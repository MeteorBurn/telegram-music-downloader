"""Local web UI: FastAPI application exposing the downloader controls."""

import asyncio
import json
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from logger import get_logger
from web_auth import AuthFlowError, TelegramAuthService
from web_config import ConfigValidationError, WebConfigService
from web_logs import LogBuffer, attach_log_buffer
from web_session import SessionBusyError, SessionIdleError, WebSessionManager

STATIC_DIR = Path(__file__).parent / "web_static"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
WILDCARD_HOSTS = ("", "0.0.0.0", "::", "[::]")
SSE_PING_SECONDS = 15
UNSAFE_METHODS = ("POST", "PUT", "DELETE")

UNKNOWN_AUTH = {"state": "unknown", "user": None, "phone_masked": None}

# The Windows registry can map .js to text/plain, which breaks ES module loading.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/woff2", ".woff2")


def error_response(
    status: int, code: str, message: str, details: Optional[list] = None
) -> JSONResponse:
    error: Dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse({"error": error}, status_code=status)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


async def read_json_object(request: Request, allow_empty: bool = False) -> Dict[str, Any]:
    raw = await request.body()
    if not raw.strip():
        if allow_empty:
            return {}
        raise ApiError(400, "invalid_body", "Request body must be a JSON object")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "invalid_body", "Request body is not valid JSON")
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_body", "Request body must be a JSON object")
    return data


