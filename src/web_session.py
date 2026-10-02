import asyncio
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from app import SessionRunner, cleanup_missing_entries, collect_statistics
from channels import create_media_filter
from config import ConfigLoader
from logger import emit_session_message, get_logger, log_exception
from state import TrackerManager
from telegram import TelegramNotAuthorizedError
from web_logs import LogBuffer, attach_log_buffer


ACTIVE_STATES = {"connecting", "running", "stopping"}
RECENT_FILES_LIMIT = 50


class SessionBusyError(RuntimeError):
    """The requested operation conflicts with an active download session."""


class SessionIdleError(RuntimeError):
    """A stop was requested while no download session is running."""


def to_json_safe(value: Any) -> Any:
    """Convert nested values into types accepted by json.dumps."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _validate_int(value: Any, name: str, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


class WebSessionManager:
    """Runs one download session at a time in the background for the web UI."""

    def __init__(
        self,
        config_path: str,
        log_buffer: LogBuffer,
        runner_factory: Callable[[str], Any] = SessionRunner,
    ) -> None:
        self.config_path = config_path
        self.log_buffer = log_buffer
        self.runner_factory = runner_factory
        self.logger = get_logger()
        self._task: Optional[asyncio.Task] = None
        self._runner: Any = None
        self._state = "idle"
        self._started_at: Optional[datetime] = None
        self._finished_at: Optional[datetime] = None
        self._options: Dict[str, Any] = {"max_files": 0, "workers": None}
        self._error: Optional[Dict[str, str]] = None
        self._results: Optional[Dict[str, Any]] = None
        self._summary: Optional[Dict[str, Any]] = None

    def is_running(self) -> bool:
        return self._state in ACTIVE_STATES

    async def start(self, max_files: int = 0, workers: Optional[int] = None) -> None:
        _validate_int(max_files, "max_files", minimum=0)
        if workers is not None:
            _validate_int(workers, "workers", minimum=1)
        if self.is_running():
            raise SessionBusyError("A download session is already running")

        self._runner = None
        self._state = "connecting"
        self._started_at = datetime.now()
        self._finished_at = None
        self._options = {"max_files": max_files, "workers": workers}
        self._error = None
        self._results = None
        self._summary = None
        self._task = asyncio.create_task(self._run_session(max_files, workers))
        self._task.add_done_callback(self._on_task_done)

    async def _run_session(self, max_files: int, workers: Optional[int]) -> None:
        runner = None
        try:
            runner = self.runner_factory(self.config_path)
            self._runner = runner
            # SessionRunner construction resets the logger handlers.
            attach_log_buffer(self.log_buffer)

            if workers is not None:
                runner.config._config["download"]["concurrent_downloads"] = workers
                emit_session_message(
                    f"Using {workers} concurrent workers (overridden from the web UI)",
                    logger=runner.logger,
                )

            await runner.initialize_client(interactive=False)
            if self._state == "connecting":
                self._state = "running"
            results = await runner.run_download_session(max_files)
            self._results = to_json_safe(results)
            self._capture_summary(runner)
            self._state = "finished"
        except TelegramNotAuthorizedError as exc:
            self._state = "failed"
            self._error = {
                "code": "not_authorized",
                "message": str(exc) or "Telegram session is not authorized",
            }
            self.logger.error(f"[FAIL] Telegram session is not authorized: {exc}")
        except asyncio.CancelledError:
            self._state = "stopped"
            self._capture_summary(runner)
            self.logger.info("[STOP] Download session stopped from the web UI")
        except Exception as exc:
            attach_log_buffer(self.log_buffer)
            self._state = "failed"
            self._error = {"code": "error", "message": str(exc) or type(exc).__name__}
            log_exception(f"Error: {exc}", logger=self.logger)
        finally:
            if runner is not None:
                try:
                    await runner.close()
                except Exception as exc:
                    log_exception(f"Failed to close session: {exc}", logger=self.logger)
            self._finished_at = datetime.now()

    def _capture_summary(self, runner: Any) -> None:
        coordinator = getattr(runner, "download_coordinator", None)
        if coordinator is None or self._summary is not None:
            return
        try:
            self._summary = to_json_safe(coordinator.get_session_summary())
        except Exception as exc:
            self.logger.warning(f"[WARN] Failed to read session summary: {exc}")

    def _on_task_done(self, task: asyncio.Task) -> None:
        # A task cancelled before its first step never runs its own handlers.
        if task.cancelled() and self.is_running():
            self._state = "stopped"
            self._finished_at = datetime.now()

    async def stop(self) -> None:
        task = self._task
        if not self.is_running() or task is None:
            raise SessionIdleError("No download session is running")
        if self._state != "stopping":
            self._state = "stopping"
            task.cancel()
        # asyncio.wait never re-raises the task's CancelledError.
        await asyncio.wait({task})

    def status(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "state": self._state,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "options": dict(self._options),
            "error": self._error,
            "total_channels": None,
            "current_channel": None,
            "channels_done": [],
            "progress": None,
            "results": self._results,
            "summary": self._summary,
        }
        try:
            runner = self._runner
            if runner is not None:
                config = getattr(runner, "config", None)
                if config is not None:
                    payload["total_channels"] = len(config.get_channels() or [])
                payload["current_channel"] = getattr(runner, "current_channel", None)
                session_results = getattr(runner, "session_results", None)
                if session_results:
                    payload["channels_done"] = [
                        dict(detail)
                        for detail in session_results.get("channels_details", [])
                    ]
                coordinator = getattr(runner, "download_coordinator", None)
                if coordinator is not None and getattr(
                    coordinator, "is_running", False
                ):
                    payload["progress"] = coordinator.get_progress_info()
        except Exception as exc:
            self.logger.debug(f"Failed to read live session status: {exc}")
        return to_json_safe(payload)

    async def statistics(self) -> Dict[str, Any]:
        return await asyncio.to_thread(self._collect_statistics)

    def _collect_statistics(self) -> Dict[str, Any]:
        config = ConfigLoader(self.config_path)
        tracker_manager = TrackerManager(config.get_download_dir())
        media_filter = create_media_filter(config)
        return to_json_safe(
            collect_statistics(
                config, tracker_manager, media_filter, recent_limit=RECENT_FILES_LIMIT
            )
        )

    async def cleanup(self) -> int:
        if self.is_running():
            raise SessionBusyError("Cleanup is not available while a session runs")
        return await asyncio.to_thread(self._cleanup)

    def _cleanup(self) -> int:
        config = ConfigLoader(self.config_path)
        tracker_manager = TrackerManager(config.get_download_dir())
        return cleanup_missing_entries(tracker_manager, self.logger)

    async def shutdown(self) -> None:
        if not self.is_running():
            return
        try:
            await self.stop()
        except SessionIdleError:
            pass
