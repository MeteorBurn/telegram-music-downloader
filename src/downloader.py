from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any

import normalizer

from download_models import DownloadOutcome, DownloadRequest
from logger import get_logger
from telegram_locator import create_telegram_locator


class TelegramDownloader:
    def __init__(self, client, config_loader, file_tracker=None):
        self.client = client
        self.config = config_loader
        self.file_tracker = file_tracker  # Default file tracker (can be None)
        self.logger = get_logger()
        self.telegram_locator = create_telegram_locator()

        # Get configuration settings
        self.download_dir = Path(self.config.get_download_dir())
        self.naming_template = self.config.get_naming_template()
        self.date_format = self.config.get_date_format()

        # Ensure download directory exists
        self.download_dir.mkdir(parents=True, exist_ok=True)

    async def download_media_file(
        self, media_info: Any, file_info: str = ""
    ) -> Dict[str, Any]:
        """Download media file from Telegram and return result with status and details"""
        request = DownloadRequest.from_payload(media_info)

        # Get file tracker from request or use default
        file_tracker = request.file_tracker or self.file_tracker

        # Check if file should be skipped based on tracker
        if file_tracker:
            should_skip, skip_reason = file_tracker.should_skip_file(request)
            if should_skip:
                self.logger.info(
                    f"→ Skipping file: {request.filename} {file_info} - {skip_reason}"
                )
                return DownloadOutcome(
                    status="skipped",
                    reason=skip_reason,
                    file_path=None,
                    logged=True,
                ).to_dict()

        try:
            # Generate filename
            filename = self._generate_filename(request)

            # Use channel-specific download directory if provided in media_info
            download_dir = Path(request.download_dir or self.download_dir)
            download_dir.mkdir(parents=True, exist_ok=True)

            file_path = download_dir / filename

            # Check if a file with the same name already exists (regardless of the message)
            if file_path.exists():
                # Physical file existence check
                skip_reason = f"File with same name already exists: {file_path}"
                self.logger.info(
                    f"→ Skipping file: {request.filename} {file_info} - {skip_reason}"
                )

                # If file tracker exists, check if this file is tracked
                if file_tracker:
                    existing_file = file_tracker.get_downloaded_file_by_message(
                        request.message_id
                    )
                    if not existing_file:
                        # File exists on disk but not tracked - add to tracker
                        self.logger.info(
                            f"→ Adding existing file to tracker: {file_path.name}"
                        )

                        # Get file modification time as download date
                        file_mtime = file_path.stat().st_mtime
                        file_download_date = datetime.fromtimestamp(file_mtime)

                        # Create a copy of media_info with download date from file attributes
                        existing_request = DownloadRequest.from_payload(request)
                        existing_request.extra_fields["download_date"] = (
                            file_download_date
                        )

                        # Track the existing file
                        file_hash = await file_tracker.track_downloaded_file(
                            existing_request, str(file_path)
                        )
                        self.logger.info(
                            f"✓ File added to tracker: {file_path.name} (hash: {file_hash[:8]}...)"
                        )

                # Return info that file was skipped due to existing name
                return DownloadOutcome(
                    status="skipped",
                    reason=skip_reason,
                    file_path=str(file_path),
                    logged=True,
                ).to_dict()

            # Download file from Telegram
            # Logging for download initiation is now handled in main.py

            # Create message object for download
            message = await self._get_message_by_id(request)
            if not message:
                self.logger.error(f"✗ Could not retrieve message {request.message_id}")
                return DownloadOutcome(
                    status="failed",
                    reason=f"Could not retrieve message {request.message_id}",
                    file_path=None,
                    logged=True,
                ).to_dict()

            # Download without progress callback
            downloaded_file = await self.client.download_media(
                message.media.document, file=str(file_path)
            )

            if downloaded_file:
                # Update media_info with download date
                request.extra_fields["download_date"] = datetime.now()
                file_hash = None

                # Normalize track name if enabled in config
                if self.config.get_normalize_track_names():
                    original_name = Path(file_path.name).stem
                    original_suffix = Path(file_path.name).suffix
                    normalized_name = normalizer.normalize_track_name(original_name)
                    if normalized_name != original_name:
                        normalized_file_name = normalized_name + original_suffix
                        normalized_path = file_path.with_name(normalized_file_name)
                        file_path.rename(normalized_path)
                        self.logger.info(
                            f"Track name normalized: '{original_name}' -> '{normalized_name}'"
                        )
                        file_path = normalized_path

                # Track downloaded file in file_tracker
                if file_tracker:
                    file_hash = await file_tracker.track_downloaded_file(
                        request, str(file_path)
                    )
                    self.logger.info(
                        f"✓ Downloaded successfully: {file_path.name} {file_info} (hash: {file_hash[:8]}...)"
                    )
                else:
                    self.logger.info(
                        f"✓ Downloaded successfully: {file_path.name} {file_info}"
                    )

                return DownloadOutcome(
                    status="success",
                    file_path=str(file_path),
                    file_hash=file_hash,
                    already_existed=False,
                    logged=True,
                ).to_dict()
            else:
                self.logger.error(f"✗ Download failed: {filename} {file_info}")
                return DownloadOutcome(
                    status="failed",
                    reason="Download returned None",
                    file_path=None,
                    logged=True,
                ).to_dict()

        except Exception as e:
            self.logger.error(
                f"✗ Download error for {request.filename} {file_info}: {e}"
            )
            # Add to blacklist on persistent errors
            if file_tracker and (
                "flood" in str(e).lower() or "timeout" in str(e).lower()
            ):
                file_tracker.add_blacklisted_file(
                    request.message_id, f"Download error: {str(e)[:100]}"
                )
            return DownloadOutcome(
                status="failed",
                reason=str(e),
                file_path=None,
                logged=True,
            ).to_dict()

    async def _get_message_by_id(self, media_info: Any) -> Optional[Any]:
        """Get message object by ID for downloading"""
        try:
            return self.telegram_locator.create_message_for_request(media_info)

        except Exception as e:
            self.logger.error(f"Error creating message object: {e}")
            return None

    def _generate_filename(self, media_info: Any) -> str:
        """Generate filename based on template"""
        try:
            request = DownloadRequest.from_payload(media_info)
            # Get original filename without extension
            original_name = Path(request.filename).stem
            file_extension = Path(request.filename).suffix

            # Get dates
            publish_date = request.publish_date
            download_date = request.extra_fields.get("download_date", datetime.now())

            # Format publish date
            publish_date_str = ""
            if publish_date:
                if isinstance(publish_date, str):
                    publish_date = datetime.fromisoformat(
                        publish_date.replace("Z", "+00:00")
                    )
                publish_date_str = publish_date.strftime(self.date_format)

            # Format download date
            download_date_str = ""
            if download_date:
                if isinstance(download_date, str):
                    download_date = datetime.fromisoformat(
                        download_date.replace("Z", "+00:00")
                    )
                download_date_str = download_date.strftime(self.date_format)

            # Prepare template variables
            template_vars = {
                "original_name": self._sanitize_filename(original_name),
                "message_id": request.message_id,
                "publish_date": publish_date_str,
                "download_date": download_date_str,
                "file_size": request.file_size,
                "mime_type": request.mime_type.replace("/", "_")
                if request.mime_type
                else "",
            }

            # Add audio metadata if available
            audio_meta = request.audio_meta
            if audio_meta:
                template_vars.update(
                    {
                        "artist": self._sanitize_filename(
                            audio_meta.get("performer", "")
                        ),
                        "title": self._sanitize_filename(audio_meta.get("title", "")),
                        "duration": audio_meta.get("duration", 0),
                    }
                )

            # Generate filename from template
            filename = self.naming_template.format(**template_vars)

            # Add original extension
            filename = filename + file_extension

            # Ensure filename is valid
            filename = self._sanitize_filename(filename)

            # Ensure filename is not too long (max 255 chars for most filesystems)
            if len(filename) > 255:
                # Truncate while keeping extension
                max_name_length = 255 - len(file_extension)
                filename = filename[:max_name_length] + file_extension

            return filename

        except Exception as e:
            self.logger.error(f"Error generating filename: {e}")
            # Fallback to simple name
            request = DownloadRequest.from_payload(media_info)
            return f"file_{request.message_id}{Path(request.filename).suffix}"

    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        if not filename:
            return ""

        # Define invalid characters for Windows/Unix
        invalid_chars = '<>:"/\\|?*'

        # Replace invalid characters with underscore
        for char in invalid_chars:
            filename = filename.replace(char, "_")

        # Remove control characters
        filename = "".join(char for char in filename if ord(char) >= 32)

        # Strip spaces and dots from ends
        filename = filename.strip(" .")

        # Ensure filename is not empty
        if not filename:
            filename = "unnamed"

        return filename

    def get_download_statistics(self) -> Dict[str, Any]:
        """Get download statistics"""
        stats = {
            "download_directory": str(self.download_dir),
            "naming_template": self.naming_template,
        }

        if self.file_tracker:
            file_stats = self.file_tracker.get_statistics()
            stats.update(
                {
                    "total_downloaded_files": file_stats["total_downloaded_files"],
                    "total_blacklisted_files": file_stats["total_blacklisted_files"],
                }
            )

        return stats


def create_downloader(client, config_loader, file_tracker=None) -> TelegramDownloader:
    """Create downloader instance"""
    return TelegramDownloader(client, config_loader, file_tracker)
