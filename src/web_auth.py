import asyncio
import re
from typing import Any, Callable, Dict, Optional

from config import ConfigLoader
from logger import get_logger

try:
    from telethon import TelegramClient
    from telethon.errors import (
        FloodWaitError,
        PasswordHashInvalidError,
        PhoneCodeExpiredError,
        PhoneCodeInvalidError,
        PhoneNumberInvalidError,
        SessionPasswordNeededError,
    )

    TELETHON_AVAILABLE = True
except ModuleNotFoundError:
    TELETHON_AVAILABLE = False

    class TelegramClient:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "Telethon is required to connect to Telegram. Install project dependencies first."
            )

    class FloodWaitError(Exception):  # type: ignore[no-redef]
        seconds = 0

    class PasswordHashInvalidError(Exception):  # type: ignore[no-redef]
        pass

    class PhoneCodeExpiredError(Exception):  # type: ignore[no-redef]
        pass

    class PhoneCodeInvalidError(Exception):  # type: ignore[no-redef]
        pass

    class PhoneNumberInvalidError(Exception):  # type: ignore[no-redef]
        pass

    class SessionPasswordNeededError(Exception):  # type: ignore[no-redef]
        pass


PHONE_PATTERN = re.compile(r"^\+?\d{7,15}$")


class AuthFlowError(RuntimeError):
    """A login step failed; ``code`` is a stable machine-readable identifier."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def mask_phone(phone: Optional[str]) -> Optional[str]:
    """Keep a leading '+', the first two and the last two digits."""
    if not phone:
        return None
    plus = "+" if phone.startswith("+") else ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 4:
        return plus + "*" * len(digits)
    return plus + digits[:2] + "*" * (len(digits) - 4) + digits[-2:]


def _default_client_factory(config_loader: ConfigLoader) -> Any:
    return TelegramClient(
        config_loader.get_full_session_path(),
        config_loader.get_api_id(),
        config_loader.get_api_hash(),
    )


class TelegramAuthService:
    """Interactive Telegram login for the web UI, one pending login at a time."""

    def __init__(
        self,
        config_path: str,
        client_factory: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self.config_path = config_path
        self._client_factory = client_factory or _default_client_factory
        self._lock = asyncio.Lock()
        self._logger = get_logger()
        self._client: Any = None
        self._state = "unauthorized"
        self._phone: Optional[str] = None
        self._phone_code_hash: Optional[str] = None
        self._user: Optional[Dict[str, Any]] = None
        self._cached: Optional[Dict[str, Any]] = None

    def cached_status(self) -> Optional[Dict[str, Any]]:
        return self._cached

    async def status(self) -> Dict[str, Any]:
        async with self._lock:
            if self._state in ("code_sent", "password_needed"):
                return self._remember()
            try:
                client = await self._connected_client()
                if await client.is_user_authorized():
                    self._state = "authorized"
                    self._user = self._describe_user(await client.get_me())
                else:
                    self._state = "unauthorized"
                    self._user = None
                await self._disconnect()
                return self._remember()
            except Exception as exc:
                await self._fail(exc)

    async def send_code(self, phone: str) -> Dict[str, Any]:
        cleaned = re.sub(r"[\s\-()]", "", phone or "")
        if not PHONE_PATTERN.match(cleaned):
            raise AuthFlowError("invalid_phone", "Enter the phone number in international format.")
        async with self._lock:
            try:
                client = await self._connected_client()
                if await client.is_user_authorized():
                    self._state = "authorized"
                    self._user = self._describe_user(await client.get_me())
                    await self._disconnect()
                    return self._remember()
                sent = await client.send_code_request(cleaned)
                self._phone = cleaned
                self._phone_code_hash = getattr(sent, "phone_code_hash", None)
                self._state = "code_sent"
                self._user = None
                return self._remember()
            except Exception as exc:
                await self._fail(exc)

    async def submit_code(self, code: str) -> Dict[str, Any]:
        async with self._lock:
            self._require("code_sent")
            digits = re.sub(r"\D", "", code or "")
            try:
                user = await self._client.sign_in(
                    phone=self._phone, code=digits, phone_code_hash=self._phone_code_hash
                )
            except SessionPasswordNeededError:
                self._state = "password_needed"
                return self._remember()
            except PhoneCodeInvalidError:
                raise AuthFlowError("invalid_code", "The code is incorrect.")
            except PhoneCodeExpiredError:
                await self._reset()
                self._remember()
                raise AuthFlowError("code_expired", "The code has expired. Request a new one.")
            except Exception as exc:
                await self._fail(exc)
            return await self._complete(user)

    async def submit_password(self, password: str) -> Dict[str, Any]:
        async with self._lock:
            self._require("password_needed")
            try:
                user = await self._client.sign_in(password=password)
            except PasswordHashInvalidError:
                raise AuthFlowError("invalid_password", "The password is incorrect.")
            except Exception as exc:
                await self._fail(exc)
            return await self._complete(user)

    async def cancel(self) -> Dict[str, Any]:
        async with self._lock:
            self._clear_pending()
            await self._disconnect()
            self._state = "unauthorized"
        return await self.status()

    async def log_out(self) -> Dict[str, Any]:
        async with self._lock:
            try:
                client = await self._connected_client()
                await client.log_out()
            except Exception as exc:
                await self._fail(exc)
            self._clear_pending()
            self._state = "unauthorized"
            self._user = None
            await self._disconnect()
            return self._remember()

    async def close(self) -> None:
        async with self._lock:
            await self._disconnect()

    # -- internals (callers hold the lock) --

    def _require(self, state: str) -> None:
        if self._state != state or self._client is None:
            raise AuthFlowError("no_pending_login", "No login is in progress.")

    async def _connected_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(ConfigLoader(self.config_path))
        if not self._client.is_connected():
            await self._client.connect()
        return self._client

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None and client.is_connected():
            await client.disconnect()

    def _clear_pending(self) -> None:
        self._phone = None
        self._phone_code_hash = None

    async def _reset(self) -> None:
        self._clear_pending()
        self._state = "unauthorized"
        self._user = None
        await self._disconnect()

    async def _complete(self, user: Any) -> Dict[str, Any]:
        self._state = "authorized"
        self._user = self._describe_user(user, self._phone)
        self._clear_pending()
        await self._disconnect()
        return self._remember()

    async def _fail(self, exc: Exception) -> None:
        """Translate any exception into AuthFlowError, resetting the pending login."""
        if isinstance(exc, AuthFlowError):
            raise exc
        await self._reset()
        self._remember()
        if isinstance(exc, PhoneNumberInvalidError):
            raise AuthFlowError("invalid_phone", "Telegram rejected this phone number.") from exc
        if isinstance(exc, FloodWaitError):
            seconds = getattr(exc, "seconds", 0)
            raise AuthFlowError(
                "flood_wait", f"Too many attempts. Wait {seconds} seconds and try again."
            ) from exc
        self._logger.warning(f"[AUTH] Login step failed: {type(exc).__name__}")
        raise AuthFlowError("error", f"Telegram login failed: {type(exc).__name__}") from exc

    @staticmethod
    def _describe_user(user: Any, fallback_phone: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if user is None:
            return None
        phone = getattr(user, "phone", None) or fallback_phone
        return {
            "id": getattr(user, "id", None),
            "first_name": getattr(user, "first_name", None) or "",
            "last_name": getattr(user, "last_name", None) or "",
            "username": getattr(user, "username", None) or "",
            "phone_masked": mask_phone(str(phone)) if phone else None,
        }

    def _remember(self) -> Dict[str, Any]:
        pending = self._state in ("code_sent", "password_needed")
        self._cached = {
            "state": self._state,
            "user": self._user if self._state == "authorized" else None,
            "phone_masked": mask_phone(self._phone) if pending else None,
        }
        return dict(self._cached)
