import asyncio
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from logger import get_logger
from state import TrackerManager
from telegram import TelegramNotAuthorizedError
from web_logs import LogBuffer
from web_session import SessionBusyError, SessionIdleError, WebSessionManager


TASK_TIMEOUT = 5


class FakeCoordinator:
    def __init__(self):
        self.is_running = False

    def get_progress_info(self):
        return {"status": "running", "total_tasks": 3, "download_dir": Path("x")}

    def get_session_summary(self):
        return {"files_queued": 3, "files_completed": 2, "files_failed": 1}


class FakeConfig:
    def __init__(self):
        self._config = {"download": {"concurrent_downloads": 2}}

    def get_channels(self):
        return ["@first", -1001]


class FakeRunner:
    def __init__(self, config_path, block=False, auth_error=False):
        self.config_path = config_path
        self.config = FakeConfig()
        self.logger = get_logger()
        self.block = block
        self.auth_error = auth_error
        self.download_coordinator = None
        self.current_channel = None
        self.session_results = None
        self.interactive = None
        self.closed = False
        self.scanning = None
        self.release = None

    async def initialize_client(self, interactive=True):
        self.interactive = interactive
        if self.auth_error:
            raise TelegramNotAuthorizedError("not authorized")
        self.download_coordinator = FakeCoordinator()

    async def run_download_session(self, max_files=0):
        self.session_results = {
            "channels_processed": 1,
            "total_files_found": 3,
            "total_files_downloaded": 0,
            "total_files_skipped": 0,
            "total_files_failed": 0,
            "total_messages_processed": 7,
            "channels_details": [
                {"channel_name": "@first", "files_queued": 3, "last_processed_id": 9}
            ],
        }
        self.download_coordinator.is_running = True
        self.current_channel = -1001
        self.scanning.set()
        if self.block:
            await self.release.wait()
        self.download_coordinator.is_running = False
        self.current_channel = None
        self.session_results["total_files_downloaded"] = 2
        return self.session_results

    async def close(self):
        self.closed = True


def write_temp_config(config_path: Path, output_dir: Path) -> None:
    config_path.write_text(
        "\n".join(
            [
                "telegram:",
                "  api_id: 123456",
                '  api_hash: "test-hash"',
                "channels:",
                "  - -100test",
                "download:",
                f'  output_dir: "{output_dir.as_posix()}"',
                "  concurrent_downloads: 3",
                "  max_queue_size: 10",
                "  rate_limit:",
                "    requests_per_second: 2",
                "naming:",
                '  template: "{original_name}__{message_id}"',
                "filters:",
                '  file_types: ["audio", "document"]',
                '  formats: [".wav"]',
                "logging:",
                '  level: "INFO"',
                "  console: false",
            ]
        ),
        encoding="utf-8",
    )


class WebSessionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.log_buffer = LogBuffer()
        self.addCleanup(get_logger().removeHandler, self.log_buffer)
        self.runners = []
        self.runner_options = {}
        self.scanning = asyncio.Event()
        self.release = asyncio.Event()

    def _factory(self, config_path):
        runner = FakeRunner(config_path, **self.runner_options)
        runner.scanning = self.scanning
        runner.release = self.release
        self.runners.append(runner)
        return runner

    def _manager(self, **runner_options):
        self.runner_options = runner_options
        return WebSessionManager("unused.yaml", self.log_buffer, self._factory)

    async def _wait_task(self, manager):
        await asyncio.wait_for(asyncio.shield(manager._task), TASK_TIMEOUT)

    async def test_session_finishes_with_results_and_summary(self):
        manager = self._manager()
        await manager.start(max_files=5)
        self.assertEqual(manager.status()["state"], "connecting")
        await self._wait_task(manager)

        status = manager.status()
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["options"], {"max_files": 5, "workers": None})
        self.assertEqual(status["results"]["total_files_downloaded"], 2)
        self.assertEqual(status["summary"]["files_completed"], 2)
        self.assertIsNone(status["progress"])
        self.assertIsNone(status["error"])
        self.assertIsNotNone(status["finished_at"])
        self.assertFalse(self.runners[0].interactive)
        self.assertTrue(self.runners[0].closed)

    async def test_running_session_rejects_start_and_status_is_json_safe(self):
        manager = self._manager(block=True)
        await manager.start(workers=4)
        await asyncio.wait_for(self.scanning.wait(), TASK_TIMEOUT)
        runner = self.runners[0]

        with self.assertRaises(SessionBusyError):
            await manager.start()
        with self.assertRaises(SessionBusyError):
            await manager.cleanup()

        status = json.loads(json.dumps(manager.status()))
        self.assertEqual(status["state"], "running")
        self.assertEqual(status["total_channels"], 2)
        self.assertEqual(status["current_channel"], -1001)
        self.assertEqual(status["channels_done"][0]["channel_name"], "@first")
        self.assertEqual(status["progress"]["download_dir"], "x")
        self.assertEqual(runner.config._config["download"]["concurrent_downloads"], 4)

        runner.release.set()
        await self._wait_task(manager)
        self.assertEqual(manager.status()["state"], "finished")

    async def test_stop_cancels_session_and_closes_runner(self):
        manager = self._manager(block=True)
        await manager.start()
        await asyncio.wait_for(self.scanning.wait(), TASK_TIMEOUT)

        await manager.stop()

        status = manager.status()
        self.assertEqual(status["state"], "stopped")
        self.assertEqual(status["summary"]["files_queued"], 3)
        self.assertTrue(self.runners[0].closed)
        self.assertFalse(manager.is_running())
        with self.assertRaises(SessionIdleError):
            await manager.stop()
        await manager.shutdown()

    async def test_not_authorized_session_fails_with_code(self):
        manager = self._manager(auth_error=True)
        await manager.start()
        await self._wait_task(manager)

        status = manager.status()
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["error"]["code"], "not_authorized")
        self.assertTrue(self.runners[0].closed)

    async def test_start_validates_options(self):
        manager = self._manager()
        for kwargs in ({"max_files": -1}, {"max_files": True}, {"workers": 0}, {"workers": "2"}):
            with self.assertRaises(ValueError):
                await manager.start(**kwargs)
        self.assertEqual(manager.status()["state"], "idle")
        self.assertEqual(self.runners, [])


class WebSessionStatisticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_tempdir)
        temp_path = Path(self.temp_dir.name)
        self.output_dir = temp_path / "output"
        self.config_path = temp_path / "config.yaml"
        write_temp_config(self.config_path, self.output_dir)
        self.manager = WebSessionManager(str(self.config_path), LogBuffer())

    async def _cleanup_tempdir(self):
        logging.shutdown()
        self.temp_dir.cleanup()

    async def _track(self, file_tracker, downloads_dir, message_id, name):
        audio_path = downloads_dir / name
        content = f"audio-{name}".encode()
        audio_path.write_bytes(content)
        await file_tracker.track_downloaded_file(
            {
                "message_id": message_id,
                "channel_id": "-100test",
                "filename": name,
                "file_size": len(content),
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "publish_date": None,
                "document_id": message_id,
                "access_hash": 2,
                "file_reference": b"ref",
            },
            str(audio_path),
        )
        return audio_path

    async def test_statistics_and_cleanup_read_disk_state(self):
        manager = TrackerManager(str(self.output_dir))
        message_tracker, file_tracker = manager.get_or_create_trackers(
            "Synthetic Channel", "-100test"
        )
        message_tracker.mark_message_processed(2)
        downloads_dir = manager.get_channel_download_dir("Synthetic Channel", "-100test")
        downloads_dir.mkdir(parents=True, exist_ok=True)
        await self._track(file_tracker, downloads_dir, 1, "old.wav")
        newest_path = await self._track(file_tracker, downloads_dir, 2, "new.wav")
        file_tracker.downloaded_files[next(iter(file_tracker.downloaded_files))][
            "download_date"
        ] = "2020-01-01T00:00:00"
        file_tracker.store.save_state()

        statistics = json.loads(json.dumps(await self.manager.statistics()))
        self.assertEqual(statistics["totals"]["downloaded"], 2)
        self.assertEqual(statistics["totals"]["channels"], 1)
        channel = statistics["channels"][0]
        self.assertEqual(channel["channel_id"], "-100test")
        self.assertEqual(channel["folder"], "Synthetic_Channel_-100test")
        self.assertEqual(channel["last_safe_message_id"], 2)
        self.assertEqual([item["filename"] for item in statistics["recent"]], ["new.wav", "old.wav"])
        self.assertEqual(statistics["workers"], 3)
        self.assertIn("allowed_formats", statistics["filters"])

        newest_path.unlink()
        self.assertEqual(await self.manager.cleanup(), 1)
        statistics = await self.manager.statistics()
        self.assertEqual(statistics["totals"]["downloaded"], 1)


class LogBufferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.buffer = LogBuffer(capacity=3)
        self.test_logger = logging.getLogger("tests.web_logs")
        self.test_logger.setLevel(logging.DEBUG)
        self.test_logger.propagate = False
        self.test_logger.addHandler(self.buffer)
        self.addCleanup(self.test_logger.removeHandler, self.buffer)

    async def test_snapshot_strips_ansi_and_filters_by_id(self):
        self.test_logger.info("\x1b[31m[CRITICAL] red\x1b[0m")
        for index in range(3):
            self.test_logger.warning(f"line {index}")

        entries = self.buffer.snapshot()
        self.assertEqual([entry["id"] for entry in entries], [2, 3, 4])
        self.assertEqual(entries[0]["level"], "WARNING")
        self.assertEqual(self.buffer.snapshot(after_id=3)[0]["message"], "line 2")
        self.assertEqual(len(self.buffer.snapshot(limit=1)), 1)

        fresh = LogBuffer()
        self.test_logger.addHandler(fresh)
        self.addCleanup(self.test_logger.removeHandler, fresh)
        self.test_logger.info("\x1b[31m[CRITICAL] red\x1b[0m")
        self.assertEqual(fresh.snapshot()[0]["message"], "[CRITICAL] red")
        self.assertRegex(fresh.snapshot()[0]["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")

    async def test_subscriber_receives_entries_until_unsubscribed(self):
        queue = self.buffer.subscribe()
        self.test_logger.info("hello")
        entry = await asyncio.wait_for(queue.get(), TASK_TIMEOUT)
        self.assertEqual(entry["message"], "hello")

        self.buffer.unsubscribe(queue)
        self.test_logger.info("after")
        await asyncio.sleep(0)
        self.assertTrue(queue.empty())


if __name__ == "__main__":
    unittest.main()
