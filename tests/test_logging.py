import asyncio
import io
import logging
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from app import SessionManager, SessionRunner
from channels import ChannelProcessor, MediaFilter
from config import ConfigLoader
from download import TelegramDownloader
from logger import PROJECT_LOGGER_NAME, setup_logging
from models import DownloadOutcome, DownloadRequest
from runtime import (
    DownloadCoordinator,
    DownloadMonitor,
    DownloadQueue,
    DownloadTask,
    DownloadWorker,
    RateLimiter,
    WorkerPool,
)
from state import DownloadStateStore, MessageTracker, TrackerManager
from telegram import (
    DocumentAttributeFilename,
    PasswordHashInvalidError,
    PhoneCodeInvalidError,
    RpcMcgetFailError,
    SessionPasswordNeededError,
    TelegramDocumentLocator,
    TelegramMusicClient,
    MessageParser,
)


def write_temp_config(
    config_path: Path, output_dir: Path, console: bool = False
) -> None:
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
                '  level: "DEBUG"',
                f"  console: {'true' if console else 'false'}",
            ]
        ),
        encoding="utf-8",
    )


class FakeMonitorCoordinator:
    def get_progress_info(self):
        return {
            "status": "running",
            "progress_percentage": 50.0,
            "terminal_tasks": 2,
            "total_tasks": 4,
            "completed_tasks": 1,
            "skipped_tasks": 1,
            "failed_tasks": 0,
            "active_workers": 1,
            "total_workers": 2,
            "queue_size": 2,
            "download_speed_mbpm": 5.5,
            "active_downloads": [
                {
                    "worker_id": "worker_1",
                    "filename": "track.wav",
                    "file_size_mb": 10.0,
                }
            ],
            "estimated_time_remaining": 75,
            "total_mb_downloaded": 12.5,
        }

    def get_session_summary(self):
        return {
            "files_queued": 4,
            "files_completed": 2,
            "files_skipped": 1,
            "files_failed": 1,
            "total_mb_downloaded": 12.5,
            "session_duration_seconds": 75,
            "average_speed_mbpm": 10.0,
            "success_rate": 75.0,
        }


class FakeTelegramClient:
    async def download_media(self, _document, file: str):
        Path(file).write_bytes(b"audio-data")
        return file


class MemoryLogHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def build_media_info(message_id: int, **overrides):
    payload = {
        "message_id": message_id,
        "channel_id": "test-channel",
        "has_media": True,
        "filename": f"track_{message_id}.wav",
        "file_size": 2 * 1024 * 1024,
        "type": "audio",
        "mime_type": "audio/vnd.wave",
        "document_id": message_id,
        "access_hash": message_id + 1000,
        "file_reference": f"ref-{message_id}".encode("ascii"),
    }
    payload.update(overrides)
    return payload


class FakeConfig:
    def __init__(self, workers: int = 1, queue_size: int = 3):
        self.workers = workers
        self.queue_size = queue_size

    def get_concurrent_downloads(self) -> int:
        return self.workers

    def get_max_queue_size(self) -> int:
        return self.queue_size

    def get_requests_per_second(self) -> float:
        return 1000.0

    def get_burst_size(self) -> int:
        return 1000


class FakeOutcomeDownloader:
    def __init__(self, outcomes=None, delay: float = 0.0, raise_error: bool = False):
        self.outcomes = outcomes or {}
        self.delay = delay
        self.raise_error = raise_error

    async def download_media_file(self, media_info, _file_info_str=""):
        if self.raise_error:
            raise RuntimeError("worker download boom")

        request = media_info if hasattr(media_info, "message_id") else None
        if request is None:
            from models import DownloadRequest, DownloadOutcome

            request = DownloadRequest.from_payload(media_info)
        else:
            from models import DownloadOutcome

        if self.delay:
            await asyncio.sleep(self.delay)

        outcome = self.outcomes.get(request.message_id, "success")
        if outcome == "success":
            return DownloadOutcome(status="success", file_path="ok.bin").to_dict()
        if outcome == "skipped":
            return DownloadOutcome(status="skipped", reason="already there").to_dict()
        return DownloadOutcome(status="failed", reason="synthetic failure").to_dict()


class ParserClient:
    def __init__(self, entities=None, entity_errors=None, iter_behaviors=None):
        self.entities = entities or {}
        self.entity_errors = entity_errors or {}
        self.iter_behaviors = iter_behaviors or {}

    async def get_entity(self, channel):
        if channel in self.entity_errors:
            raise self.entity_errors[channel]
        return self.entities[channel]

    async def iter_messages(self, entity, **kwargs):
        behavior = self.iter_behaviors.get(entity.title)
        if isinstance(behavior, Exception):
            raise behavior
        for item in behavior or []:
            yield item


