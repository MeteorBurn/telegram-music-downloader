import copy
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from channel_processor import ChannelProcessor
from download_models import DownloadRequest
from tracker import TrackerManager


class FakeParser:
    def __init__(self, messages, media_messages: int = 0):
        self.messages = messages
        self.media_messages = media_messages or len(messages)

    async def get_channel_stats(self, _entity):
        return {"media_messages": self.media_messages}

    async def parse_messages(
        self, _entity, last_processed_id=None, config_channel_id=None
    ):
        for message in self.messages:
            if (
                last_processed_id is not None
                and message["message_id"] <= last_processed_id
            ):
                continue

            parsed_message = copy.deepcopy(message)
            if config_channel_id is not None:
                parsed_message.setdefault("channel_id", config_channel_id)
            yield parsed_message


class FakeMediaFilter:
    def __init__(self, accepted_message_ids=None):
        self.accepted_message_ids = set(accepted_message_ids or [])

    def should_process_media(self, media_info):
        if isinstance(media_info, dict):
            message_id = media_info["message_id"]
        else:
            message_id = media_info.message_id
        return message_id in self.accepted_message_ids


class FakeDownloadCoordinator:
    def __init__(self, rejected_message_ids=None):
        self.rejected_message_ids = set(rejected_message_ids or [])
        self.queued_tasks = []

    async def add_download_task(self, media_info, file_info_str=""):
        request = DownloadRequest.from_payload(media_info)
        if request.message_id in self.rejected_message_ids:
            return False

        self.queued_tasks.append((request, file_info_str))
        return True


class ChannelProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_channel_handles_skips_and_deferred_completion(self):
        messages = [
            {"message_id": 1, "has_media": False},
            {
                "message_id": 2,
                "has_media": True,
                "filename": "invalid.wav",
                "file_size": 1,
            },
            {
                "message_id": 3,
                "has_media": True,
                "filename": "filtered.wav",
                "file_size": 10 * 1024 * 1024,
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "document_id": 103,
                "access_hash": 1003,
                "file_reference": b"ref-3",
            },
            {
                "message_id": 4,
                "has_media": True,
                "filename": "queued.wav",
                "file_size": 10 * 1024 * 1024,
                "type": "audio",
                "audio_meta": {"duration": 125},
                "mime_type": "audio/vnd.wave",
                "document_id": 104,
                "access_hash": 1004,
                "file_reference": b"ref-4",
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            tracker_manager = TrackerManager(temp_dir)
            processor = ChannelProcessor(
                parser=FakeParser(messages),
                media_filter=FakeMediaFilter(accepted_message_ids={4}),
                tracker_manager=tracker_manager,
                download_coordinator=FakeDownloadCoordinator(),
                logger=logging.getLogger("channel_processor_test"),
            )

            result = await processor.process_channel(
                "-100test", SimpleNamespace(title="Synthetic Channel")
            )

            self.assertEqual(result["messages_processed"], 4)
            self.assertEqual(result["files_found"], 1)
            self.assertEqual(result["files_queued"], 1)
            self.assertEqual(result["last_processed_id"], 4)

            message_tracker = tracker_manager.message_trackers["-100test"]
            self.assertEqual(message_tracker.get_last_processed_id(), 3)

            queued_request, file_info_str = processor.download_coordinator.queued_tasks[
                0
            ]
            self.assertEqual(file_info_str, "[02:05] [10.0 MB]")
            self.assertEqual(queued_request.filename, "queued.wav")
            self.assertEqual(queued_request.media_type, "audio")
            queued_request.outcome_callback("completed", None, {"status": "success"})

            self.assertEqual(message_tracker.get_last_processed_id(), 4)

    async def test_failed_queue_result_blocks_contiguous_checkpoint(self):
        messages = [
            {
                "message_id": 10,
                "has_media": True,
                "filename": "first.wav",
                "file_size": 10 * 1024 * 1024,
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "document_id": 201,
                "access_hash": 2001,
                "file_reference": b"ref-10",
            },
            {
                "message_id": 11,
                "has_media": True,
                "filename": "second.wav",
                "file_size": 10 * 1024 * 1024,
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "document_id": 202,
                "access_hash": 2002,
                "file_reference": b"ref-11",
            },
            {"message_id": 12, "has_media": False},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            tracker_manager = TrackerManager(temp_dir)
            coordinator = FakeDownloadCoordinator(rejected_message_ids={11})
            processor = ChannelProcessor(
                parser=FakeParser(messages),
                media_filter=FakeMediaFilter(accepted_message_ids={10, 11}),
                tracker_manager=tracker_manager,
                download_coordinator=coordinator,
                logger=logging.getLogger("channel_processor_test"),
            )

            result = await processor.process_channel(
                "-100test", SimpleNamespace(title="Synthetic Channel")
            )

            self.assertEqual(result["files_found"], 2)
            self.assertEqual(result["files_queued"], 1)

            message_tracker = tracker_manager.message_trackers["-100test"]
            coordinator.queued_tasks[0][0].outcome_callback(
                "completed", None, {"status": "success"}
            )

            self.assertEqual(message_tracker.get_last_processed_id(), 10)

    async def test_max_files_limit_stops_channel_scan_after_limit(self):
        messages = [
            {
                "message_id": 21,
                "has_media": True,
                "filename": "first.wav",
                "file_size": 10 * 1024 * 1024,
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "document_id": 301,
                "access_hash": 3001,
                "file_reference": b"ref-21",
            },
            {
                "message_id": 22,
                "has_media": True,
                "filename": "second.wav",
                "file_size": 10 * 1024 * 1024,
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "document_id": 302,
                "access_hash": 3002,
                "file_reference": b"ref-22",
            },
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            tracker_manager = TrackerManager(temp_dir)
            coordinator = FakeDownloadCoordinator()
            processor = ChannelProcessor(
                parser=FakeParser(messages),
                media_filter=FakeMediaFilter(accepted_message_ids={21, 22}),
                tracker_manager=tracker_manager,
                download_coordinator=coordinator,
                logger=logging.getLogger("channel_processor_test"),
            )

            result = await processor.process_channel(
                "-100test", SimpleNamespace(title="Synthetic Channel"), max_files=1
            )

            self.assertEqual(result["messages_processed"], 1)
            self.assertEqual(result["files_found"], 1)
            self.assertEqual(result["files_queued"], 1)
            self.assertEqual(len(coordinator.queued_tasks), 1)

    async def test_missing_locator_fields_skip_download_queueing(self):
        messages = [
            {
                "message_id": 31,
                "has_media": True,
                "filename": "missing-locator.wav",
                "file_size": 10 * 1024 * 1024,
                "type": "audio",
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            tracker_manager = TrackerManager(temp_dir)
            coordinator = FakeDownloadCoordinator()
            processor = ChannelProcessor(
                parser=FakeParser(messages),
                media_filter=FakeMediaFilter(accepted_message_ids={31}),
                tracker_manager=tracker_manager,
                download_coordinator=coordinator,
                logger=logging.getLogger("channel_processor_test"),
            )

            result = await processor.process_channel(
                "-100test", SimpleNamespace(title="Synthetic Channel")
            )

            self.assertEqual(result["files_found"], 0)
            self.assertEqual(result["files_queued"], 0)
            self.assertEqual(len(coordinator.queued_tasks), 0)


class DownloadRequestTests(unittest.TestCase):
    def test_round_trip_preserves_extra_fields_and_normalized_values(self):
        media_info = {
            "message_id": 99,
            "channel_id": "chan-1",
            "filename": "roundtrip.wav",
            "file_size": 4096,
            "type": "audio",
            "mime_type": "audio/vnd.wave",
            "custom_field": "kept",
        }

        request = DownloadRequest.from_media_info(media_info)

        self.assertEqual(request.message_id, 99)
        self.assertEqual(request.channel_id, "chan-1")
        self.assertEqual(request.media_type, "audio")
        self.assertEqual(request.extra_fields["custom_field"], "kept")

        rebuilt_media_info = request.to_media_info()
        self.assertEqual(rebuilt_media_info["custom_field"], "kept")
        self.assertEqual(rebuilt_media_info["type"], "audio")


if __name__ == "__main__":
    unittest.main()