def require_string(data: Dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ApiError(400, "invalid_body", f"'{key}' must be a string")
    return value


def parse_int(value: Any, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ApiError(400, "invalid", f"'{name}' must be an integer >= {minimum}")
    return value


def create_app(
    config_path: str,
    *,
    session_manager: Optional[WebSessionManager] = None,
    config_service: Optional[WebConfigService] = None,
    auth_service: Optional[TelegramAuthService] = None,
    log_buffer: Optional[LogBuffer] = None,
    allowed_hosts: Optional[Iterable[str]] = None,
) -> FastAPI:
    if log_buffer is None:
        log_buffer = LogBuffer()
        attach_log_buffer(log_buffer)
    sessions = session_manager or WebSessionManager(config_path, log_buffer)
    configs = config_service or WebConfigService(config_path)
    auth = auth_service or TelegramAuthService(config_path)
    logger = get_logger()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            await sessions.shutdown()
            await auth.close()

    app = FastAPI(
        title="Telegram Music Downloader",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    hosts = list(LOOPBACK_HOSTS)
    for host in allowed_hosts or ():
        if host not in WILDCARD_HOSTS and host not in hosts:
            hosts.append(host)
    app.state.allowed_hosts = hosts

    @app.middleware("http")
    async def require_json_content_type(request: Request, call_next):
        if request.method in UNSAFE_METHODS and request.url.path.startswith("/api"):
            content_type = request.headers.get("content-type", "")
            if content_type.split(";")[0].strip().lower() != "application/json":
                return error_response(
                    415,
                    "unsupported_media_type",
                    "Content-Type must be application/json",
                )
        return await call_next(request)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(SessionBusyError)
    async def handle_busy(_request: Request, exc: SessionBusyError):
        return error_response(409, "busy", str(exc))

    @app.exception_handler(SessionIdleError)
    async def handle_idle(_request: Request, exc: SessionIdleError):
        return error_response(409, "idle", str(exc))

    @app.exception_handler(ConfigValidationError)
    async def handle_validation(_request: Request, exc: ConfigValidationError):
        return error_response(400, "validation", "Invalid configuration", list(exc.errors))

    @app.exception_handler(AuthFlowError)
    async def handle_auth_error(_request: Request, exc: AuthFlowError):
        return error_response(400, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception):
        logger.error(f"Unhandled web error: {exc!r}", exc_info=exc)
        return error_response(500, "internal", "Internal server error")

    def ensure_not_running() -> None:
        if sessions.is_running():
            raise SessionBusyError("A download session is running")

    # --- health and session -------------------------------------------------

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/session")
    async def session_status():
        return sessions.status()

    @app.post("/api/session/start")
    async def session_start(request: Request):
        data = await read_json_object(request, allow_empty=True)
        max_files = parse_int(data.get("max_files", 0), "max_files", 0)
        workers = data.get("workers")
        if workers is not None:
            workers = parse_int(workers, "workers", 1)
        ensure_not_running()
        status = await auth.status()
        if status.get("state") != "authorized":
            return error_response(
                412, "not_authorized", "Telegram session is not authorized"
            )
        try:
            await sessions.start(max_files=max_files, workers=workers)
        except (SessionBusyError, SessionIdleError):
            raise
        except ValueError as exc:
            raise ApiError(400, "invalid", str(exc))
        return JSONResponse(sessions.status(), status_code=202)

    @app.post("/api/session/stop")
    async def session_stop(request: Request):
        await read_json_object(request, allow_empty=True)
        await sessions.stop()
        return JSONResponse(sessions.status(), status_code=202)

    # --- statistics and cleanup ---------------------------------------------

    @app.get("/api/stats")
    async def stats():
        return await sessions.statistics()

    @app.post("/api/cleanup")
    async def cleanup(request: Request):
        await read_json_object(request, allow_empty=True)
        ensure_not_running()
        return {"removed": await sessions.cleanup()}

    # --- configuration -------------------------------------------------------

    @app.get("/api/config")
    async def get_config():
        return await asyncio.to_thread(configs.read)

    @app.put("/api/config")
    async def put_config(request: Request):
        data = await read_json_object(request)
        ensure_not_running()
        return await asyncio.to_thread(configs.update, data)

    # --- authentication ------------------------------------------------------

    @app.get("/api/auth")
    async def get_auth():
        if sessions.is_running():
            return auth.cached_status() or UNKNOWN_AUTH
        return await auth.status()

    @app.post("/api/auth/phone")
    async def auth_phone(request: Request):
        data = await read_json_object(request)
        phone = require_string(data, "phone")
        ensure_not_running()
        return await auth.send_code(phone)

    @app.post("/api/auth/code")
    async def auth_code(request: Request):
        data = await read_json_object(request)
        code = require_string(data, "code")
        ensure_not_running()
        return await auth.submit_code(code)

    @app.post("/api/auth/password")
    async def auth_password(request: Request):
        data = await read_json_object(request)
        password = require_string(data, "password")
        ensure_not_running()
        return await auth.submit_password(password)

    @app.post("/api/auth/cancel")
    async def auth_cancel(request: Request):
        await read_json_object(request, allow_empty=True)
        ensure_not_running()
        return await auth.cancel()

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request):
        await read_json_object(request, allow_empty=True)
        ensure_not_running()
        return await auth.log_out()

    # --- logs ----------------------------------------------------------------

    @app.get("/api/logs")
    async def get_logs(request: Request):
        try:
            limit = int(request.query_params.get("limit", "500"))
            after_id = int(request.query_params.get("after_id", "0"))
        except ValueError:
            raise ApiError(400, "invalid", "'limit' and 'after_id' must be integers")
        if limit < 0 or after_id < 0:
            raise ApiError(400, "invalid", "'limit' and 'after_id' must be >= 0")
        return {"entries": log_buffer.snapshot(limit=limit, after_id=after_id)}

    @app.get("/api/logs/stream")
    async def logs_stream(request: Request):
        queue = log_buffer.subscribe()

        async def event_stream():
            try:
                yield ": ping\n\n"
                while not await request.is_disconnected():
                    try:
                        entry = await asyncio.wait_for(queue.get(), SSE_PING_SECONDS)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield f"event: log\ndata: {json.dumps(entry)}\n\n"
            finally:
                log_buffer.unsubscribe(queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- static UI -----------------------------------------------------------

    @app.get("/")
    async def index():
        index_file = STATIC_DIR / "index.html"
        if not index_file.is_file():
            return error_response(503, "ui_missing", "Web UI files are missing")
        return FileResponse(index_file, headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")

    return app


def run_web(config_path: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    app = create_app(config_path, allowed_hosts=[host])
    display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    print(f"Web UI: http://{display_host}:{port}")
    if host not in LOOPBACK_HOSTS and host != "::1":
        print(
            "WARNING: the web UI has no authentication; anyone who can reach "
            f"{host}:{port} can control the downloader."
        )
    uvicorn.run(app, host=host, port=port, log_level="warning")
