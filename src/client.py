import asyncio
from typing import Optional

from logger import get_logger

try:
    from telethon import TelegramClient
    from telethon.errors import (
        PasswordHashInvalidError,
        PhoneCodeInvalidError,
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

    class SessionPasswordNeededError(Exception):
        pass

    class PhoneCodeInvalidError(Exception):
        pass

    class PasswordHashInvalidError(Exception):
        pass


class TelegramMusicClient:
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str,
        two_factor_enabled: bool = False,
    ):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.two_factor_enabled = two_factor_enabled
        self.client: Optional[TelegramClient] = None
        self.logger = get_logger()

    async def connect(self) -> bool:
        """Connect and authenticate with Telegram"""
        try:
            if not TELETHON_AVAILABLE:
                raise RuntimeError(
                    "Telethon is required to connect to Telegram. Install project dependencies first."
                )
            self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            await self.client.connect()

            if not await self.client.is_user_authorized():
                self.logger.info("User not authorized, starting authentication")
                await self._authenticate()
            else:
                self.logger.info("User already authorized")

            self.logger.info("Successfully connected to Telegram")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect: {e}")
            return False

    async def _authenticate(self) -> None:
        """Handle interactive authentication process"""
        phone = input("Enter your phone number (with country code): ")

        try:
            await self.client.send_code_request(phone)
            code = input("Enter the verification code: ")

            try:
                await self.client.sign_in(phone, code)
            except SessionPasswordNeededError:
                if self.two_factor_enabled:
                    password = input("Enter your 2FA password: ")
                    await self.client.sign_in(password=password)
                else:
                    raise Exception("2FA is required but not enabled in config")

        except PhoneCodeInvalidError:
            self.logger.error("Invalid verification code")
            raise
        except PasswordHashInvalidError:
            self.logger.error("Invalid 2FA password")
            raise

    async def disconnect(self) -> None:
        """Disconnect from Telegram"""
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            self.logger.info("Disconnected from Telegram")

    def get_client(self) -> TelegramClient:
        """Get the Telegram client instance"""
        if not self.client:
            raise RuntimeError("Client not initialized. Call connect() first")
        return self.client

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect()


async def create_client(config_loader) -> TelegramMusicClient:
    """Create and configure Telegram client from config"""
    api_id = config_loader.get_api_id()
    api_hash = config_loader.get_api_hash()
    session_name = config_loader.get_full_session_path()
    two_factor_enabled = config_loader.is_two_factor_enabled()

    client = TelegramMusicClient(
        api_id=api_id,
        api_hash=api_hash,
        session_name=session_name,
        two_factor_enabled=two_factor_enabled,
    )

    return client
