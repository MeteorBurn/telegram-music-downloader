from typing import Any, Optional

from download_models import DownloadRequest
from logger import get_logger

try:
    from telethon.tl.types import Document
except ModuleNotFoundError:

    class Document:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)


class TelegramDocumentLocator:
    """Creates a downloadable Telegram document object from stored request data."""

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