class FakeDocument:
    def __init__(self, filename: str = "track.wav", mime_type: str = "audio/vnd.wave"):
        try:
            attr = DocumentAttributeFilename(filename)
        except TypeError:
            attr = DocumentAttributeFilename()
            setattr(attr, "file_name", filename)
        self.attributes = [attr]
        self.mime_type = mime_type
        self.size = 2 * 1024 * 1024
        self.id = 99
        self.access_hash = 199
        self.file_reference = b"ref"


class FakeMedia:
    def __init__(self, document=None):
        self.document = document


class FakeMessage:
    def __init__(self, message_id: int, media=None):
        self.id = message_id
        self.date = datetime(2025, 2, 1, tzinfo=timezone.utc)
        self.media = media


class ChannelFakeParser:
    def __init__(self, messages, stats=None, error=None):
        self.messages = messages
        self.stats = stats or {"media_messages": len(messages)}
        self.error = error

    async def get_channel_stats(self, _entity):
        return self.stats

    async def parse_messages(self, _entity, **_kwargs):
        if self.error:
            raise self.error
        for message in self.messages:
            yield message


class ChannelFakeMediaFilter:
    def __init__(self, accepted_ids=None):
        self.accepted_ids = set(accepted_ids or [])

    def should_process_media(self, media_info):
        message_id = (
            media_info.message_id
            if hasattr(media_info, "message_id")
            else media_info["message_id"]
        )
        return message_id in self.accepted_ids


class ChannelFakeCoordinator:
    def __init__(self, rejected_ids=None):
        self.rejected_ids = set(rejected_ids or [])
        self.queued = []

    async def add_download_task(self, media_info, file_info_str=""):
        from models import DownloadRequest

        request = DownloadRequest.from_payload(media_info)
        self.queued.append((request, file_info_str))
        return request.message_id not in self.rejected_ids


class FakeAuthClient:
    def __init__(self, authorized=True, connect_error=None, sign_in_effect=None):
        self.authorized = authorized
        self.connect_error = connect_error
        self.sign_in_effect = sign_in_effect
        self.connected = False

    async def connect(self):
        if self.connect_error:
            raise self.connect_error
        self.connected = True

    async def is_user_authorized(self):
        return self.authorized

    async def send_code_request(self, _phone):
        return None

    async def sign_in(self, *args, **kwargs):
        effect = self.sign_in_effect
        if isinstance(effect, Exception):
            raise effect
        return None

    def is_connected(self):
        return self.connected

    async def disconnect(self):
        self.connected = False


class LoggingHarness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_tempdir)
        temp_path = Path(self.temp_dir.name)
        self.output_dir = temp_path / "output"
        self.config_path = temp_path / "config.yaml"
        write_temp_config(self.config_path, self.output_dir, console=False)
        self.config = ConfigLoader(str(self.config_path))
        self.logger = setup_logging(self.config)
        self.memory_handler = MemoryLogHandler()
        self.logger.addHandler(self.memory_handler)
        self.addCleanup(self.logger.removeHandler, self.memory_handler)

    async def _cleanup_tempdir(self):
        logging.shutdown()
        self.temp_dir.cleanup()

    def read_console_log(self) -> str:
        return (self.output_dir / "console.log").read_text(encoding="utf-8")

    def assert_logged(self, *messages: str) -> None:
        joined = "\n".join(self.memory_handler.messages)
        for message in messages:
            self.assertIn(message, joined)


class LoggingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_tempdir)
        temp_path = Path(self.temp_dir.name)
        self.output_dir = temp_path / "output"
        self.config_path = temp_path / "config.yaml"
        write_temp_config(self.config_path, self.output_dir, console=False)

    async def _cleanup_tempdir(self):
        logging.shutdown()
        self.temp_dir.cleanup()

    def read_console_log(self) -> str:
        return (self.output_dir / "console.log").read_text(encoding="utf-8")

    async def test_setup_logging_is_idempotent_and_uses_single_file_handler(self):
        config = ConfigLoader(str(self.config_path))
        logger = setup_logging(config)
        logger = setup_logging(config)

        self.assertEqual(logger.name, PROJECT_LOGGER_NAME)
        self.assertEqual(len(logger.handlers), 1)

        logger.info("idempotent logger marker")
        log_content = self.read_console_log()
        self.assertEqual(log_content.count("idempotent logger marker"), 1)

    async def test_session_outputs_are_mirrored_to_console_log(self):
        runner = SessionRunner(str(self.config_path))
        output = io.StringIO()
        with redirect_stdout(output):
            await runner.show_statistics()
            await runner.show_progress()
        await runner.close()

        rendered = output.getvalue()
        log_content = self.read_console_log()

        self.assertIn("[STATS] Download Statistics", rendered)
        self.assertIn("No active in-process download session", rendered)
        self.assertIn("[STATS] Download Statistics", log_content)
        self.assertIn("No active in-process download session", log_content)
        self.assertIn("[START] Telegram Music Downloader Started", log_content)
        self.assertIn("[STOP] Telegram Music Downloader Finished", log_content)

    async def test_live_progress_redraw_is_not_written_to_console_log(self):
        setup_logging(ConfigLoader(str(self.config_path)))
        monitor = DownloadMonitor(FakeMonitorCoordinator())

        output = io.StringIO()
        with redirect_stdout(output):
            monitor._display_progress(monitor.coordinator.get_progress_info())
            monitor.display_summary()

        rendered = output.getvalue()
        log_content = self.read_console_log()

        self.assertIn("Progress:", rendered)
        self.assertIn("track.wav", rendered)
        self.assertIn("[SUMMARY] Download Session Complete", log_content)
        self.assertNotIn("Progress:", log_content)
        self.assertNotIn("track.wav (10.0 MB)", log_content)

    async def test_project_modules_write_into_same_console_log(self):
        config = ConfigLoader(str(self.config_path))
        setup_logging(config)

        manager = TrackerManager(str(self.output_dir))
        _, file_tracker = manager.get_or_create_trackers(
            "Synthetic Channel", "-100test"
        )
        file_tracker.add_blacklisted_file(7, "timeout")
        file_tracker.remove_from_blacklist(7)

        broken_state = (
            self.output_dir / "Synthetic_Channel_-100test" / "download_state.json"
        )
        broken_state.write_text("{broken json", encoding="utf-8")
        DownloadStateStore(str(broken_state), "-100test")

        media_filter = MediaFilter(config)
        media_filter.should_process_media(
            {
                "message_id": 8,
                "channel_id": "-100test",
                "has_media": True,
                "filename": "bad.mp3",
                "file_size": 10 * 1024 * 1024,
                "type": "audio",
                "mime_type": "audio/mpeg",
                "publish_date": "not-a-date",
                "document_id": 80,
                "access_hash": 81,
                "file_reference": b"ref",
            }
        )

        locator = TelegramDocumentLocator()
        locator.create_message_for_request(
            {
                "message_id": 9,
                "channel_id": "-100test",
                "filename": "missing.wav",
                "file_size": 1024,
                "type": "audio",
            }
        )

        log_content = self.read_console_log()
        self.assertIn(
            "[INIT] Trackers created for channel Synthetic Channel (-100test)",
            log_content,
        )
        self.assertIn("[BLACKLIST] Message 7 blacklisted: timeout", log_content)
        self.assertIn("[BLACKLIST] Message 7 removed from blacklist", log_content)
        self.assertIn("Failed to load state from", log_content)
        self.assertIn("[WARN] Starting with empty state", log_content)
        self.assertIn("[FILTER] format: bad.mp3", log_content)
        self.assertIn("Missing Telegram locator fields for message 9", log_content)

    async def test_downloader_logs_success_skip_and_failure_paths(self):
        config = ConfigLoader(str(self.config_path))
        setup_logging(config)

        manager = TrackerManager(str(self.output_dir))
        _, file_tracker = manager.get_or_create_trackers(
            "Synthetic Channel", "-100test"
        )
        download_dir = manager.get_channel_download_dir("Synthetic Channel", "-100test")
        download_dir.mkdir(parents=True, exist_ok=True)

        downloader = TelegramDownloader(
            FakeTelegramClient(), config, file_tracker=file_tracker
        )
        success_request = {
            "message_id": 10,
            "channel_id": "-100test",
            "filename": "song.wav",
            "file_size": 2 * 1024 * 1024,
            "type": "audio",
            "mime_type": "audio/vnd.wave",
            "document_id": 110,
            "access_hash": 111,
            "file_reference": b"ref-10",
            "download_dir": str(download_dir),
            "file_tracker": file_tracker,
        }

        result = await downloader.download_media_file(
            success_request, "[02:00] [2.0 MB]"
        )
        self.assertEqual(result["status"], "success")

        skipped = await downloader.download_media_file(
            success_request, "[02:00] [2.0 MB]"
        )
        self.assertEqual(skipped["status"], "skipped")

        failed = await downloader.download_media_file(
            {
                "message_id": 11,
                "channel_id": "-100test",
                "filename": "broken.wav",
                "file_size": 2 * 1024 * 1024,
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "document_id": 210,
                "access_hash": 211,
                "download_dir": str(download_dir),
                "file_tracker": file_tracker,
            },
            "[03:00] [2.0 MB]",
        )
        self.assertEqual(failed["status"], "failed")

        log_content = self.read_console_log()
        self.assertIn("[OK] Downloaded: song__10.wav [02:00] [2.0 MB]", log_content)
        self.assertIn(
            "Skipped: File already downloaded:",
            log_content,
        )
        self.assertIn("Missing Telegram locator fields for message 11", log_content)
        self.assertIn("[FAIL] Could not retrieve message 11", log_content)

    async def test_async_concurrent_logging_records_every_message_without_hanging(self):
        setup_logging(ConfigLoader(str(self.config_path)))
        logger = logging.getLogger(PROJECT_LOGGER_NAME)

        async def emit_logs(worker_id: int):
            for index in range(10):
                logger.info(f"async-worker-{worker_id} message-{index}")
                await asyncio.sleep(0)

        await asyncio.wait_for(
            asyncio.gather(*(emit_logs(worker_id) for worker_id in range(5))),
            timeout=1.0,
        )

        log_content = self.read_console_log()
        for worker_id in range(5):
            for index in range(10):
                self.assertIn(f"async-worker-{worker_id} message-{index}", log_content)


