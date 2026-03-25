import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional

from logger import get_logger
from models import DownloadRequest, ParsedMessage

try:
    from telethon import TelegramClient
    from telethon.errors import (
        PasswordHashInvalidError,
        PhoneCodeInvalidError,
        RpcMcgetFailError,
        SessionPasswordNeededError,
    )
    from telethon.tl.types import Document
    from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeFilename

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

    class RpcMcgetFailError(Exception):
        pass

    class Document:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class DocumentAttributeAudio:  # type: ignore[no-redef]
        pass

    class DocumentAttributeFilename:  # type: ignore[no-redef]
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
        try:
            if not TELETHON_AVAILABLE:
                raise RuntimeError(
                    "Telethon is required to connect to Telegram. Install project dependencies first."
                )
            self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            await self.client.connect()

            if not await self.client.is_user_authorized():
                self.logger.info("[AUTH] User not authorized, starting authentication")
                await self._authenticate()
            else:
                self.logger.info("[AUTH] User already authorized")

            self.logger.info("[AUTH] Successfully connected to Telegram")
            return True
        except Exception as exc:
            self.logger.error(f"[FAIL] Failed to connect to Telegram: {exc}")
            return False

    async def _authenticate(self) -> None:
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
            self.logger.error("[AUTH] Invalid verification code")
            raise
        except PasswordHashInvalidError:
            self.logger.error("[AUTH] Invalid 2FA password")
            raise

    async def disconnect(self) -> None:
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            self.logger.info("[AUTH] Disconnected from Telegram")

    def get_client(self) -> TelegramClient:
        if not self.client:
            raise RuntimeError("Client not initialized. Call connect() first")
        return self.client

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


async def create_client(config_loader) -> TelegramMusicClient:
    return TelegramMusicClient(
        api_id=config_loader.get_api_id(),
        api_hash=config_loader.get_api_hash(),
        session_name=config_loader.get_full_session_path(),
        two_factor_enabled=config_loader.is_two_factor_enabled(),
    )


