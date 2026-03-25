import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

from channel_utils import get_channel_downloads_dir, get_channel_state_path
from domain_models import DownloadRequest
from logger import get_logger
from state_store import DownloadStateStore, ScanStateStore


class MessageTracker:
    """Tracks scan checkpoint state for a specific channel."""

    SAFE_CHECKPOINT_OUTCOMES = {"completed", "skipped"}

    def __init__(self, tracker_file: str, channel_id: str):
        self.tracker_file = Path(tracker_file)
        self.channel_id = str(channel_id)
        self.logger = get_logger()
        self.store = ScanStateStore(str(self.tracker_file), self.channel_id)
        self.channel_id = self.store.state.channel_id

        self._pending_message_ids: list[int] = []
        self._message_outcomes: Dict[int, Optional[str]] = {}

    @property
    def last_processed_id(self) -> Optional[int]:
        return self.store.state.last_safe_message_id

    @property
    def total_messages_processed(self) -> int:
        return self.store.state.total_messages_processed

    def is_message_processed(self, message_id: int) -> bool:
        if self.last_processed_id is None:
            return False
        return message_id <= self.last_processed_id

    def mark_message_processed(self, message_id: int) -> None:
        self.register_message(message_id)
        self.mark_message_outcome(message_id, "completed")

    def register_message(self, message_id: int) -> None:
        if self.last_processed_id is not None and message_id <= self.last_processed_id:
            return
        if message_id in self._message_outcomes:
            return
        self._pending_message_ids.append(message_id)
        self._message_outcomes[message_id] = None

    def mark_message_outcome(self, message_id: int, outcome: str) -> Optional[int]:
        if outcome not in {"completed", "skipped", "failed"}:
            raise ValueError(f"Unsupported message outcome: {outcome}")

        self.register_message(message_id)
        if message_id not in self._message_outcomes:
            return self.last_processed_id

        self._message_outcomes[message_id] = outcome
        committed_until = self._commit_safe_prefix()
        self.logger.debug(
            f"Message {message_id} in channel {self.channel_id} recorded with outcome {outcome}; checkpoint={committed_until}"
        )
        return committed_until

    def _commit_safe_prefix(self) -> Optional[int]:
        committed_count = 0
        committed_until = self.last_processed_id

        while self._pending_message_ids:
            message_id = self._pending_message_ids[0]
            outcome = self._message_outcomes.get(message_id)
            if outcome not in self.SAFE_CHECKPOINT_OUTCOMES:
                break

            self._pending_message_ids.pop(0)
            self._message_outcomes.pop(message_id, None)
            committed_until = message_id
            committed_count += 1

        if committed_count > 0 and committed_until is not None:
            self.store.update_checkpoint(committed_until, committed_count)

        return committed_until

    def get_last_processed_id(self) -> Optional[int]:
        return self.last_processed_id

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.store.state.schema_version,
            "channel_id": self.channel_id,
            "total_messages_processed": self.total_messages_processed,
            "last_processed_id": self.last_processed_id,
            "tracker_file_path": str(self.tracker_file),
            "tracker_file_exists": self.tracker_file.exists(),
        }


class FileTracker:
    """Tracks downloaded files and blacklisted message IDs for a channel."""

    def __init__(self, tracker_file: str, channel_id: str):
        self.tracker_file = Path(tracker_file)
        self.channel_id = str(channel_id)
        self.logger = get_logger()
        self.store = DownloadStateStore(str(self.tracker_file), self.channel_id)
        self.channel_id = self.store.state.channel_id
        self._lock = asyncio.Lock()

    @property
    def downloaded_files(self) -> Dict[str, Dict[str, Any]]:
        return self.store.state.downloaded_files

    @property
    def blacklisted_files(self) -> set[int]:
        return set(self.store.state.blacklisted_message_ids)

    def is_file_downloaded(self, file_hash: str) -> bool:
        return file_hash in self.downloaded_files

    def is_file_blacklisted(self, message_id: int) -> bool:
        return message_id in self.blacklisted_files

    def add_blacklisted_file(self, message_id: int, reason: str = "") -> None:
        if message_id not in self.store.state.blacklisted_message_ids:
            self.store.state.blacklisted_message_ids.append(message_id)
            self.store.save_state()
        self.logger.info(f"File from message {message_id} blacklisted: {reason}")

    def remove_from_blacklist(self, message_id: int) -> None:
        if message_id in self.store.state.blacklisted_message_ids:
            self.store.state.blacklisted_message_ids.remove(message_id)
            self.store.save_state()
            self.logger.info(f"Message {message_id} removed from blacklist")

    async def track_downloaded_file(self, payload: Any, file_path: str) -> str:
        async with self._lock:
            request = DownloadRequest.from_payload(payload)
            file_hash = self._calculate_file_hash(file_path)
            file_size_mb = request.file_size / (1024 * 1024)

            download_date = request.extra_fields.get("download_date", datetime.now())
            if isinstance(download_date, datetime):
                download_date_str = download_date.isoformat()
            else:
                download_date_str = str(download_date)

            publish_date = request.publish_date
            publish_date_str = (
                publish_date.isoformat()
                if isinstance(publish_date, datetime)
                else publish_date
            )

            self.store.state.downloaded_files[file_hash] = {
                "message_id": request.message_id,
                "channel_id": request.channel_id,
                "filename": Path(file_path).name,
                "file_path": str(file_path),
                "file_size": request.file_size,
                "file_size_mb": round(file_size_mb, 1),
                "mime_type": request.mime_type,
                "download_date": download_date_str,
                "publish_date": publish_date_str,
            }
            self.store.save_state()
            self.logger.info(f"File tracked: {request.filename} -> {file_hash}")
            return file_hash

    def _calculate_file_hash(self, file_path: str) -> str:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def get_downloaded_file_by_message(
        self, message_id: int
    ) -> Optional[Dict[str, Any]]:
        for file_hash, file_info in self.downloaded_files.items():
            if file_info["message_id"] == message_id:
                return {**file_info, "file_hash": file_hash}
        return None

    def should_skip_file(self, payload: Any) -> tuple[bool, str]:
        request = DownloadRequest.from_payload(payload)
        message_id = request.message_id

        if self.is_file_blacklisted(message_id):
            return True, "File is blacklisted"

        existing_file = self.get_downloaded_file_by_message(message_id)
        if existing_file:
            file_path = Path(existing_file["file_path"])
            if file_path.exists():
                return True, f"File already downloaded: {existing_file['file_path']}"

            self.logger.warning(
                f"File tracked but missing on disk: {existing_file['file_path']}"
            )

        return False, ""

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.store.state.schema_version,
            "channel_id": self.channel_id,
            "total_downloaded_files": len(self.downloaded_files),
            "total_blacklisted_files": len(self.blacklisted_files),
            "tracker_file_path": str(self.tracker_file),
            "tracker_file_exists": self.tracker_file.exists(),
            "tracker_file_size": self.tracker_file.stat().st_size
            if self.tracker_file.exists()
            else 0,
        }

    def cleanup_missing_files(self) -> int:
        removed_hashes = []
        for file_hash, file_info in self.downloaded_files.items():
            file_path = Path(file_info["file_path"])
            if not file_path.exists():
                removed_hashes.append(file_hash)
                self.logger.info(
                    f"Removing missing file from tracker: {file_info['filename']}"
                )

        for file_hash in removed_hashes:
            del self.store.state.downloaded_files[file_hash]

        if removed_hashes:
            self.store.save_state()

        return len(removed_hashes)


