from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional


OutcomeCallback = Callable[[str, Any, Optional[Dict[str, Any]]], None]


@dataclass
class ParsedMessage:
    message_id: int
    channel_id: str
    publish_date: Any = None
    has_media: bool = False
    filename: Optional[str] = None
    file_size: int = 0
    media_type: Optional[str] = None
    mime_type: str = ""
    audio_meta: Optional[Dict[str, Any]] = None
    document_id: Optional[int] = None
    access_hash: Optional[int] = None
    file_reference: Any = None
    extra_fields: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Any) -> "ParsedMessage":
        if isinstance(payload, cls):
            return payload

        known_fields = {
            "message_id",
            "channel_id",
            "publish_date",
            "has_media",
            "filename",
            "file_size",
            "type",
            "media_type",
            "mime_type",
            "audio_meta",
            "document_id",
            "access_hash",
            "file_reference",
        }
        extra_fields = {
            key: value for key, value in payload.items() if key not in known_fields
        }
        return cls(
            message_id=payload["message_id"],
            channel_id=str(payload.get("channel_id", "unknown")),
            publish_date=payload.get("publish_date"),
            has_media=bool(payload.get("has_media", False)),
            filename=payload.get("filename"),
            file_size=payload.get("file_size", 0),
            media_type=payload.get("media_type") or payload.get("type"),
            mime_type=payload.get("mime_type", ""),
            audio_meta=payload.get("audio_meta"),
            document_id=payload.get("document_id"),
            access_hash=payload.get("access_hash"),
            file_reference=payload.get("file_reference"),
            extra_fields=extra_fields,
        )

    @property
    def is_downloadable(self) -> bool:
        return bool(
            self.has_media and self.filename and self.file_size and self.media_type
        )

    @property
    def has_download_locator(self) -> bool:
        return all(
            value is not None
            for value in (
                self.document_id,
                self.access_hash,
                self.file_reference,
                self.mime_type,
                self.file_size,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = dict(self.extra_fields)
        payload.update(
            {
                "message_id": self.message_id,
                "channel_id": self.channel_id,
                "publish_date": self.publish_date,
                "has_media": self.has_media,
                "filename": self.filename,
                "file_size": self.file_size,
                "type": self.media_type,
                "mime_type": self.mime_type,
                "audio_meta": self.audio_meta,
                "document_id": self.document_id,
                "access_hash": self.access_hash,
                "file_reference": self.file_reference,
            }
        )
        return payload


@dataclass
class DownloadRequest:
    message_id: int
    channel_id: str
    filename: str
    file_size: int
    media_type: str
    mime_type: str = ""
    file_tracker: Any = None
    download_dir: Optional[str] = None
    audio_meta: Optional[Dict[str, Any]] = None
    publish_date: Any = None
    document_id: Optional[int] = None
    access_hash: Optional[int] = None
    file_reference: Any = None
    outcome_callback: Optional[OutcomeCallback] = None
    extra_fields: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_parsed_message(
        cls,
        parsed_message: Any,
        file_tracker: Any = None,
        download_dir: Optional[str] = None,
        outcome_callback: Optional[OutcomeCallback] = None,
    ) -> "DownloadRequest":
        parsed = ParsedMessage.from_payload(parsed_message)
        return cls(
            message_id=parsed.message_id,
            channel_id=parsed.channel_id,
            filename=parsed.filename or f"file_{parsed.message_id}.bin",
            file_size=parsed.file_size,
            media_type=parsed.media_type or "document",
            mime_type=parsed.mime_type,
            file_tracker=file_tracker,
            download_dir=download_dir,
            audio_meta=parsed.audio_meta,
            publish_date=parsed.publish_date,
            document_id=parsed.document_id,
            access_hash=parsed.access_hash,
            file_reference=parsed.file_reference,
            outcome_callback=outcome_callback,
            extra_fields=dict(parsed.extra_fields),
        )

    @classmethod
    def from_media_info(cls, media_info: Dict[str, Any]) -> "DownloadRequest":
        normalized = {
            "message_id": media_info["message_id"],
            "channel_id": str(media_info.get("channel_id", "unknown")),
            "filename": media_info["filename"],
            "file_size": media_info["file_size"],
            "media_type": media_info.get("type") or media_info.get("media_type"),
            "mime_type": media_info.get("mime_type", ""),
            "file_tracker": media_info.get("file_tracker"),
            "download_dir": media_info.get("download_dir"),
            "audio_meta": media_info.get("audio_meta"),
            "publish_date": media_info.get("publish_date"),
            "document_id": media_info.get("document_id"),
            "access_hash": media_info.get("access_hash"),
            "file_reference": media_info.get("file_reference"),
            "outcome_callback": media_info.get("outcome_callback"),
        }
        extra_fields = {
            key: value
            for key, value in media_info.items()
            if key
            not in {
                "message_id",
                "channel_id",
                "filename",
                "file_size",
                "type",
                "media_type",
                "mime_type",
                "file_tracker",
                "download_dir",
                "audio_meta",
                "publish_date",
                "document_id",
                "access_hash",
                "file_reference",
                "outcome_callback",
            }
        }
        return cls(extra_fields=extra_fields, **normalized)

    @classmethod
    def from_payload(cls, payload: Any) -> "DownloadRequest":
        if isinstance(payload, cls):
            return payload
        if isinstance(payload, ParsedMessage):
            return cls.from_parsed_message(payload)
        return cls.from_media_info(payload)

    def to_media_info(self) -> Dict[str, Any]:
        media_info = dict(self.extra_fields)
        media_info.update(
            {
                "message_id": self.message_id,
                "channel_id": self.channel_id,
                "filename": self.filename,
                "file_size": self.file_size,
                "type": self.media_type,
                "mime_type": self.mime_type,
                "file_tracker": self.file_tracker,
                "download_dir": self.download_dir,
                "audio_meta": self.audio_meta,
                "publish_date": self.publish_date,
                "document_id": self.document_id,
                "access_hash": self.access_hash,
                "file_reference": self.file_reference,
                "outcome_callback": self.outcome_callback,
            }
        )
        return media_info

    @property
    def has_locator(self) -> bool:
        return all(
            value is not None
            for value in (
                self.document_id,
                self.access_hash,
                self.file_reference,
                self.mime_type,
                self.file_size,
            )
        )

    def missing_locator_fields(self) -> list[str]:
        missing = []
        for field_name in (
            "document_id",
            "access_hash",
            "file_reference",
            "mime_type",
            "file_size",
        ):
            if getattr(self, field_name) is None:
                missing.append(field_name)
        return missing


@dataclass
class DownloadOutcome:
    status: str
    reason: Optional[str] = None
    file_path: Optional[str] = None
    file_hash: Optional[str] = None
    already_existed: bool = False
    logged: bool = False

    @classmethod
    def from_result(cls, result: Dict[str, Any]) -> "DownloadOutcome":
        return cls(
            status=result.get("status", "failed"),
            reason=result.get("reason"),
            file_path=result.get("file_path"),
            file_hash=result.get("file_hash"),
            already_existed=bool(result.get("already_existed", False)),
            logged=bool(result.get("logged", False)),
        )

    @classmethod
    def from_payload(cls, payload: Any) -> "DownloadOutcome":
        if isinstance(payload, cls):
            return payload
        return cls.from_result(payload)

    @property
    def terminal_outcome(self) -> str:
        if self.status == "success":
            return "completed"
        if self.status == "skipped":
            return "skipped"
        return "failed"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChannelContext:
    channel_name: str
    channel_id: str
    channel_title: str
    entity: Any
    message_tracker: Any
    file_tracker: Any
    download_dir: Path
    last_processed_id: Optional[int] = None


@dataclass
class ChannelProcessingResult:
    channel_name: str
    channel_title: str
    channel_id: str
    files_found: int = 0
    files_queued: int = 0
    messages_processed: int = 0
    last_processed_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QueuedMessageContext:
    message_id: int
    filename: str
    request: DownloadRequest
    file_info_str: str = ""


@dataclass
class ScanState:
    schema_version: int
    channel_id: str
    last_safe_message_id: Optional[int] = None
    total_messages_processed: int = 0
    last_updated: Optional[str] = None


@dataclass
class DownloadState:
    schema_version: int
    channel_id: str
    downloaded_files: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    blacklisted_message_ids: list[int] = field(default_factory=list)
    total_files: int = 0
    last_updated: Optional[str] = None
