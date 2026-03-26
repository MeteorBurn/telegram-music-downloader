from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from logger import get_logger
from models import DownloadOutcome, DownloadRequest
from renamer import normalize_track_name
from telegram import create_telegram_locator


class TelegramDownloader:
    def __init__(self, client, config_loader, file_tracker=None):
        self.client = client
        self.config = config_loader
        self.file_tracker = file_tracker
        self.logger = get_logger()
        self.telegram_locator = create_telegram_locator()
        self.download_dir = Path(self.config.get_download_dir())
        self.naming_template = self.config.get_naming_template()
        self.date_format = self.config.get_date_format()
        self.download_dir.mkdir(parents=True, exist_ok=True)

    async def download_media_file(
        self, media_info: Any, file_info: str = ""
    ) -> Dict[str, Any]:
        request = DownloadRequest.from_payload(media_info)
        file_tracker = request.file_tracker or self.file_tracker

        if file_tracker:
            should_skip, skip_reason = file_tracker.should_skip_file(request)
            if should_skip:
                self.logger.info(
                    f"[SKIP] {request.filename} {file_info} - {skip_reason}"
                )
                return DownloadOutcome(
                    status="skipped",
                    reason=skip_reason,
                    file_path=None,
                    logged=True,
                ).to_dict()

        try:
            filename = self._generate_filename(request)
            download_dir = Path(request.download_dir or self.download_dir)
            download_dir.mkdir(parents=True, exist_ok=True)
            file_path = download_dir / filename
            predicted_final_path = self._predict_final_path(file_path)

            if predicted_final_path != file_path and predicted_final_path.exists():
                return await self._build_existing_file_skip_result(
                    request,
                    file_info,
                    file_tracker,
                    predicted_final_path,
                    "Normalized file already exists",
                )

            if file_path.exists():
                return await self._build_existing_file_skip_result(
                    request,
                    file_info,
                    file_tracker,
                    file_path,
                    "File with same name already exists",
                )

            message = await self._get_message_by_id(request)
            if not message:
                self.logger.error(
                    f"[FAIL] Could not retrieve message {request.message_id}"
                )
                return DownloadOutcome(
                    status="failed",
                    reason=f"Could not retrieve message {request.message_id}",
                    file_path=None,
                    logged=True,
                ).to_dict()

            downloaded_file = await self.client.download_media(
                message.media.document, file=str(file_path)
            )

            if downloaded_file:
                request.extra_fields["download_date"] = datetime.now()
                file_hash = None

                if self.config.get_normalize_track_names():
                    normalization_result = self._apply_normalized_filename(
                        file_path, request, file_info
                    )
                    if normalization_result["status"] == "skipped":
                        return DownloadOutcome(
                            status="skipped",
                            reason=normalization_result["reason"],
                            file_path=normalization_result["file_path"],
                            logged=True,
                        ).to_dict()
                    file_path = normalization_result["file_path"]

                if file_tracker:
                    file_hash = await file_tracker.track_downloaded_file(
                        request, str(file_path)
                    )
                    self.logger.info(
                        f"[OK] Downloaded: {file_path.name} {file_info} (hash: {file_hash[:8]}...)"
                    )
                else:
                    self.logger.info(f"[OK] Downloaded: {file_path.name} {file_info}")

                return DownloadOutcome(
                    status="success",
                    file_path=str(file_path),
                    file_hash=file_hash,
                    already_existed=False,
                    logged=True,
                ).to_dict()

            self.logger.error(f"[FAIL] Download returned None: {filename} {file_info}")
            return DownloadOutcome(
                status="failed",
                reason="Download returned None",
                file_path=None,
                logged=True,
            ).to_dict()
        except Exception as exc:
            self.logger.error(
                f"[FAIL] Download error: {request.filename} {file_info} - {exc}"
            )
            if file_tracker and (
                "flood" in str(exc).lower() or "timeout" in str(exc).lower()
            ):
                file_tracker.add_blacklisted_file(
                    request.message_id, f"Download error: {str(exc)[:100]}"
                )
            return DownloadOutcome(
                status="failed",
                reason=str(exc),
                file_path=None,
                logged=True,
            ).to_dict()

    def _apply_normalized_filename(
        self, file_path: Path, request: DownloadRequest, file_info: str
    ) -> Dict[str, Any]:
        original_name = file_path.stem
        original_suffix = file_path.suffix
        normalized_name = normalize_track_name(original_name)

        if normalized_name == original_name:
            return {"status": "success", "file_path": file_path}

        normalized_file_name = normalized_name + original_suffix
        normalized_path = file_path.with_name(normalized_file_name)

        if normalized_path.exists():
            if file_path.exists():
                file_path.unlink()
            skip_reason = f"Normalized file already exists: {normalized_path}"
            self.logger.info(f"[SKIP] {request.filename} {file_info} - {skip_reason}")
            return {
                "status": "skipped",
                "reason": skip_reason,
                "file_path": str(normalized_path),
            }

        try:
            file_path.rename(normalized_path)
        except FileExistsError:
            if file_path.exists():
                file_path.unlink()
            skip_reason = f"Normalized file already exists: {normalized_path}"
            self.logger.info(f"[SKIP] {request.filename} {file_info} - {skip_reason}")
            return {
                "status": "skipped",
                "reason": skip_reason,
                "file_path": str(normalized_path),
            }
        except OSError as exc:
            if getattr(exc, "winerror", None) == 183:
                if file_path.exists():
                    file_path.unlink()
                skip_reason = f"Normalized file already exists: {normalized_path}"
                self.logger.info(
                    f"[SKIP] {request.filename} {file_info} - {skip_reason}"
                )
                return {
                    "status": "skipped",
                    "reason": skip_reason,
                    "file_path": str(normalized_path),
                }
            raise

        self.logger.info(f"[NORM] '{original_name}' -> '{normalized_name}'")
        return {"status": "success", "file_path": normalized_path}

    def _predict_final_path(self, file_path: Path) -> Path:
        if not self.config.get_normalize_track_names():
            return file_path

        normalized_name = normalize_track_name(file_path.stem)
        if normalized_name == file_path.stem:
            return file_path
        return file_path.with_name(normalized_name + file_path.suffix)

    async def _build_existing_file_skip_result(
        self,
        request: DownloadRequest,
        file_info: str,
        file_tracker,
        existing_path: Path,
        reason_prefix: str,
    ) -> Dict[str, Any]:
        skip_reason = f"{reason_prefix}: {existing_path}"
        self.logger.info(f"[SKIP] {request.filename} {file_info} - {skip_reason}")

        if file_tracker:
            existing_file = file_tracker.get_downloaded_file_by_message(
                request.message_id
            )
            if not existing_file:
                self.logger.info(
                    f"[TRACK] Adding existing file to tracker: {existing_path.name}"
                )
                file_mtime = existing_path.stat().st_mtime
                file_download_date = datetime.fromtimestamp(file_mtime)
                existing_request = DownloadRequest.from_payload(request)
                existing_request.extra_fields["download_date"] = file_download_date
                file_hash = await file_tracker.track_downloaded_file(
                    existing_request, str(existing_path)
                )
                self.logger.info(
                    f"[TRACK] Registered existing file: {existing_path.name} (hash: {file_hash[:8]}...)"
                )

        return DownloadOutcome(
            status="skipped",
            reason=skip_reason,
            file_path=str(existing_path),
            logged=True,
        ).to_dict()

    async def _get_message_by_id(self, media_info: Any) -> Optional[Any]:
        try:
            return self.telegram_locator.create_message_for_request(media_info)
        except Exception as exc:
            self.logger.error(f"[FAIL] Error creating message object: {exc}")
            return None

    def _generate_filename(self, media_info: Any) -> str:
        try:
            request = DownloadRequest.from_payload(media_info)
            original_name = Path(request.filename).stem
            file_extension = Path(request.filename).suffix
            publish_date = request.publish_date
            download_date = request.extra_fields.get("download_date", datetime.now())

            publish_date_str = ""
            if publish_date:
                if isinstance(publish_date, str):
                    publish_date = datetime.fromisoformat(
                        publish_date.replace("Z", "+00:00")
                    )
                publish_date_str = publish_date.strftime(self.date_format)

            download_date_str = ""
            if download_date:
                if isinstance(download_date, str):
                    download_date = datetime.fromisoformat(
                        download_date.replace("Z", "+00:00")
                    )
                download_date_str = download_date.strftime(self.date_format)

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

            filename = self.naming_template.format(**template_vars)
            filename = filename + file_extension
            filename = self._sanitize_filename(filename)

            if len(filename) > 255:
                max_name_length = 255 - len(file_extension)
                filename = filename[:max_name_length] + file_extension
            return filename
        except Exception as exc:
            self.logger.error(f"Error generating filename: {exc}")
            request = DownloadRequest.from_payload(media_info)
            return f"file_{request.message_id}{Path(request.filename).suffix}"

    def _sanitize_filename(self, filename: str) -> str:
        if not filename:
            return ""

        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, "_")
        filename = "".join(char for char in filename if ord(char) >= 32)
        filename = filename.strip(" .")
        if not filename:
            filename = "unnamed"
        return filename

    def get_download_statistics(self) -> Dict[str, Any]:
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
    return TelegramDownloader(client, config_loader, file_tracker)
