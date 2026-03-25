import logging
from pathlib import Path
from typing import Any, Dict

from channel_models import (
    ChannelContext,
    ChannelProcessingResult,
    ParsedMessage,
    QueuedMessageContext,
)
from download_models import DownloadRequest


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

        self.logger.info(f"Processing channel: {channel_name} ({entity.title})")

        try:
            if context.last_processed_id:
                self.logger.info(
                    f"Continuing from last processed message ID: {context.last_processed_id}"
                )

            stats = await self.parser.get_channel_stats(entity)
            if stats:
                self.logger.info(
                    f"Channel stats: {stats['media_messages']} media files in last 100 messages"
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
                        f"Queued for download: {queued_message.filename} {queued_message.file_info_str}"
                    )
                else:
                    context.message_tracker.mark_message_outcome(message_id, "failed")
                    self.logger.warning(f"Failed to queue: {queued_message.filename}")

                if max_files > 0 and files_queued_in_channel >= max_files:
                    self.logger.info(
                        f"Reached file limit ({max_files}) for channel {channel_name} in this run."
                    )
                    break

            self.logger.info(
                f"Channel {channel_name} processed: "
                f"{result.files_queued} files queued, "
                f"{result.messages_processed} messages processed"
            )
            return result.to_dict()

        except Exception as e:
            self.logger.error(f"Error processing channel {channel_name}: {e}")
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
