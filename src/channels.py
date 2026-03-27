import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

from logger import format_critical_message, get_logger
from models import (
    ChannelContext,
    ChannelProcessingResult,
    DownloadRequest,
    ParsedMessage,
    QueuedMessageContext,
)


def sanitize_channel_name(channel_title: str, max_length: int = 50) -> str:
    if not channel_title or not isinstance(channel_title, str):
        return "Unknown"

    name = unicodedata.normalize("NFKD", channel_title)
    cyrillic_map = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "А": "A",
        "Б": "B",
        "В": "V",
        "Г": "G",
        "Д": "D",
        "Е": "E",
        "Ё": "Yo",
        "Ж": "Zh",
        "З": "Z",
        "И": "I",
        "Й": "Y",
        "К": "K",
        "Л": "L",
        "М": "M",
        "Н": "N",
        "О": "O",
        "П": "P",
        "Р": "R",
        "С": "S",
        "Т": "T",
        "У": "U",
        "Ф": "F",
        "Х": "H",
        "Ц": "Ts",
        "Ч": "Ch",
        "Ш": "Sh",
        "Щ": "Sch",
        "Ъ": "",
        "Ы": "Y",
        "Ь": "",
        "Э": "E",
        "Ю": "Yu",
        "Я": "Ya",
    }

    transliterated = []
    for char in name:
        if char in cyrillic_map:
            transliterated.append(cyrillic_map[char])
        else:
            transliterated.append(char)
    name = "".join(transliterated)
    name = re.sub(r"[^\w\s\-]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")

    if len(name) > max_length:
        name = name[:max_length].rstrip("_")
    if not name:
        return "Unknown"
    return name


def create_channel_folder_name(
    channel_title: str, channel_id: Union[str, int], max_title_length: int = 50
) -> str:
    sanitized_title = sanitize_channel_name(channel_title, max_title_length)
    return f"{sanitized_title}_{str(channel_id)}"


def get_channel_directory(
    base_dir: Union[str, Path], channel_title: str, channel_id: Union[str, int]
) -> Path:
    return Path(base_dir) / create_channel_folder_name(channel_title, channel_id)


def get_channel_downloads_dir(
    base_dir: Union[str, Path], channel_title: str, channel_id: Union[str, int]
) -> Path:
    return get_channel_directory(base_dir, channel_title, channel_id) / "downloads"


def get_channel_state_path(
    base_dir: Union[str, Path],
    channel_title: str,
    channel_id: Union[str, int],
    filename: str,
) -> Path:
    return get_channel_directory(base_dir, channel_title, channel_id) / filename


def get_channel_tracker_path(
    base_dir: Union[str, Path],
    channel_title: str,
    channel_id: Union[str, int],
    tracker_type: str,
) -> Path:
    tracker_filenames = {
        "message": "scan_state.json",
        "file": "download_state.json",
    }
    return get_channel_state_path(
        base_dir,
        channel_title,
        channel_id,
        tracker_filenames.get(tracker_type, tracker_type),
    )


