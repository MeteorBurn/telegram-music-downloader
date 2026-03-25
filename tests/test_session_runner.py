import io
import json
import logging
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from session_runner import SessionRunner
from tracker import TrackerManager


def write_temp_config(config_path: Path, output_dir: Path) -> None:
    config_path.write_text(
        "\n".join(
            [
                "telegram:",
                "  api_id: 123456",
                '  api_hash: "test-hash"',
                "  two_factor_auth: false",
                "channels:",
                "  - -100test",
                "download:",
                f'  output_dir: "{output_dir.as_posix()}"',
                "  timeout_between_messages: 0",
                "  max_files_per_run: 0",
                "  concurrent_downloads: 2",
                "  max_queue_size: 10",
                "  worker_timeout: 30",
                "  rate_limit:",
                "    requests_per_second: 2",
                "    burst_size: 5",
                "naming:",
                '  template: "{original_name}__{message_id}"',
                '  date_format: "%Y%m%d_%H%M%S"',
                "normalize_track_names: false",
                "filters:",
                '  file_types: ["audio", "document"]',
                '  formats: [".wav"]',
                "  size:",
                "    min_mb: 1",
                "    max_mb: 500",
                "  date:",
                '    from: "2025-01-01"',
                "    to: null",
                "logging:",
                '  level: "INFO"',
                "  console: false",
            ]
        ),
        encoding="utf-8",
    )


class SessionRunnerCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_tempdir)
        temp_path = Path(self.temp_dir.name)
        self.output_dir = temp_path / "output"
        self.config_path = temp_path / "config.yaml"
        write_temp_config(self.config_path, self.output_dir)

    async def _cleanup_tempdir(self):
        logging.shutdown()
        self.temp_dir.cleanup()

    async def test_show_statistics_reads_state_from_disk(self):
        manager = TrackerManager(str(self.output_dir))
        message_tracker, file_tracker = manager.get_or_create_trackers(
            "Synthetic Channel", "-100test"
        )
        message_tracker.register_message(1)
        message_tracker.mark_message_outcome(1, "completed")

        downloads_dir = manager.get_channel_download_dir(
            "Synthetic Channel", "-100test"
        )
        downloads_dir.mkdir(parents=True, exist_ok=True)
        audio_path = downloads_dir / "demo.wav"
        audio_path.write_bytes(b"audio-data")
        await file_tracker.track_downloaded_file(
            {
                "message_id": 1,
                "channel_id": "-100test",
                "filename": "demo.wav",
                "file_size": len(audio_path.read_bytes()),
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "publish_date": None,
                "document_id": 1,
                "access_hash": 2,
                "file_reference": b"ref",
            },
            str(audio_path),
        )

        runner = SessionRunner(str(self.config_path))
        output = io.StringIO()
        with redirect_stdout(output):
            await runner.show_statistics()
        await runner.close()

        rendered = output.getvalue()
        self.assertIn(
            "Channel -100test: 1 files, 0 blacklisted, last safe message 1", rendered
        )
        self.assertIn("Total downloaded files (all channels): 1", rendered)

    async def test_cleanup_tracker_reads_existing_state_from_disk(self):
        manager = TrackerManager(str(self.output_dir))
        _, file_tracker = manager.get_or_create_trackers(
            "Synthetic Channel", "-100test"
        )
        downloads_dir = manager.get_channel_download_dir(
            "Synthetic Channel", "-100test"
        )
        downloads_dir.mkdir(parents=True, exist_ok=True)
        audio_path = downloads_dir / "demo.wav"
        audio_path.write_bytes(b"audio-data")

        await file_tracker.track_downloaded_file(
            {
                "message_id": 1,
                "channel_id": "-100test",
                "filename": "demo.wav",
                "file_size": len(audio_path.read_bytes()),
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "publish_date": None,
                "document_id": 1,
                "access_hash": 2,
                "file_reference": b"ref",
            },
            str(audio_path),
        )
        audio_path.unlink()

        runner = SessionRunner(str(self.config_path))
        removed = await runner.cleanup_tracker()
        await runner.close()

        self.assertEqual(removed, 1)
        state_path = (
            self.output_dir / "Synthetic_Channel_-100test" / "download_state.json"
        )
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["total_files"], 0)

    async def test_show_progress_explains_standalone_behavior(self):
        runner = SessionRunner(str(self.config_path))
        output = io.StringIO()
        with redirect_stdout(output):
            await runner.show_progress()
        await runner.close()

        self.assertIn("No active in-process download session", output.getvalue())


if __name__ == "__main__":
    unittest.main()
