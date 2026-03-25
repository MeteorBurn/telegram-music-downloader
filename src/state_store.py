import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generic, Optional, Type, TypeVar

from domain_models import DownloadState, ScanState
from logger import get_logger


T = TypeVar("T")


class JsonStateStore(Generic[T]):
    def __init__(self, file_path: str, logger_name: str = __name__):
        self.file_path = Path(file_path)
        self.logger = get_logger()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self, model_cls: Type[T], defaults: Dict[str, Any]) -> T:
        if not self.file_path.exists():
            return model_cls(**defaults)

        try:
            with open(self.file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            merged_payload = dict(defaults)
            merged_payload.update(payload)
            return model_cls(**merged_payload)
        except Exception as exc:
            self.logger.error(f"Failed to load state from {self.file_path}: {exc}")
            self.logger.warning("Starting with empty state")
            return model_cls(**defaults)

    def save(self, state: T) -> None:
        payload = asdict(state)
        payload["last_updated"] = datetime.now().isoformat()
        temp_file = self.file_path.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        temp_file.replace(self.file_path)


class ScanStateStore(JsonStateStore[ScanState]):
    SCHEMA_VERSION = 2

    def __init__(self, file_path: str, channel_id: str):
        super().__init__(file_path)
        self.channel_id = str(channel_id)
        self.state = self.load(
            ScanState,
            {
                "schema_version": self.SCHEMA_VERSION,
                "channel_id": self.channel_id,
                "last_safe_message_id": None,
                "total_messages_processed": 0,
                "last_updated": None,
            },
        )

    def update_checkpoint(self, message_id: int, processed_delta: int) -> None:
        self.state.last_safe_message_id = message_id
        self.state.total_messages_processed += processed_delta
        self.save(self.state)


class DownloadStateStore(JsonStateStore[DownloadState]):
    SCHEMA_VERSION = 2

    def __init__(self, file_path: str, channel_id: str):
        super().__init__(file_path)
        self.channel_id = str(channel_id)
        self.state = self.load(
            DownloadState,
            {
                "schema_version": self.SCHEMA_VERSION,
                "channel_id": self.channel_id,
                "downloaded_files": {},
                "blacklisted_message_ids": [],
                "total_files": 0,
                "last_updated": None,
            },
        )

    def save_state(self) -> None:
        self.state.total_files = len(self.state.downloaded_files)
        self.save(self.state)