class LoggingMessageCoverageTests(LoggingHarness):
    async def test_config_loader_and_session_manager_messages(self):
        local_config_path = self.config_path.parent / "local_config.yaml"
        local_config_path.write_text("[1]", encoding="utf-8")

        config_with_bad_local = ConfigLoader(str(self.config_path))
        self.assertEqual(
            config_with_bad_local.consume_startup_messages(),
            [
                (
                    "warning",
                    f"Warning: Local config content is not a dictionary, skipping: {local_config_path}",
                )
            ],
        )

        manager = SessionManager(str(self.output_dir / "sessions"))
        self.assertFalse(manager.session_exists("missing"))
        self.assertEqual(manager.list_sessions(), [])
        self.assertFalse(manager.delete_session("missing"))
        self.assertFalse(manager.backup_session("missing"))

        session_file = Path(manager.get_session_path("demo")).with_suffix(".session")
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text("session", encoding="utf-8")
        self.assertTrue(manager.session_exists("demo"))
        self.assertTrue(manager.backup_session("demo"))
        self.assertTrue(manager.delete_session("demo"))

        self.assert_logged(
            f"Session directory ensured: {self.output_dir / 'sessions'}",
            "Session missing exists: False",
            "Found 0 sessions",
            "Session file not found: missing",
            "Session not found: missing",
            "Session demo exists: True",
            "Session backed up: demo ->",
            "Session deleted: demo",
        )

    async def test_media_filter_and_locator_messages(self):
        media_filter = MediaFilter(self.config)
        media_filter.should_process_media(
            {"message_id": 1, "channel_id": "chan", "has_media": True}
        )
        media_filter.should_process_media(
            build_media_info(2, type="video", filename="clip.wav")
        )
        media_filter.should_process_media(
            build_media_info(3, filename="track.mp3", mime_type="audio/mpeg")
        )
        media_filter.should_process_media(build_media_info(4, file_size=100))
        media_filter.should_process_media(
            build_media_info(5, publish_date="2024-01-01T00:00:00+00:00")
        )
        media_filter.should_process_media(build_media_info(6, publish_date="bad-date"))
        media_filter.should_process_media(
            build_media_info(7, publish_date="2025-02-01T00:00:00+00:00")
        )
        media_filter.should_process_media("bad-payload")

        locator = TelegramDocumentLocator()
        locator.create_message_for_request(
            {
                "message_id": 8,
                "channel_id": "chan",
                "filename": "track.wav",
                "file_size": 100,
                "type": "audio",
            }
        )

        self.assert_logged(
            "Missing required media fields in message 1",
            "[FILTER] type: clip.wav",
            "[FILTER] format: track.mp3",
            "[FILTER] size: track_4.wav",
            "[FILTER] date: track_5.wav",
            "[WARN] Invalid date format: bad-date",
            "Missing Telegram locator fields for message 8",
        )

    async def test_message_parser_messages(self):
        success_entity = SimpleNamespace(title="Good Channel", id=10)
        self.config._config["channels"] = ["good", "bad"]
        parser = MessageParser(
            ParserClient(
                entities={"good": success_entity},
                entity_errors={"bad": RuntimeError("entity fail")},
                iter_behaviors={
                    "Good Channel": [
                        FakeMessage(1, media=None),
                        FakeMessage(2, media=SimpleNamespace()),
                        FakeMessage(3, media=FakeMedia(FakeDocument("track.wav"))),
                    ]
                },
            ),
            self.config,
        )

        entities = await parser.get_channels_entities()
        self.assertEqual(len(entities), 1)

        parsed = []
        async for item in parser.parse_messages(
            success_entity, last_processed_id=5, config_channel_id="cfg-channel"
        ):
            parsed.append(item)
        self.assertEqual(len(parsed), 3)

        self.config._config["filters"]["date"]["from"] = None
        begin_parser = MessageParser(
            ParserClient(iter_behaviors={"Good Channel": []}), self.config
        )
        async for _ in begin_parser.parse_messages(success_entity):
            pass

        self.config._config["filters"]["date"]["from"] = "2025-01-01"
        date_parser = MessageParser(
            ParserClient(iter_behaviors={"Good Channel": []}), self.config
        )
        async for _ in date_parser.parse_messages(success_entity):
            pass

        rpc_parser = MessageParser(
            ParserClient(
                iter_behaviors={"Good Channel": RpcMcgetFailError("rpc fail")}
            ),
            self.config,
        )
        with patch("telegram.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            async for _ in rpc_parser.parse_messages(success_entity):
                pass
            sleep_mock.assert_awaited()

        error_parser = MessageParser(
            ParserClient(iter_behaviors={"Good Channel": RuntimeError("parse fail")}),
            self.config,
        )
        async for _ in error_parser.parse_messages(success_entity):
            pass

        stats_parser = MessageParser(
            ParserClient(iter_behaviors={"Good Channel": RuntimeError("stats fail")}),
            self.config,
        )
        stats = await stats_parser.get_channel_stats(success_entity)
        self.assertEqual(stats, {})

        self.assert_logged(
            "[CHANNEL] Entity resolved: good -> Good Channel",
            "[FAIL] Failed to get entity for bad: entity fail",
            "Parsing messages from channel Good Channel starting after message ID 5",
            "Message 1 has no media",
            "Failed to extract media info from message 2",
            "Found media in message 3: track.wav (audio)",
            "Parsing messages from channel Good Channel from the beginning",
            "Parsing messages from channel Good Channel starting from date 2025-01-01",
            "[WARN] Telegram internal issues:",
            "[WARN] Waiting 60 seconds before retry...",
            "[FAIL] Error parsing messages from Good Channel: parse fail",
            "[FAIL] Error getting channel stats: stats fail",
        )

    async def test_download_queue_and_rate_limiter_messages(self):
        queue = DownloadQueue(max_size=3)
        task1 = DownloadTask(request=SimpleNamespace(**build_media_info(11)))
        task1.request = __import__("models").DownloadRequest.from_payload(
            build_media_info(11)
        )
        task2 = __import__("models").DownloadRequest.from_payload(build_media_info(12))
        duplicate = DownloadTask(request=task1.request)

        self.assertTrue(await queue.put(DownloadTask(request=task1.request)))
        self.assertFalse(await queue.put(duplicate))

        queued_task = await queue.get(timeout=0.1)
        queue.task_done(queued_task, outcome="completed", result={"status": "success"})

        skipped_task = DownloadTask(request=task2)
        await queue.put(skipped_task)
        skipped_task = await queue.get(timeout=0.1)
        queue.task_done(skipped_task, outcome="skipped", result={"status": "skipped"})

        failed_task = DownloadTask(
            request=__import__("models").DownloadRequest.from_payload(
                build_media_info(13)
            )
        )
        await queue.put(failed_task)
        failed_task = await queue.get(timeout=0.1)
        queue.task_done(failed_task, outcome="failed", result={"status": "failed"})

        retry_task = DownloadTask(
            request=__import__("models").DownloadRequest.from_payload(
                build_media_info(14)
            )
        )
        await queue.put(retry_task)
        retry_task = await queue.get(timeout=0.1)
        self.assertTrue(await queue.retry_task(retry_task))

        max_retry_task = DownloadTask(
            request=__import__("models").DownloadRequest.from_payload(
                build_media_info(15)
            ),
            attempts=2,
            max_attempts=3,
        )
        await queue.put(max_retry_task)
        max_retry_task = await queue.get(timeout=0.1)
        self.assertFalse(await queue.retry_task(max_retry_task))

        callback_task = DownloadTask(
            request=__import__("models").DownloadRequest.from_payload(
                build_media_info(16)
            ),
            outcome_callback=lambda *_args: (_ for _ in ()).throw(
                RuntimeError("callback boom")
            ),
        )
        await queue.put(callback_task)
        callback_task = await queue.get(timeout=0.1)
        queue.task_done(
            callback_task, outcome="completed", result={"status": "success"}
        )

        with patch.object(queue._queue, "put", side_effect=asyncio.QueueFull()):
            self.assertFalse(
                await queue.put(
                    DownloadTask(
                        request=__import__("models").DownloadRequest.from_payload(
                            build_media_info(17)
                        )
                    )
                )
            )
        with patch.object(queue._queue, "put", side_effect=RuntimeError("put boom")):
            self.assertFalse(
                await queue.put(
                    DownloadTask(
                        request=__import__("models").DownloadRequest.from_payload(
                            build_media_info(18)
                        )
                    )
                )
            )
        with patch.object(queue._queue, "get", side_effect=RuntimeError("get boom")):
            self.assertIsNone(await queue.get(timeout=0.1))

        failed_requeue = DownloadTask(
            request=__import__("models").DownloadRequest.from_payload(
                build_media_info(19)
            )
        )
        await queue.put(failed_requeue)
        failed_requeue = await queue.get(timeout=0.1)
        with patch.object(queue, "put", new=AsyncMock(return_value=False)):
            self.assertFalse(await queue.retry_task(failed_requeue))

        limiter = RateLimiter(requests_per_second=1.0, burst_size=1)
        await limiter.acquire("worker-a")
        with patch("runtime.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            await limiter.acquire("worker-a")
            sleep_mock.assert_awaited()

        self.assert_logged(
            "Added task test-channel_11 to queue",
            "Task test-channel_11 already exists, skipping",
            "Task test-channel_11 completed successfully",
            "Task test-channel_12 skipped",
            "Task test-channel_13 failed",
            "Retrying task (attempt 1/3)",
            "Task exceeded max attempts (3), marking as failed",
            "Task outcome callback failed: callback boom",
            "Download queue is full, cannot add more tasks",
            "Error adding task to queue: put boom",
            "Error getting task from queue: get boom",
            "Failed to requeue task for retry, marking as critical",
            "Rate limit acquired for worker worker-a",
            "Rate limit hit for worker worker-a",
        )

    async def test_worker_pool_coordinator_and_monitor_messages(self):
        from models import DownloadRequest

        class QueueForProcess:
            def __init__(self, task):
                self.task = task

            async def get(self, timeout=0.5):
                task, self.task = self.task, None
                return task

            def task_done(self, *args, **kwargs):
                return None

            async def retry_task(self, _task):
                return False

        worker = DownloadWorker(
            "worker_1",
            FakeOutcomeDownloader(outcomes={21: "success"}),
            QueueForProcess(
                DownloadTask(request=DownloadRequest.from_payload(build_media_info(21)))
            ),
            RateLimiter(requests_per_second=1000.0, burst_size=1000),
        )
        original_process_next_task = worker._process_next_task

        async def stop_after_once():
            await original_process_next_task()
            worker.is_running = False

        worker._process_next_task = stop_after_once
        await worker.start()

        failed_worker = DownloadWorker(
            "worker_1",
            FakeOutcomeDownloader(outcomes={22: "failed"}),
            QueueForProcess(
                DownloadTask(
                    request=DownloadRequest.from_payload(build_media_info(22)),
                    max_attempts=1,
                )
            ),
            RateLimiter(requests_per_second=1000.0, burst_size=1000),
        )
        await failed_worker._process_next_task()

        quiet_worker = DownloadWorker(
            "worker_2",
            FakeOutcomeDownloader(),
            QueueForProcess(None),
            RateLimiter(requests_per_second=1000.0, burst_size=1000),
        )
        quiet_worker.current_task = DownloadTask(
            request=DownloadRequest.from_payload(build_media_info(23))
        )
        await quiet_worker.stop()

        error_worker = DownloadWorker(
            "worker_3",
            FakeOutcomeDownloader(raise_error=True),
            QueueForProcess(None),
            RateLimiter(requests_per_second=1000.0, burst_size=1000),
        )
        await error_worker._download_file(
            DownloadTask(request=DownloadRequest.from_payload(build_media_info(24)))
        )

        crash_worker = DownloadWorker(
            "worker_4",
            FakeOutcomeDownloader(),
            QueueForProcess(None),
            RateLimiter(requests_per_second=1000.0, burst_size=1000),
        )
        crash_worker._process_next_task = AsyncMock(
            side_effect=RuntimeError("queue boom")
        )
        await crash_worker.start()

        coordinator = DownloadCoordinator(
            FakeOutcomeDownloader(), FakeConfig(workers=1, queue_size=5)
        )
        coordinator.worker_pool.start = AsyncMock()
        coordinator.worker_pool.stop = AsyncMock()
        coordinator.worker_pool.wait_completion = AsyncMock()
        coordinator.worker_pool.get_stats = lambda: {
            "total_bytes_downloaded": 0,
            "active_workers": 0,
            "total_workers": 1,
        }
        coordinator.queue.get_stats = lambda: {
            "completed_tasks": 0,
            "skipped_tasks": 0,
            "failed_tasks": 0,
            "pending_tasks": 0,
            "queue_size": 0,
            "total_added": 0,
        }
        self.assertFalse(await coordinator.add_download_task(build_media_info(30)))
        await coordinator.wait_completion()
        await coordinator.start()
        await coordinator.start()
        coordinator.queue.put = AsyncMock(return_value=True)
        self.assertTrue(await coordinator.add_download_task(build_media_info(31)))
        coordinator.queue.put = AsyncMock(return_value=False)
        self.assertFalse(await coordinator.add_download_task(build_media_info(32)))
        await coordinator.wait_completion()
        await coordinator.stop()

        pool = WorkerPool(
            FakeOutcomeDownloader(),
            DownloadQueue(max_size=1),
            RateLimiter(requests_per_second=1000.0, burst_size=1000),
            num_workers=1,
        )

        async def instant_worker_start(*_args, **_kwargs):
            return None

        with patch("runtime.DownloadWorker.start", new=instant_worker_start):
            await pool.start()
        pool.queue.wait_empty = AsyncMock()
        await pool.wait_completion()
        timeout_task = asyncio.create_task(asyncio.sleep(0.2))
        pool.workers = {"worker_1": SimpleNamespace(stop=AsyncMock())}
        pool.worker_tasks = {"worker_1": timeout_task}
        pool.shutdown_timeout = 0.01
        await pool.stop()

        monitor = DownloadMonitor(FakeMonitorCoordinator())
        monitor._monitor_loop = AsyncMock()
        await monitor.start_monitoring()
        await monitor.stop_monitoring()
        failing_monitor = DownloadMonitor(FakeMonitorCoordinator())
        failing_monitor.is_monitoring = True
        failing_monitor.coordinator = SimpleNamespace(
            get_progress_info=lambda: (_ for _ in ()).throw(
                RuntimeError("monitor boom")
            )
        )
        await failing_monitor._monitor_loop()

        self.assert_logged(
            "[WORKER_1] Started",
            "[WORKER_1] -> Downloading: track_21.wav",
            "[WORKER_1] [OK] Completed: track_21.wav",
            "[WORKER_1] [FAIL] Failed: track_22.wav",
            "[WORKER_1] Stopped",
            "[WORKER_2] Stopping - current task will complete first",
            "[WORKER_3] [FAIL] Download error: worker download boom",
            "[WORKER_4] [FAIL] Crashed: queue boom",
            "[FAIL] Coordinator is not running, cannot add task",
            "Coordinator is not running",
            "[INIT] Download coordinator starting: 1 workers",
            "Coordinator is already running",
            "Added download task: track_31.wav",
            "Failed to add download task: track_32.wav",
            "[WAIT] Waiting for all downloads to complete...",
            "[WAIT] All downloads completed",
            "[STOP] Download coordinator stopping...",
            "[STOP] Download coordinator stopped",
            "[INIT] Starting worker pool: 1 workers",
            "[INIT] All 1 workers started",
            "[WARN] Worker shutdown timeout exceeded",
            "[STOP] Worker pool stopped",
            "Download monitoring started",
            "Download monitoring stopped",
            "Monitor loop error: monitor boom",
        )

    async def test_channel_processor_messages(self):
        channel_dir = self.output_dir / "Synthetic_Channel_-100test"
        channel_dir.mkdir(parents=True, exist_ok=True)
        scan_state = channel_dir / "scan_state.json"
        tracker = MessageTracker(str(scan_state), "-100test")
        tracker.register_message(5)
        tracker.mark_message_outcome(5, "completed")

        messages = [
            {"message_id": 6, "channel_id": "-100test", "has_media": False},
            {
                "message_id": 7,
                "channel_id": "-100test",
                "has_media": True,
                "filename": "invalid.wav",
                "file_size": 1,
            },
            build_media_info(
                8, channel_id="-100test", filename="missing.wav", access_hash=None
            ),
            build_media_info(
                9,
                channel_id="-100test",
                filename="queued.wav",
                audio_meta={"duration": 125},
            ),
            build_media_info(10, channel_id="-100test", filename="later.wav"),
        ]
        coordinator = ChannelFakeCoordinator()
        processor = ChannelProcessor(
            parser=ChannelFakeParser(messages),
            media_filter=ChannelFakeMediaFilter(accepted_ids={9}),
            tracker_manager=TrackerManager(str(self.output_dir)),
            download_coordinator=coordinator,
            logger=self.logger,
        )
        await processor.process_channel(
            "-100test", SimpleNamespace(title="Synthetic Channel"), max_files=1
        )

        failed_queue_processor = ChannelProcessor(
            parser=ChannelFakeParser(
                [build_media_info(11, channel_id="-100test", filename="failed.wav")]
            ),
            media_filter=ChannelFakeMediaFilter(accepted_ids={11}),
            tracker_manager=TrackerManager(str(self.output_dir)),
            download_coordinator=ChannelFakeCoordinator(rejected_ids={11}),
            logger=self.logger,
        )
        with self.assertRaises(RuntimeError):
            await failed_queue_processor.process_channel(
                "-100test", SimpleNamespace(title="Synthetic Channel")
            )

        failing_processor = ChannelProcessor(
            parser=ChannelFakeParser([], error=RuntimeError("channel boom")),
            media_filter=ChannelFakeMediaFilter(),
            tracker_manager=TrackerManager(str(self.output_dir)),
            download_coordinator=ChannelFakeCoordinator(),
            logger=self.logger,
        )
        with self.assertRaises(RuntimeError):
            await failing_processor.process_channel(
                "-100test", SimpleNamespace(title="Synthetic Channel")
            )

        self.assert_logged(
            "[CHANNEL] Processing: -100test (Synthetic Channel)",
            "[CHANNEL] Resume from message ID: 5",
            "[CHANNEL] Stats: 5 media files in last 100 messages",
            "Skipping message 6 - no media",
            "Skipping message 7 - missing required media fields",
            "Skipping message 8 - missing Telegram locator fields",
            "[QUEUE] queued.wav [02:05] [2.0 MB]",
            "[CHANNEL] File limit reached (1) for -100test",
            "[CHANNEL] Done: -100test - 1 queued, 4 messages scanned",
            "[FAIL] Failed to queue: failed.wav",
            "[CRITICAL] Failed to queue failed.wav",
            "[FAIL] Error processing channel -100test: channel boom",
        )

    async def test_client_messages(self):
        with (
            patch("telegram.TELETHON_AVAILABLE", True),
            patch(
                "telegram.TelegramClient", return_value=FakeAuthClient(authorized=True)
            ),
        ):
            client = TelegramMusicClient(1, "hash", "session")
            self.assertTrue(await client.connect())
            await client.disconnect()

        with (
            patch("telegram.TELETHON_AVAILABLE", True),
            patch(
                "telegram.TelegramClient", return_value=FakeAuthClient(authorized=False)
            ),
            patch("builtins.input", side_effect=["+123", "9999"]),
        ):
            client = TelegramMusicClient(1, "hash", "session")
            self.assertTrue(await client.connect())

        with (
            patch("telegram.TELETHON_AVAILABLE", True),
            patch(
                "telegram.TelegramClient",
                return_value=FakeAuthClient(connect_error=RuntimeError("connect fail")),
            ),
        ):
            client = TelegramMusicClient(1, "hash", "session")
            self.assertFalse(await client.connect())

        client = TelegramMusicClient(1, "hash", "session", two_factor_enabled=True)
        client.client = FakeAuthClient(
            authorized=False, sign_in_effect=PhoneCodeInvalidError("bad code")
        )
        with patch("builtins.input", side_effect=["+123", "9999"]):
            with self.assertRaises(PhoneCodeInvalidError):
                await client._authenticate()

        client = TelegramMusicClient(1, "hash", "session", two_factor_enabled=True)
        client.client = FakeAuthClient(
            authorized=False, sign_in_effect=SessionPasswordNeededError("need pass")
        )
        with (
            patch.object(
                client.client,
                "sign_in",
                side_effect=[
                    SessionPasswordNeededError("need pass"),
                    PasswordHashInvalidError("bad pass"),
                ],
            ),
            patch("builtins.input", side_effect=["+123", "9999", "secret"]),
        ):
            with self.assertRaises(PasswordHashInvalidError):
                await client._authenticate()

        self.assert_logged(
            "[AUTH] User already authorized",
            "[AUTH] Successfully connected to Telegram",
            "[AUTH] Disconnected from Telegram",
            "[AUTH] User not authorized, starting authentication",
            "[FAIL] Failed to connect to Telegram: connect fail",
            "[AUTH] Invalid verification code",
            "[AUTH] Invalid 2FA password",
        )


if __name__ == "__main__":
    unittest.main()
