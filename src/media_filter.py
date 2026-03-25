from datetime import datetime
from pathlib import Path
from typing import Dict

from domain_models import ParsedMessage
from logger import get_logger


class MediaFilter:
    def __init__(self, config_loader):
        self.config = config_loader
        self.logger = get_logger()

        # Cache filter settings
        self.allowed_formats = [
            fmt.lower() for fmt in self.config.get_allowed_formats()
        ]
        self.file_types = self.config.get_file_types()
        self.size_filter = self.config.get_size_filter()
        self.date_filter = self.config.get_date_filter()

    def should_process_media(self, media_info) -> bool:
        """Check if media file passes all filters"""
        try:
            parsed_message = ParsedMessage.from_payload(media_info)

            # Check for required fields in media_info
            if not parsed_message.is_downloadable:
                self.logger.debug(
                    f"Missing required media fields in message {parsed_message.message_id}"
                )
                return False

            # Check file type (audio/document)
            if not self._check_file_type(parsed_message):
                self.logger.info(f"→ Filtered out (type): {parsed_message.filename}")
                return False

            # Check file format extension
            if not self._check_file_format(parsed_message):
                self.logger.info(f"→ Filtered out (format): {parsed_message.filename}")
                return False

            # Check file size
            if not self._check_file_size(parsed_message):
                self.logger.info(f"→ Filtered out (size): {parsed_message.filename}")
                return False

            # Check message date
            if not self._check_message_date(parsed_message):
                self.logger.info(f"→ Filtered out (date): {parsed_message.filename}")
                return False

            self.logger.debug(f"All filters passed: {parsed_message.filename}")
            return True

        except Exception as e:
            if isinstance(media_info, dict):
                filename = media_info.get("filename", "unknown")
            else:
                filename = getattr(media_info, "filename", "unknown")
            self.logger.error(f"Filter error for {filename}: {e}")
            return False

    def _check_file_type(self, media_info: ParsedMessage) -> bool:
        """Check if file type (audio/document) is allowed"""
        if not self.file_types:
            return True

        media_type = media_info.media_type
        return media_type in self.file_types

    def _check_file_format(self, media_info: ParsedMessage) -> bool:
        """Check if file format extension is allowed"""
        if not self.allowed_formats:
            return True

        filename = media_info.filename or ""
        if not filename:
            return False

        # Extract extension from filename
        file_ext = Path(filename).suffix.lower()

        # Check if extension is in allowed formats
        return file_ext in self.allowed_formats

    def _check_file_size(self, media_info: ParsedMessage) -> bool:
        """Check if file size is within allowed range"""
        file_size_bytes = media_info.file_size
        if file_size_bytes <= 0:
            return False

        # Convert bytes to MB
        file_size_mb = file_size_bytes / (1024 * 1024)

        # Check minimum size
        min_mb = self.size_filter.get("min_mb")
        if min_mb is not None and file_size_mb < min_mb:
            return False

        # Check maximum size
        max_mb = self.size_filter.get("max_mb")
        if max_mb is not None and file_size_mb > max_mb:
            return False

        return True

    def _check_message_date(self, media_info: ParsedMessage) -> bool:
        """Check if message date is within allowed range"""
        message_date = media_info.publish_date
        if not message_date:
            return True

        # Ensure message_date is datetime object
        if isinstance(message_date, str):
            try:
                message_date = datetime.fromisoformat(
                    message_date.replace("Z", "+00:00")
                )
            except ValueError:
                self.logger.warning(f"Invalid date format: {message_date}")
                return True

        # Check from date
        date_from = self.date_filter.get("from")
        if date_from and message_date.date() < date_from.date():
            return False

        # Check to date
        date_to = self.date_filter.get("to")
        if date_to and message_date.date() > date_to.date():
            return False

        return True

    def get_filter_summary(self) -> Dict:
        """Get summary of current filter settings"""
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
    """Create media filter instance from config"""
    return MediaFilter(config_loader)