class MessageParser:
    def __init__(self, client, config_loader):
        self.client = client
        self.config = config_loader
        self.logger = get_logger()

    async def get_channels_entities(self) -> List[tuple]:
        channels = self.config.get_channels()
        entities = []

        for channel in channels:
            try:
                entity = await self.client.get_entity(channel)
                entities.append((channel, entity))
                self.logger.info(
                    f"[CHANNEL] Entity resolved: {channel} -> {entity.title}"
                )
            except Exception as exc:
                self.logger.error(f"[FAIL] Failed to get entity for {channel}: {exc}")

        return entities

    async def parse_messages(
        self,
        entity,
        last_processed_id: Optional[int] = None,
        limit: Optional[int] = None,
        config_channel_id: Optional[str] = None,
    ) -> AsyncIterator[ParsedMessage]:
        timeout = self.config.get_message_timeout()

        try:
            kwargs = {
                "limit": limit,
                "reverse": True,
            }

            date_filter = self.config.get_date_filter()
            date_from = date_filter.get("from")

            if (
                last_processed_id is not None
                and isinstance(last_processed_id, int)
                and last_processed_id > 0
            ):
                kwargs["min_id"] = last_processed_id
                self.logger.info(
                    f"Parsing messages from channel {entity.title} starting after message ID {last_processed_id}"
                )
            elif date_from is not None:
                kwargs["offset_date"] = date_from
                self.logger.info(
                    f"Parsing messages from channel {entity.title} starting from date {date_from.strftime('%Y-%m-%d')}"
                )
            else:
                self.logger.info(
                    f"Parsing messages from channel {entity.title} from the beginning"
                )

            message_count = 0
            async for message in self.client.iter_messages(entity, **kwargs):
                message_count += 1

                if timeout > 0 and message_count > 1:
                    self.logger.debug(
                        f"Waiting {timeout}s before processing next message..."
                    )
                    await asyncio.sleep(timeout)

                channel_id_to_use = (
                    config_channel_id
                    if config_channel_id is not None
                    else str(entity.id)
                )
                base_message = ParsedMessage(
                    message_id=message.id,
                    channel_id=channel_id_to_use,
                    publish_date=message.date,
                    has_media=bool(message.media),
                )

                if not message.media:
                    self.logger.debug(f"Message {message.id} has no media")
                    yield base_message
                    continue

                media_info = await self._extract_media_info(message)
                if not media_info:
                    self.logger.debug(
                        f"Failed to extract media info from message {message.id}"
                    )
                    yield base_message
                    continue

                full_info = ParsedMessage.from_payload(
                    {**base_message.to_dict(), **media_info}
                )
                self.logger.debug(
                    f"Found media in message {message.id}: {full_info.filename or 'unknown'} ({full_info.media_type or 'unknown'})"
                )
                yield full_info
        except RpcMcgetFailError as exc:
            self.logger.warning(f"[WARN] Telegram internal issues: {exc}")
            self.logger.info("[WARN] Waiting 60 seconds before retry...")
            await asyncio.sleep(60)
        except Exception as exc:
            self.logger.error(
                f"[FAIL] Error parsing messages from {entity.title}: {exc}"
            )

    async def _extract_media_info(self, message) -> Optional[Dict]:
        if not hasattr(message.media, "document"):
            return None

        document = message.media.document
        if not document:
            return None

        if document.mime_type and document.mime_type.startswith("audio/"):
            media_type = "audio"
        else:
            media_type = "document"

        filename = None
        for attr in document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                filename = attr.file_name
                break
            if isinstance(attr, DocumentAttributeAudio):
                if hasattr(attr, "title") and attr.title:
                    filename = f"{attr.title}.{self._get_extension_from_mime(document.mime_type)}"

        if not filename:
            ext = self._get_extension_from_mime(document.mime_type)
            filename = f"file_{message.id}.{ext}"

        audio_meta = None
        for attr in document.attributes:
            if isinstance(attr, DocumentAttributeAudio):
                audio_meta = {
                    "duration": getattr(attr, "duration", None),
                    "title": getattr(attr, "title", None),
                    "performer": getattr(attr, "performer", None),
                }
                break

        return {
            "filename": filename,
            "file_size": document.size,
            "mime_type": document.mime_type,
            "type": media_type,
            "audio_meta": audio_meta,
            "document_id": document.id,
            "access_hash": document.access_hash,
            "file_reference": document.file_reference,
        }

    def _get_extension_from_mime(self, mime_type: str) -> str:
        mime_map = {
            "audio/flac": "flac",
            "audio/wav": "wav",
            "audio/x-wav": "wav",
            "audio/aiff": "aiff",
            "audio/x-aiff": "aiff",
            "audio/mp4": "m4a",
            "audio/m4a": "m4a",
            "audio/x-m4a": "m4a",
            "audio/mpeg": "mp3",
            "audio/mp3": "mp3",
        }
        return mime_map.get(mime_type, "bin")

    async def get_channel_stats(self, entity) -> Dict:
        try:
            total_messages = 0
            media_messages = 0
            audio_files = 0
            document_files = 0

            async for message in self.client.iter_messages(entity, limit=100):
                total_messages += 1

                if message.media and hasattr(message.media, "document"):
                    media_messages += 1
                    document = message.media.document

                    if document.mime_type and document.mime_type.startswith("audio/"):
                        audio_files += 1
                    else:
                        document_files += 1

            return {
                "total_messages_sampled": total_messages,
                "media_messages": media_messages,
                "audio_files": audio_files,
                "document_files": document_files,
                "media_percentage": (media_messages / total_messages * 100)
                if total_messages > 0
                else 0,
            }
        except Exception as exc:
            self.logger.error(f"[FAIL] Error getting channel stats: {exc}")
            return {}


def create_message_parser(client, config_loader) -> MessageParser:
    return MessageParser(client, config_loader)


class TelegramDocumentLocator:
    def __init__(self):
        self.logger = get_logger()

    def create_message_for_request(self, payload: Any) -> Optional[Any]:
        request = DownloadRequest.from_payload(payload)
        if not request.has_locator:
            missing_fields = ", ".join(request.missing_locator_fields()) or "unknown"
            self.logger.error(
                f"Missing Telegram locator fields for message {request.message_id}: {missing_fields}"
            )
            return None

        document = Document(
            id=request.document_id,
            access_hash=request.access_hash,
            file_reference=request.file_reference,
            size=request.file_size,
            dc_id=1,
            mime_type=request.mime_type,
            attributes=[],
            date=None,
            thumbs=None,
            video_thumbs=None,
        )

        class MockMessage:
            def __init__(self, doc):
                self.media = doc
                self.media.document = doc

        return MockMessage(document)


def create_telegram_locator() -> TelegramDocumentLocator:
    return TelegramDocumentLocator()