class MediaFilter:
    def __init__(self, config_loader):
        self.config = config_loader
        self.logger = get_logger()
        self.allowed_formats = [
            fmt.lower() for fmt in self.config.get_allowed_formats()
        ]
        self.file_types = self.config.get_file_types()
        self.size_filter = self.config.get_size_filter()
        self.date_filter = self.config.get_date_filter()

    def should_process_media(self, media_info) -> bool:
        try:
            parsed_message = ParsedMessage.from_payload(media_info)
            filename = parsed_message.filename or "unknown"

            if not parsed_message.is_downloadable:
                self.logger.debug(
                    f"Missing required media fields in message {parsed_message.message_id}"
                )
                return False

            if not self._check_file_type(parsed_message):
                self.logger.info(f"[FILTER] type: {parsed_message.filename}")
                return False

            format_details = self._get_format_filter_details(parsed_message)
            if format_details is not None:
                self.logger.info(f"[FILTER] format: {format_details} {filename}")
                return False

            size_details = self._get_size_filter_details(parsed_message)
            if size_details is not None:
                self.logger.info(f"[FILTER] size: {size_details} {filename}")
                return False

            date_details = self._get_date_filter_details(parsed_message)
            if date_details is not None:
                self.logger.info(f"[FILTER] date: {date_details} {filename}")
                return False

            self.logger.debug(f"All filters passed: {parsed_message.filename}")
            return True
        except Exception as exc:
            if isinstance(media_info, dict):
                filename = media_info.get("filename", "unknown")
            else:
                filename = getattr(media_info, "filename", "unknown")
            self.logger.error(f"[FAIL] Filter error for {filename}: {exc}")
            return False

    def _check_file_type(self, media_info: ParsedMessage) -> bool:
        if not self.file_types:
            return True
        return media_info.media_type in self.file_types

    def _get_format_filter_details(self, media_info: ParsedMessage) -> Optional[str]:
        if not self.allowed_formats:
            return None

        filename = media_info.filename or ""
        if not filename:
            return "[no-name]"

        file_extension = Path(filename).suffix.lower()
        if file_extension in self.allowed_formats:
            return None

        return f"[{file_extension or 'no-extension'}]"

    def _get_size_filter_details(self, media_info: ParsedMessage) -> Optional[str]:
        file_size_bytes = media_info.file_size
        file_size_mb = file_size_bytes / (1024 * 1024)

        if file_size_bytes <= 0:
            return f"[{file_size_mb:.1f} MB <= 0 MB]"

        min_mb = self.size_filter.get("min_mb")
        if min_mb is not None and file_size_mb < min_mb:
            return f"[{self._format_limit_mb(min_mb)} MB > {file_size_mb:.1f} MB]"

        max_mb = self.size_filter.get("max_mb")
        if max_mb is not None and file_size_mb > max_mb:
            return f"[{self._format_limit_mb(max_mb)} MB < {file_size_mb:.1f} MB]"

        return None

    def _get_date_filter_details(self, media_info: ParsedMessage) -> Optional[str]:
        message_date = media_info.publish_date
        if not message_date:
            return None

        if isinstance(message_date, str):
            try:
                message_date = datetime.fromisoformat(
                    message_date.replace("Z", "+00:00")
                )
            except ValueError:
                self.logger.warning(f"[WARN] Invalid date format: {message_date}")
                return None

        message_date_str = message_date.date().isoformat()

        date_from = self.date_filter.get("from")
        if date_from and message_date.date() < date_from.date():
            date_from_str = date_from.date().isoformat()
            return f"[{date_from_str} > {message_date_str}]"

        date_to = self.date_filter.get("to")
        if date_to and message_date.date() > date_to.date():
            date_to_str = date_to.date().isoformat()
            return f"[{date_to_str} < {message_date_str}]"

        return None

    def _format_limit_mb(self, value: float) -> str:
        return f"{value:g}"

    def get_filter_summary(self) -> Dict:
        return {
            "file_types": self.file_types,
            "allowed_formats": self.allowed_formats,
            "size_range_mb": {
                "min": self.size_filter.get("min_mb"),
                "max": self.size_filter.get("max_mb"),
            },
            "date_range": {
                "from": self.date_filter.get("from"),
                "to": self.date_filter.get("to"),
            },
        }


def create_media_filter(config_loader) -> MediaFilter:
    return MediaFilter(config_loader)


