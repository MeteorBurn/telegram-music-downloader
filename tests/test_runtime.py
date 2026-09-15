import asyncio
import copy
import logging
import sys
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from channels import ChannelProcessor, MediaFilter
from download import TelegramDownloader
from models import DownloadOutcome, DownloadRequest
from runtime import DownloadCoordinator, DownloadQueue, DownloadTask, RateLimiter
from state import FileTracker, MessageTracker, TrackerManager
from telegram import TelegramDocumentLocator


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


class FakeDownloader:
    def __init__(self, outcomes=None, delay: float = 0.0):
        self.outcomes = outcomes or {}
        self.delay = delay
        self.attempts = {}

    async def download_media_file(self, media_info, _file_info_str=""):
        request = DownloadRequest.from_payload(media_info)
        message_id = request.message_id
        self.attempts[message_id] = self.attempts.get(message_id, 0) + 1

        if self.delay > 0:
            await asyncio.sleep(self.delay)

        status = self.outcomes.get(message_id, "success")
        if callable(status):
            status = status(self.attempts[message_id])

        if status == "success":
            return DownloadOutcome(
                status="success", file_path=f"file_{message_id}.bin"
            ).to_dict()

        if status == "skipped":
            return DownloadOutcome(
                status="skipped", reason="already exists", file_path=None
            ).to_dict()

        return DownloadOutcome(
            status="failed", reason="synthetic failure", file_path=None
        ).to_dict()


class FakeConfig:
    def __init__(self, workers: int = 1):
        self.workers = workers

    def get_concurrent_downloads(self) -> int:
        return self.workers

    def get_max_queue_size(self) -> int:
        return 50

    def get_requests_per_second(self) -> float:
        return 1000.0

    def get_burst_size(self) -> int:
        return 1000


class FakeDownloadConfig:
    def __init__(
        self,
        download_dir: str,
        normalize_track_names: bool = True,
        duration_filter=None,
    ):
        self.download_dir = download_dir
        self.normalize_track_names = normalize_track_names
        self.duration_filter = duration_filter or {"min_sec": None, "max_sec": None}

    def get_download_dir(self) -> str:
        return self.download_dir

    def get_naming_template(self) -> str:
        return "{original_name}__{message_id}"

    def get_date_format(self) -> str:
        return "%Y%m%d_%H%M%S"

    def get_normalize_track_names(self) -> bool:
        return self.normalize_track_names

    def get_duration_filter(self):
        return self.duration_filter

    def get_allowed_formats(self):
        return [".mp3"]

    def get_file_types(self):
        return ["audio", "document"]

    def get_size_filter(self):
        return {"min_mb": None, "max_mb": None}

    def get_date_filter(self):
        return {"from": None, "to": None}


class FakeDownloadClient:
    def __init__(self):
        self.download_calls = 0

    async def download_media(self, _document, file: str):
        self.download_calls += 1
        Path(file).write_bytes(b"downloaded-audio")
        return file


def build_media_info(message_id: int) -> dict:
    return {
        "message_id": message_id,
        "channel_id": "test-channel",
        "filename": f"track_{message_id}.mp3",
        "file_size": 1024,
        "type": "audio",
        "mime_type": "audio/mpeg",
    }


class ChannelProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_duration_metadata_filters_before_queueing(self):
        cases = [
            (180, 900, [125, 960, 180, 900], [3, 4], 2),
            (180, 900, [179.9, 900.1, 180.5, 899.9], [3, 4], 2),
            (180, None, [125, 180, 960], [2, 3], 1),
            (None, 900, [960, 125, 900], [2, 3], 1),
            (None, None, [125, 960], [1, 2], None),
        ]
        for min_sec, max_sec, durations, expected_ids, checkpoint in cases:
            with self.subTest(min_sec=min_sec, max_sec=max_sec):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config = FakeDownloadConfig(
                        temp_dir,
                        duration_filter={"min_sec": min_sec, "max_sec": max_sec},
                    )
                    messages = [
                        {
                            **build_media_info(message_id),
                            "has_media": True,
                            "audio_meta": {"duration": duration},
                            "document_id": message_id + 100,
                            "access_hash": message_id + 1000,
                            "file_reference": b"ref",
                        }
                        for message_id, duration in enumerate(durations, start=1)
                    ]
                    tracker_manager = TrackerManager(temp_dir)
                    coordinator = FakeDownloadCoordinator()
                    processor = ChannelProcessor(
                        FakeParser(messages),
                        MediaFilter(config),
                        tracker_manager,
                        coordinator,
                        logging.getLogger("channel_processor_test"),
                    )

                    result = await processor.process_channel(
                        "-100test",
                        SimpleNamespace(title="Synthetic Channel"),
                        max_files=2,
                    )

                    self.assertEqual(result["messages_processed"], len(messages))
                    self.assertEqual(result["files_found"], 2)
                    self.assertEqual(result["files_queued"], 2)
                    self.assertEqual(
                        [request.message_id for request, _ in coordinator.queued_tasks],
                        expected_ids,
                    )
                    tracker = tracker_manager.message_trackers["-100test"]
                    self.assertEqual(tracker.get_last_processed_id(), checkpoint)
                    for request, _ in coordinator.queued_tasks:
                        self.assertEqual(
                            request.audio_meta["duration"],
                            durations[request.message_id - 1],
                        )
                        request.outcome_callback(
                            "completed", None, {"status": "success"}
                        )
                    self.assertEqual(tracker.get_last_processed_id(), len(messages))

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

    async def test_critical_queue_result_stops_channel_processing(self):
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

            with self.assertRaises(RuntimeError):
                await processor.process_channel(
                    "-100test", SimpleNamespace(title="Synthetic Channel")
                )

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


class DownloaderNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalized_file_is_registered_at_actual_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = FakeDownloadConfig(temp_dir)
            client = FakeDownloadClient()
            tracker = FileTracker(str(Path(temp_dir) / "download_state.json"), "test-channel")
            downloader = TelegramDownloader(client, config, tracker)
            downloader._get_message_by_id = lambda _payload: asyncio.sleep(
                0, result=SimpleNamespace(media=SimpleNamespace(document=object()))
            )
            request = {
                **build_media_info(130),
                "filename": "[LABEL] Artist_-_Track_-_Alice_Remix WEB 320kbps 8A.FLAC",
            }

            result = await downloader.download_media_file(request)

            expected = Path(temp_dir) / "Artist - Track (Alice Remix) [LABEL].FLAC"
            self.assertEqual(result["status"], "success")
            self.assertEqual(Path(result["file_path"]), expected)
            self.assertEqual(expected.read_bytes(), b"downloaded-audio")
            self.assertEqual(client.download_calls, 1)
            self.assertEqual(tracker.get_downloaded_file_by_message(130)["file_path"], str(expected))
            self.assertFalse((Path(temp_dir) / (Path(request["filename"]).stem + "__130.FLAC")).exists())

    async def test_distinct_musical_versions_are_all_downloaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = FakeDownloadClient()
            downloader = TelegramDownloader(client, FakeDownloadConfig(temp_dir))
            downloader._get_message_by_id = lambda _payload: asyncio.sleep(
                0, result=SimpleNamespace(media=SimpleNamespace(document=object()))
            )
            names = ("Artist - Track", "Artist - Track (Instrumental)",
                     "Artist - Track (Alice Remix)", "Artist - Track (Bob Remix)")
            for message_id, name in enumerate(names, 150):
                with self.subTest(name=name):
                    result = await downloader.download_media_file(
                        {**build_media_info(message_id), "filename": name + ".wav"}
                    )
                    self.assertEqual(result["status"], "success")
                    self.assertEqual(Path(result["file_path"]).name, name + ".wav")
            self.assertEqual(client.download_calls, 4)
            self.assertEqual({p.name for p in Path(temp_dir).iterdir()}, {n + ".wav" for n in names})

    async def test_unsafe_normalized_name_keeps_downloaded_file(self):
        filenames = ("().wav", "CON [24bit].wav", "A" * 242 + "(PartTwo).wav")
        for filename in filenames:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp_dir:
                downloader = TelegramDownloader(
                    FakeDownloadClient(), FakeDownloadConfig(temp_dir)
                )
                downloader.naming_template = "{original_name}"
                downloader._get_message_by_id = lambda _payload: asyncio.sleep(
                    0, result=SimpleNamespace(media=SimpleNamespace(document=object()))
                )
                result = await downloader.download_media_file(
                    {**build_media_info(160), "filename": filename}
                )
                self.assertEqual(result["status"], "success")
                self.assertEqual(Path(result["file_path"]).name, filename)
                self.assertEqual(Path(result["file_path"]).read_bytes(), b"downloaded-audio")

    async def test_destination_appearing_during_download_keeps_both_files(self):
        for race_at_rename in (False, True):
            with self.subTest(race_at_rename=race_at_rename), tempfile.TemporaryDirectory() as temp_dir:
                target = Path(temp_dir) / "Artist - Track.wav"
                client = FakeDownloadClient()
                real_download = client.download_media

                async def download(document, file):
                    result = await real_download(document, file)
                    if not race_at_rename:
                        target.write_bytes(b"existing-content")
                    return result

                def race_rename(source, destination):
                    target.write_bytes(b"existing-content")
                    raise FileExistsError(str(destination))

                client.download_media = download
                downloader = TelegramDownloader(client, FakeDownloadConfig(temp_dir))
                downloader._get_message_by_id = lambda _payload: asyncio.sleep(
                    0, result=SimpleNamespace(media=SimpleNamespace(document=object()))
                )
                rename_context = (
                    patch.object(Path, "rename", race_rename)
                    if race_at_rename else nullcontext()
                )
                with rename_context:
                    result = await downloader.download_media_file(
                        {**build_media_info(170), "filename": "Artist - Track.wav"}
                    )
                downloaded = Path(temp_dir) / "Artist - Track__170.wav"
                self.assertEqual(result["status"], "success")
                self.assertEqual(Path(result["file_path"]), downloaded)
                self.assertEqual(target.read_bytes(), b"existing-content")
                self.assertEqual(client.download_calls, 1)
                self.assertEqual(downloaded.read_bytes(), b"downloaded-audio")

    async def test_known_duration_does_not_probe_downloaded_file(self):
        for duration in (180, 300.5, 900):
            with self.subTest(duration=duration):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config = FakeDownloadConfig(
                        temp_dir,
                        normalize_track_names=False,
                        duration_filter={"min_sec": 180, "max_sec": 900},
                    )
                    downloader = TelegramDownloader(FakeDownloadClient(), config)
                    downloader._get_message_by_id = lambda _payload: asyncio.sleep(
                        0, result=SimpleNamespace(media=SimpleNamespace(document=object()))
                    )

                    def unexpected_probe(_path):
                        self.fail("Known Telegram duration must not invoke ffprobe")

                    downloader._probe_duration_seconds = unexpected_probe
                    media_info = build_media_info(124)
                    media_info["audio_meta"] = {"duration": duration}

                    result = await downloader.download_media_file(media_info)

                    self.assertEqual(result["status"], "success")
                    self.assertEqual(
                        Path(result["file_path"]).read_bytes(), b"downloaded-audio"
                    )

    async def test_missing_duration_is_queued_then_probed_and_rejected(self):
        missing_metadata = [None, {}, {"title": "Track"}]
        invalid_durations = [None, 0, -1, "unknown", float("nan"), float("inf"), True]
        missing_metadata.extend({"duration": value} for value in invalid_durations)
        for audio_meta in missing_metadata:
            with self.subTest(audio_meta=audio_meta):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config = FakeDownloadConfig(
                        temp_dir,
                        normalize_track_names=False,
                        duration_filter={"min_sec": 180, "max_sec": 900},
                    )
                    client = FakeDownloadClient()
                    downloader = TelegramDownloader(client, config)
                    downloader._get_message_by_id = lambda _payload: asyncio.sleep(
                        0, result=SimpleNamespace(media=SimpleNamespace(document=object()))
                    )

                    def probe_downloaded_file(path):
                        self.assertEqual(path.read_bytes(), b"downloaded-audio")
                        return 125.0

                    downloader._probe_duration_seconds = probe_downloaded_file
                    media_info = {
                        **build_media_info(124),
                        "has_media": True,
                        "audio_meta": audio_meta,
                        "document_id": 224,
                        "access_hash": 1124,
                        "file_reference": b"ref",
                    }
                    coordinator = FakeDownloadCoordinator()
                    tracker_manager = TrackerManager(temp_dir)
                    processor = ChannelProcessor(
                        FakeParser([media_info]),
                        MediaFilter(config),
                        tracker_manager,
                        coordinator,
                        logging.getLogger("channel_processor_test"),
                    )

                    scan_result = await processor.process_channel(
                        "-100test", SimpleNamespace(title="Synthetic Channel")
                    )
                    self.assertEqual(scan_result["files_queued"], 1)
                    request, file_info = coordinator.queued_tasks[0]
                    with self.assertLogs(
                        "telegram_music_downloader", level="INFO"
                    ) as logs:
                        result = await downloader.download_media_file(request, file_info)

                    self.assertEqual(client.download_calls, 1)
                    self.assertEqual(result["status"], "skipped")
                    self.assertIn(
                        "Duration 125.0 sec is below minimum 180 sec", result["reason"]
                    )
                    self.assertIn(
                        "[FILTER] duration: [180 sec > 125.0 sec] track_124__124.mp3",
                        "\n".join(logs.output),
                    )
                    expected_path = Path(request.download_dir) / "track_124__124.mp3"
                    self.assertFalse(expected_path.exists())
                    self.assertEqual(request.file_tracker.downloaded_files, {})

    async def test_duration_probe_failure_deletes_file_and_returns_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = FakeDownloadConfig(
                temp_dir,
                normalize_track_names=False,
                duration_filter={"min_sec": 180, "max_sec": 900},
            )
            client = FakeDownloadClient()
            downloader = TelegramDownloader(client, config)
            downloader._get_message_by_id = lambda _payload: asyncio.sleep(
                0, result=SimpleNamespace(media=SimpleNamespace(document=object()))
            )

            def _raise_probe_error(_path):
                raise RuntimeError("ffprobe could not read duration")

            downloader._probe_duration_seconds = _raise_probe_error

            result = await downloader.download_media_file(build_media_info(125))

            expected_path = Path(temp_dir) / "track_125__125.mp3"
            self.assertEqual(result["status"], "failed")
            self.assertIn("ffprobe could not read duration", result["reason"])
            self.assertFalse(expected_path.exists())

    async def test_duration_above_filter_is_deleted_and_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = FakeDownloadConfig(
                temp_dir,
                normalize_track_names=False,
                duration_filter={"min_sec": 180, "max_sec": 900},
            )
            client = FakeDownloadClient()
            downloader = TelegramDownloader(client, config)
            downloader._get_message_by_id = lambda _payload: asyncio.sleep(
                0, result=SimpleNamespace(media=SimpleNamespace(document=object()))
            )
            downloader._probe_duration_seconds = lambda _path: 960.0

            result = await downloader.download_media_file(build_media_info(126))

            expected_path = Path(temp_dir) / "track_126__126.mp3"
            self.assertEqual(result["status"], "skipped")
            self.assertIn("Duration 960.0 sec exceeds maximum 900 sec", result["reason"])
            self.assertFalse(expected_path.exists())

    async def test_existing_normalized_name_compares_content_before_skipping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = FakeDownloadConfig(temp_dir, normalize_track_names=True)
            client = FakeDownloadClient()
            downloader = TelegramDownloader(client, config)
            downloader._get_message_by_id = lambda _payload: asyncio.sleep(
                0, result=SimpleNamespace(media=SimpleNamespace(document=object()))
            )

            final_path = Path(temp_dir) / "Artist - Track (Alice Remix).FLAC"
            final_path.write_bytes(b"downloaded-audio")

            result = await downloader.download_media_file(
                {
                    "message_id": 123,
                    "channel_id": "test-channel",
                    "filename": "[PROMO] Artist_-_Track_-_Alice_Remix.FLAC.FLAC",
                    "file_size": 1024,
                    "type": "audio",
                    "mime_type": "audio/flac",
                    "document_id": 1,
                    "access_hash": 2,
                    "file_reference": b"ref",
                }
            )

            temp_path = Path(temp_dir) / "[PROMO] Artist_-_Track_-_Alice_Remix.FLAC__123.FLAC"

            self.assertEqual(result["status"], "skipped")
            self.assertIn("Identical normalized file already exists", result["reason"])
            self.assertEqual(result["file_path"], str(final_path))
            self.assertTrue(final_path.exists())
            self.assertFalse(temp_path.exists())
            self.assertEqual(client.download_calls, 1)

            final_path.write_bytes(b"existing-content")
            result = await downloader.download_media_file(
                {**build_media_info(124), "filename": "Artist - Track - Alice Remix.FLAC"}
            )
            kept = Path(temp_dir) / "Artist - Track - Alice Remix__124.FLAC"
            self.assertEqual(result["status"], "success")
            self.assertEqual(Path(result["file_path"]), kept)
            self.assertEqual(kept.read_bytes(), b"downloaded-audio")
            self.assertEqual(final_path.read_bytes(), b"existing-content")
            self.assertEqual(client.download_calls, 2)


class DownloadQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_keeps_join_consistent(self):
        queue = DownloadQueue(max_size=10)
        task = DownloadTask(
            request=DownloadRequest.from_media_info(build_media_info(101))
        )

        self.assertTrue(await queue.put(task))

        first_attempt = await queue.get(timeout=0.1)
        self.assertIsNotNone(first_attempt)
        self.assertTrue(await queue.retry_task(first_attempt))

        second_attempt = await queue.get(timeout=0.1)
        self.assertIs(second_attempt, task)
        self.assertEqual(second_attempt.attempts, 1)

        queue.task_done(
            second_attempt, outcome="completed", result={"status": "success"}
        )
        await asyncio.wait_for(queue.wait_empty(), timeout=0.5)

        stats = queue.get_stats()
        self.assertEqual(stats["total_added"], 1)
        self.assertEqual(stats["total_retried"], 1)
        self.assertEqual(stats["completed_tasks"], 1)
        self.assertEqual(stats["failed_tasks"], 0)


class DownloadCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_outcomes_are_reported_honestly(self):
        downloader = FakeDownloader(outcomes={1: "success", 2: "skipped", 3: "failed"})
        coordinator = DownloadCoordinator(downloader, FakeConfig(workers=1))

        await coordinator.start()
        try:
            for message_id in (1, 2, 3):
                added = await coordinator.add_download_task(
                    build_media_info(message_id)
                )
                self.assertTrue(added)

            await asyncio.wait_for(coordinator.wait_completion(), timeout=2.0)
            summary = coordinator.get_session_summary()
            progress = coordinator.get_progress_info()

            self.assertEqual(summary["files_completed"], 1)
            self.assertEqual(summary["files_skipped"], 1)
            self.assertEqual(summary["files_failed"], 1)
            self.assertEqual(progress["terminal_tasks"], 3)
            self.assertEqual(progress["completed_tasks"], 1)
            self.assertEqual(progress["skipped_tasks"], 1)
            self.assertEqual(progress["failed_tasks"], 1)
        finally:
            await coordinator.stop()

    async def test_stop_shuts_workers_down_and_fails_pending_tasks(self):
        downloader = FakeDownloader(delay=0.15)
        coordinator = DownloadCoordinator(downloader, FakeConfig(workers=1))

        await coordinator.start()
        try:
            for message_id in (10, 11, 12):
                added = await coordinator.add_download_task(
                    build_media_info(message_id)
                )
                self.assertTrue(added)

            await asyncio.sleep(0.02)
            await asyncio.wait_for(coordinator.stop(), timeout=2.0)

            summary = coordinator.get_session_summary()
            self.assertEqual(summary["files_queued"], 3)
            self.assertEqual(summary["files_completed"], 1)
            self.assertEqual(summary["files_failed"], 2)
        finally:
            if coordinator.is_running:
                await coordinator.stop()


class RateLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limiter_acquire_is_non_blocking_with_large_burst(self):
        limiter = RateLimiter(requests_per_second=1000.0, burst_size=10)
        await asyncio.wait_for(limiter.acquire("worker-test"), timeout=0.5)


class TelegramLocatorTests(unittest.TestCase):
    def test_locator_rejects_missing_required_fields(self):
        locator = TelegramDocumentLocator()
        message = locator.create_message_for_request(
            {
                "message_id": 1,
                "channel_id": "chan",
                "filename": "track.wav",
                "file_size": 100,
                "type": "audio",
            }
        )

        self.assertIsNone(message)

    def test_locator_creates_message_for_valid_request(self):
        locator = TelegramDocumentLocator()
        message = locator.create_message_for_request(
            {
                "message_id": 1,
                "channel_id": "chan",
                "filename": "track.wav",
                "file_size": 100,
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "document_id": 10,
                "access_hash": 20,
                "file_reference": b"ref",
            }
        )

        self.assertIsNotNone(message)
        self.assertEqual(message.media.document.id, 10)


if __name__ == "__main__":
    unittest.main()
