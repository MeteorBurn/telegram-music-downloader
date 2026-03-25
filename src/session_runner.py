from pathlib import Path
from typing import Any, Dict

from channel_processor import ChannelProcessor
from client import create_client
from config_loader import ConfigLoader
from download_coordinator import create_download_coordinator
from download_monitor import ProgressDisplay, create_download_monitor
from downloader import create_downloader
from logger import emit_session_lines, emit_session_message, setup_logging
from media_filter import create_media_filter
from message_parser import create_message_parser
from session_manager import create_session_manager
from tracker import TrackerManager


class SessionRunner:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = ConfigLoader(config_path)
        self.logger = setup_logging(self.config)
        for level, message in self.config.consume_startup_messages():
            emit_session_message(message, level=level, logger=self.logger)
        self.logger.info("=== Telegram Music Downloader Started ===")

        self.session_manager = create_session_manager(self.config)
        self.tracker_manager = TrackerManager(self.config.get_download_dir())
        self.media_filter = create_media_filter(self.config)

        self.client = None
        self.parser = None
        self.downloader = None
        self.download_coordinator = None
        self.download_monitor = None
        self.channel_processor = None

    async def initialize_client(self):
        self.logger.info("Initializing Telegram client...")
        self.client = await create_client(self.config)

        await self.client.connect()
        if not self.client.client.is_connected():
            raise RuntimeError("Failed to connect to Telegram")

        self.parser = create_message_parser(self.client.get_client(), self.config)
        self.downloader = create_downloader(
            self.client.get_client(), self.config, file_tracker=None
        )
        self.download_coordinator = create_download_coordinator(
            self.downloader, self.config
        )
        self.download_monitor = create_download_monitor(self.download_coordinator)
        self.channel_processor = ChannelProcessor(
            parser=self.parser,
            media_filter=self.media_filter,
            tracker_manager=self.tracker_manager,
            download_coordinator=self.download_coordinator,
            logger=self.logger,
        )

        self.logger.info("Client initialized successfully")

    async def run_download_session(self, max_files: int = 0) -> Dict[str, Any]:
        session_results = {
            "channels_processed": 0,
            "total_files_found": 0,
            "total_files_downloaded": 0,
            "total_files_skipped": 0,
            "total_files_failed": 0,
            "total_messages_processed": 0,
            "channels_details": [],
        }

        channels = self.config.get_channels()
        if not channels:
            self.logger.warning("No channels configured")
            return session_results

        entities = await self.parser.get_channels_entities()
        if not entities:
            self.logger.error("No accessible channels found")
            return session_results

        config_max_files = self.config.get_max_files_per_run()
        if config_max_files > 0:
            max_files = (
                min(max_files, config_max_files) if max_files > 0 else config_max_files
            )

        self.logger.info(
            f"Processing {len(entities)} channels with {self.config.get_concurrent_downloads()} concurrent downloads"
        )
        self.logger.info(f"Max files: {max_files if max_files > 0 else 'unlimited'}")

        await self.download_coordinator.start()

        try:
            files_queued_total = 0
            for channel_name, entity in entities:
                if max_files > 0 and files_queued_total >= max_files:
                    self.logger.info(
                        f"Reached overall maximum files limit ({max_files}), stopping channel processing"
                    )
                    break

                remaining_for_channel = (
                    max_files - files_queued_total if max_files > 0 else 0
                )
                channel_result = await self.channel_processor.process_channel(
                    channel_name, entity, remaining_for_channel
                )

                session_results["channels_details"].append(channel_result)
                session_results["channels_processed"] += 1
                session_results["total_files_found"] += channel_result["files_found"]
                session_results["total_messages_processed"] += channel_result[
                    "messages_processed"
                ]
                files_queued_total += channel_result["files_queued"]

            self.logger.info(
                "All channels processed, waiting for downloads to complete..."
            )
            await self.download_coordinator.wait_completion()

            final_summary = self.download_coordinator.get_session_summary()
            session_results.update(
                {
                    "total_files_downloaded": final_summary["files_completed"],
                    "total_files_failed": final_summary["files_failed"],
                    "total_files_skipped": final_summary["files_skipped"],
                }
            )
            return session_results
        finally:
            await self.download_coordinator.stop()

    async def show_statistics(self):
        lines = ["", "=== Download Statistics ==="]
        discovered_trackers = self.tracker_manager.load_existing_trackers()

        if discovered_trackers:
            lines.extend(["", "Per-Channel Statistics:"])
            total_downloaded = 0
            total_blacklisted = 0
            for tracker_entry in discovered_trackers:
                channel_id = tracker_entry["channel_id"]
                file_tracker = tracker_entry["file_tracker"]
                message_tracker = tracker_entry["message_tracker"]

                file_stats = (
                    file_tracker.get_statistics()
                    if file_tracker
                    else {"total_downloaded_files": 0, "total_blacklisted_files": 0}
                )
                last_safe_message_id = (
                    message_tracker.get_last_processed_id() if message_tracker else None
                )
                total_downloaded += file_stats["total_downloaded_files"]
                total_blacklisted += file_stats["total_blacklisted_files"]
                lines.append(
                    f"  Channel {channel_id}: {file_stats['total_downloaded_files']} files, {file_stats['total_blacklisted_files']} blacklisted, last safe message {last_safe_message_id}"
                )
            lines.append("")
            lines.append(f"Total downloaded files (all channels): {total_downloaded}")
            lines.append(f"Total blacklisted files (all channels): {total_blacklisted}")
        else:
            lines.append("No channel state found in output_dir yet")

        download_directory = self.config.get_download_dir()
        naming_template = self.config.get_naming_template()
        if self.downloader:
            download_stats = self.downloader.get_download_statistics()
            download_directory = download_stats["download_directory"]
            naming_template = download_stats["naming_template"]

        lines.append("")
        lines.append(f"Base download directory: {download_directory}")
        lines.append(f"Naming template: {naming_template}")

        lines.append("")
        lines.append(f"Concurrent downloads: {self.config.get_concurrent_downloads()}")
        lines.append(f"Max queue size: {self.config.get_max_queue_size()}")
        lines.append(f"Rate limit: {self.config.get_requests_per_second()} req/sec")

        filter_summary = self.media_filter.get_filter_summary()
        lines.append("")
        lines.append(f"File types filter: {filter_summary['file_types']}")
        lines.append(f"Format filter: {filter_summary['allowed_formats']}")
        lines.append(
            f"Size filter: {filter_summary['size_range_mb']['min']}-{filter_summary['size_range_mb']['max']} MB"
        )
        lines.append("=" * 30)
        emit_session_lines(lines, logger=self.logger)

    async def show_progress(self):
        if not self.download_coordinator or not self.download_coordinator.is_running:
            emit_session_message(
                "No active in-process download session. `--progress` only shows live progress during the current run; use `--stats` for persisted state.",
                logger=self.logger,
            )
            return
        ProgressDisplay.show_progress_once(self.download_coordinator)

    async def cleanup_tracker(self) -> int:
        self.logger.info("Cleaning up trackers for all channels...")
        total_removed = 0
        discovered_trackers = self.tracker_manager.load_existing_trackers()
        for tracker_entry in discovered_trackers:
            channel_id = tracker_entry["channel_id"]
            file_tracker = tracker_entry["file_tracker"]
            if not file_tracker:
                continue
            removed_count = file_tracker.cleanup_missing_files()
            if removed_count > 0:
                self.logger.info(
                    f"Channel {channel_id}: Removed {removed_count} missing file entries"
                )
                total_removed += removed_count

        self.logger.info(
            f"Total removed {total_removed} missing file entries from all trackers"
        )
        return total_removed

    async def close(self):
        if self.client:
            await self.client.disconnect()
        self.logger.info("=== Telegram Music Downloader Finished ===")


def config_exists(config_path: str) -> bool:
    return Path(config_path).exists()