class ChannelProcessor:
    def __init__(
        self,
        parser,
        media_filter,
        tracker_manager,
        download_coordinator,
        logger: logging.Logger,
    ):
        self.parser = parser
        self.media_filter = media_filter
        self.tracker_manager = tracker_manager
        self.download_coordinator = download_coordinator
        self.logger = logger

    async def process_channel(
        self, channel_name: str, entity, max_files: int = 0
    ) -> Dict[str, Any]:
        context = self._get_channel_context(channel_name, entity)
        result = self._initialize_channel_state(context)

        self.logger.info(f"[CHANNEL] Processing: {channel_name} ({entity.title})")

        try:
            if context.last_processed_id:
                self.logger.info(
                    f"[CHANNEL] Resume from message ID: {context.last_processed_id}"
                )

            stats = await self.parser.get_channel_stats(entity)
            if stats:
                self.logger.info(
                    f"[CHANNEL] Stats: {stats['media_messages']} media files in last 100 messages"
                )

            files_queued_in_channel = 0

            async for parsed_message in self.parser.parse_messages(
                entity,
                last_processed_id=context.last_processed_id,
                config_channel_id=context.channel_id,
            ):
                parsed_message = ParsedMessage.from_payload(parsed_message)
                result.messages_processed += 1

                message_id = parsed_message.message_id
                context.message_tracker.register_message(message_id)
                result.last_processed_id = message_id

                if not parsed_message.has_media:
                    self._handle_message_without_media(context, message_id)
                    continue

                if not parsed_message.is_downloadable:
                    self._handle_invalid_media_message(context, message_id)
                    continue

                if not parsed_message.has_download_locator:
                    self._handle_invalid_media_message(context, message_id)
                    self.logger.debug(
                        f"Skipping message {message_id} - missing Telegram locator fields"
                    )
                    continue

                if not self.media_filter.should_process_media(parsed_message):
                    context.message_tracker.mark_message_outcome(message_id, "skipped")
                    continue

                result.files_found += 1
                queued_message = self._prepare_download_message(context, parsed_message)
                success = await self._queue_download(queued_message)

                if success:
                    result.files_queued += 1
                    files_queued_in_channel += 1
                    self.logger.info(
                        f"[QUEUE] {queued_message.filename} {queued_message.file_info_str}"
                    )
                else:
                    context.message_tracker.mark_message_outcome(message_id, "critical")
                    self.logger.warning(
                        f"[FAIL] Failed to queue: {queued_message.filename}"
                    )
                    critical_reason = (
                        f"[CRITICAL] Failed to queue {queued_message.filename}"
                    )
                    self.logger.critical(format_critical_message(critical_reason))
                    raise RuntimeError(critical_reason)

                if max_files > 0 and files_queued_in_channel >= max_files:
                    self.logger.info(
                        f"[CHANNEL] File limit reached ({max_files}) for {channel_name}"
                    )
                    break

            self.logger.info(
                f"[CHANNEL] Done: {channel_name} - {result.files_queued} queued, {result.messages_processed} messages scanned"
            )
            return result.to_dict()
        except Exception as exc:
            self.logger.error(f"[FAIL] Error processing channel {channel_name}: {exc}")
            raise

    def _get_channel_context(self, channel_name: str, entity) -> ChannelContext:
        channel_id = str(channel_name)
        channel_title = entity.title
        message_tracker, file_tracker = self.tracker_manager.get_or_create_trackers(
            channel_title, channel_id
        )
        channel_download_dir = self.tracker_manager.get_channel_download_dir(
            channel_title, channel_id
        )

        return ChannelContext(
            channel_name=channel_name,
            channel_id=channel_id,
            channel_title=channel_title,
            entity=entity,
            message_tracker=message_tracker,
            file_tracker=file_tracker,
            download_dir=channel_download_dir,
            last_processed_id=message_tracker.get_last_processed_id(),
        )

    def _initialize_channel_state(
        self, context: ChannelContext
    ) -> ChannelProcessingResult:
        return ChannelProcessingResult(
            channel_name=context.channel_name,
            channel_title=context.channel_title,
            channel_id=context.channel_id,
        )

    def _handle_message_without_media(
        self, context: ChannelContext, message_id: int
    ) -> None:
        self.logger.debug(f"Skipping message {message_id} - no media")
        context.message_tracker.mark_message_outcome(message_id, "skipped")

    def _handle_invalid_media_message(
        self, context: ChannelContext, message_id: int
    ) -> None:
        self.logger.debug(
            f"Skipping message {message_id} - missing required media fields"
        )
        context.message_tracker.mark_message_outcome(message_id, "skipped")

    def _prepare_download_message(
        self, context: ChannelContext, parsed_message: ParsedMessage
    ) -> QueuedMessageContext:
        message_id = parsed_message.message_id
        request = self._build_download_request(context, parsed_message, message_id)
        file_info_str = self._build_file_info_str(request)

        return QueuedMessageContext(
            message_id=message_id,
            filename=request.filename,
            request=request,
            file_info_str=file_info_str,
        )

    async def _queue_download(self, queued_message: QueuedMessageContext) -> bool:
        return await self.download_coordinator.add_download_task(
            queued_message.request, queued_message.file_info_str
        )

    def _build_download_request(
        self,
        context: ChannelContext,
        parsed_message: ParsedMessage,
        message_id: int,
    ) -> DownloadRequest:
        return DownloadRequest.from_parsed_message(
            parsed_message,
            file_tracker=context.file_tracker,
            download_dir=str(Path(context.download_dir)),
            outcome_callback=self._create_message_outcome_callback(context, message_id),
        )

    def _create_message_outcome_callback(
        self, context: ChannelContext, message_id: int
    ):
        def _record_outcome(outcome: str, _task, _result):
            context.message_tracker.mark_message_outcome(message_id, outcome)

        return _record_outcome

    def _build_file_info_str(self, request: DownloadRequest) -> str:
        duration_str = ""
        if request.audio_meta and request.audio_meta.get("duration"):
            duration = request.audio_meta["duration"]
            minutes, seconds = divmod(duration, 60)
            duration_str = f"[{minutes:02d}:{seconds:02d}]"

        file_size_mb = request.file_size / (1024 * 1024)
        size_str = f"[{file_size_mb:.1f} MB]"

        if duration_str and size_str:
            return f"{duration_str} {size_str}"

        return f"{duration_str}{size_str}"
