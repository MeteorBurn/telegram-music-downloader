import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from tracker import FileTracker, MessageTracker, TrackerManager


class StateStoreTests(unittest.TestCase):
    def test_message_tracker_uses_new_scan_state_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker_path = Path(temp_dir) / "scan_state.json"
            tracker = MessageTracker(str(tracker_path), "channel-1")

            tracker.register_message(1)
            tracker.register_message(2)
            tracker.mark_message_outcome(1, "completed")
            tracker.mark_message_outcome(2, "skipped")

            payload = json.loads(tracker_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["channel_id"], "channel-1")
            self.assertEqual(payload["last_safe_message_id"], 2)
            self.assertEqual(payload["total_messages_processed"], 2)

    def test_file_tracker_uses_new_download_state_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            downloads_dir = Path(temp_dir) / "downloads"
            downloads_dir.mkdir()
            file_path = downloads_dir / "demo.mp3"
            file_path.write_bytes(b"demo-audio")

            tracker_path = Path(temp_dir) / "download_state.json"
            tracker = FileTracker(str(tracker_path), "channel-1")
            tracker.add_blacklisted_file(42, "synthetic")

            import asyncio

            async def _track():
                await tracker.track_downloaded_file(
                    {
                        "message_id": 1,
                        "channel_id": "channel-1",
                        "filename": "demo.mp3",
                        "file_size": len(file_path.read_bytes()),
                        "type": "audio",
                        "mime_type": "audio/mpeg",
                        "publish_date": None,
                    },
                    str(file_path),
                )

            asyncio.run(_track())

            payload = json.loads(tracker_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["channel_id"], "channel-1")
            self.assertEqual(payload["total_files"], 1)
            self.assertEqual(payload["blacklisted_message_ids"], [42])

    def test_tracker_manager_uses_new_state_filenames(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TrackerManager(temp_dir)
            message_tracker, file_tracker = manager.get_or_create_trackers(
                "Synthetic Channel", "-100test"
            )

            self.assertTrue(
                str(message_tracker.tracker_file).endswith("scan_state.json")
            )
            self.assertTrue(
                str(file_tracker.tracker_file).endswith("download_state.json")
            )

    def test_corrupt_scan_state_falls_back_to_empty_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker_path = Path(temp_dir) / "scan_state.json"
            tracker_path.write_text("{broken json", encoding="utf-8")

            tracker = MessageTracker(str(tracker_path), "channel-1")

            self.assertIsNone(tracker.get_last_processed_id())
            self.assertEqual(tracker.total_messages_processed, 0)

    def test_corrupt_download_state_falls_back_to_empty_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker_path = Path(temp_dir) / "download_state.json"
            tracker_path.write_text("{broken json", encoding="utf-8")

            tracker = FileTracker(str(tracker_path), "channel-1")

            self.assertEqual(tracker.downloaded_files, {})
            self.assertEqual(tracker.blacklisted_files, set())


if __name__ == "__main__":
    unittest.main()