def create_message_tracker(tracker_file: str, channel_id: str) -> MessageTracker:
    return MessageTracker(tracker_file, channel_id)


def create_file_tracker(tracker_file: str, channel_id: str) -> FileTracker:
    return FileTracker(tracker_file, channel_id)


class TrackerManager:
    def __init__(self, base_download_dir: str):
        self.base_download_dir = Path(base_download_dir)
        self.message_trackers: Dict[str, MessageTracker] = {}
        self.file_trackers: Dict[str, FileTracker] = {}
        self.logger = get_logger()

    def get_or_create_trackers(
        self, channel_title: str, channel_id: Union[str, int]
    ) -> tuple[MessageTracker, FileTracker]:
        channel_id_str = str(channel_id)
        if (
            channel_id_str in self.message_trackers
            and channel_id_str in self.file_trackers
        ):
            return self.message_trackers[channel_id_str], self.file_trackers[
                channel_id_str
            ]

        scan_state_path = get_channel_state_path(
            self.base_download_dir, channel_title, channel_id, "scan_state.json"
        )
        download_state_path = get_channel_state_path(
            self.base_download_dir, channel_title, channel_id, "download_state.json"
        )

        message_tracker = create_message_tracker(str(scan_state_path), channel_id_str)
        file_tracker = create_file_tracker(str(download_state_path), channel_id_str)

        self.message_trackers[channel_id_str] = message_tracker
        self.file_trackers[channel_id_str] = file_tracker

        self.logger.info(
            f"Created trackers for channel {channel_title} ({channel_id_str})"
        )
        return message_tracker, file_tracker

    def get_channel_download_dir(
        self, channel_title: str, channel_id: Union[str, int]
    ) -> Path:
        return get_channel_downloads_dir(
            self.base_download_dir, channel_title, channel_id
        )

    def discover_channel_state_entries(self) -> list[Dict[str, Any]]:
        entries = []
        if not self.base_download_dir.exists():
            return entries

        for channel_dir in sorted(
            path for path in self.base_download_dir.iterdir() if path.is_dir()
        ):
            scan_state_path = channel_dir / "scan_state.json"
            download_state_path = channel_dir / "download_state.json"
            if not scan_state_path.exists() and not download_state_path.exists():
                continue

            channel_id = (
                self._read_channel_id(scan_state_path)
                or self._read_channel_id(download_state_path)
                or channel_dir.name
            )
            entries.append(
                {
                    "channel_id": str(channel_id),
                    "channel_directory": channel_dir,
                    "scan_state_path": scan_state_path
                    if scan_state_path.exists()
                    else None,
                    "download_state_path": download_state_path
                    if download_state_path.exists()
                    else None,
                }
            )

        return entries

    def load_existing_trackers(self) -> list[Dict[str, Any]]:
        discovered = []
        for entry in self.discover_channel_state_entries():
            channel_id = entry["channel_id"]

            message_tracker = None
            if entry["scan_state_path"] is not None:
                message_tracker = create_message_tracker(
                    str(entry["scan_state_path"]), channel_id
                )
                self.message_trackers[channel_id] = message_tracker

            file_tracker = None
            if entry["download_state_path"] is not None:
                file_tracker = create_file_tracker(
                    str(entry["download_state_path"]), channel_id
                )
                self.file_trackers[channel_id] = file_tracker

            discovered.append(
                {
                    **entry,
                    "message_tracker": message_tracker,
                    "file_tracker": file_tracker,
                }
            )

        return discovered

    def _read_channel_id(self, state_path: Optional[Path]) -> Optional[str]:
        if state_path is None or not state_path.exists():
            return None

        try:
            with open(state_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload.get("channel_id")
        except Exception as exc:
            self.logger.warning(f"Failed to read state file {state_path}: {exc}")
            return None
