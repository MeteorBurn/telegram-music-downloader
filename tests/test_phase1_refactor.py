import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from download_coordinator import DownloadCoordinator
from download_models import DownloadOutcome, DownloadRequest
from download_queue import DownloadQueue, DownloadTask, RateLimiter
from tracker import MessageTracker


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


def build_media_info(message_id: int) -> dict:
    return {
        "message_id": message_id,
        "channel_id": "test-channel",
        "filename": f"track_{message_id}.mp3",
        "file_size": 1024,
        "type": "audio",
        "mime_type": "audio/mpeg",
    }


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


class MessageTrackerTests(unittest.TestCase):
    def test_checkpoint_advances_only_on_safe_contiguous_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker_path = Path(temp_dir) / "message_tracker.json"
            tracker = MessageTracker(str(tracker_path), "channel-1")

            tracker.register_message(10)
            tracker.register_message(11)
            tracker.register_message(12)

            tracker.mark_message_outcome(10, "completed")
            tracker.mark_message_outcome(12, "completed")

            self.assertEqual(tracker.get_last_processed_id(), 10)
            self.assertEqual(tracker.total_messages_processed, 1)

            tracker.mark_message_outcome(11, "completed")

            self.assertEqual(tracker.get_last_processed_id(), 12)
            self.assertEqual(tracker.total_messages_processed, 3)

            data = json.loads(tracker_path.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(data.keys()),
                [
                    "channel_id",
                    "last_safe_message_id",
                    "last_updated",
                    "schema_version",
                    "total_messages_processed",
                ],
            )

    def test_failed_message_stays_replayable_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker_path = Path(temp_dir) / "message_tracker.json"
            tracker = MessageTracker(str(tracker_path), "channel-1")

            tracker.register_message(20)
            tracker.register_message(21)
            tracker.register_message(22)
            tracker.mark_message_outcome(20, "completed")
            tracker.mark_message_outcome(21, "failed")
            tracker.mark_message_outcome(22, "skipped")

            self.assertEqual(tracker.get_last_processed_id(), 20)

            restarted_tracker = MessageTracker(str(tracker_path), "channel-1")
            self.assertEqual(restarted_tracker.get_last_processed_id(), 20)

            restarted_tracker.register_message(21)
            restarted_tracker.register_message(22)
            restarted_tracker.mark_message_outcome(21, "completed")
            restarted_tracker.mark_message_outcome(22, "skipped")

            self.assertEqual(restarted_tracker.get_last_processed_id(), 22)
            self.assertEqual(restarted_tracker.total_messages_processed, 3)


class RateLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limiter_acquire_is_non_blocking_with_large_burst(self):
        limiter = RateLimiter(requests_per_second=1000.0, burst_size=10)
        await asyncio.wait_for(limiter.acquire("worker-test"), timeout=0.5)


if __name__ == "__main__":
    unittest.main()
