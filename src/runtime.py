import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from logger import (
    emit_session_lines,
    emit_session_message,
    format_critical_message,
    get_logger,
)
from models import DownloadOutcome, DownloadRequest


TERMINAL_OUTCOMES = {"completed", "skipped", "failed", "critical"}


@dataclass
class DownloadTask:
    request: DownloadRequest
    file_info_str: str = ""
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    attempts: int = 0
    max_attempts: int = 3
    outcome_callback: Optional[
        Callable[[str, "DownloadTask", Optional[Dict[str, Any]]], None]
    ] = None

    def __lt__(self, other):
        return self.priority < other.priority

    @property
    def media_info(self) -> Dict[str, Any]:
        return self.request.to_media_info()


class DownloadQueue:
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._queue = asyncio.PriorityQueue(maxsize=max_size)
        self._pending_tasks = {}
        self._completed_tasks = set()
        self._skipped_tasks = set()
        self._failed_tasks = set()
        self._critical_tasks = set()
        self._critical_failure_reason: Optional[str] = None
        self.logger = get_logger()
        self._stats = {
            "total_added": 0,
            "total_completed": 0,
            "total_skipped": 0,
            "total_failed": 0,
            "total_critical": 0,
            "total_retried": 0,
            "current_size": 0,
        }

    async def put(self, task: DownloadTask, is_retry: bool = False) -> bool:
        try:
            task_id = self._generate_task_id(task.media_info)
            if not is_retry and (
                task_id in self._pending_tasks
                or task_id in self._completed_tasks
                or task_id in self._skipped_tasks
            ):
                self.logger.debug(f"Task {task_id} already exists, skipping")
                return False

            if not is_retry:
                task.priority = task.media_info.get("message_id", 0)

            await self._queue.put(task)
            if not is_retry:
                self._pending_tasks[task_id] = task
                self._stats["total_added"] += 1
            self._stats["current_size"] = self._queue.qsize()
            self.logger.debug(
                f"Added task {task_id} to queue (priority: {task.priority})"
            )
            return True
        except asyncio.QueueFull:
            self.logger.warning("Download queue is full, cannot add more tasks")
            return False
        except Exception as exc:
            self.logger.error(f"Error adding task to queue: {exc}")
            return False

    async def get(self, timeout: Optional[float] = None) -> Optional[DownloadTask]:
        try:
            if timeout is None:
                task = await self._queue.get()
            else:
                task = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            self._stats["current_size"] = self._queue.qsize()
            return task
        except asyncio.TimeoutError:
            return None
        except Exception as exc:
            self.logger.error(f"Error getting task from queue: {exc}")
            return None

    def task_done(
        self,
        task: DownloadTask,
        outcome: str = "completed",
        result: Optional[Dict[str, Any]] = None,
    ):
        task_id = self._generate_task_id(task.media_info)
        if outcome not in TERMINAL_OUTCOMES:
            raise ValueError(f"Unsupported task outcome: {outcome}")

        if task_id in self._pending_tasks:
            del self._pending_tasks[task_id]

        if outcome == "completed":
            self._completed_tasks.add(task_id)
            self._stats["total_completed"] += 1
            self.logger.debug(f"Task {task_id} completed successfully")
        elif outcome == "skipped":
            self._skipped_tasks.add(task_id)
            self._stats["total_skipped"] += 1
            self.logger.debug(f"Task {task_id} skipped")
        elif outcome == "failed":
            self._failed_tasks.add(task_id)
            self._stats["total_failed"] += 1
            self.logger.debug(f"Task {task_id} failed")
        else:
            self._critical_tasks.add(task_id)
            self._stats["total_critical"] += 1
            reason = (result or {}).get("reason", "Unknown critical task failure")
            self._record_critical_failure(task_id, reason)

        self._notify_task_outcome(task, outcome, result)
        self._queue.task_done()
        self._stats["current_size"] = self._queue.qsize()

    async def retry_task(self, task: DownloadTask) -> bool:
        task.attempts += 1

        if task.attempts >= task.max_attempts:
            self.logger.warning(
                f"Task exceeded max attempts ({task.max_attempts}), marking as failed"
            )
            task_id = self._generate_task_id(task.media_info)
            if task_id in self._pending_tasks:
                del self._pending_tasks[task_id]
            self._failed_tasks.add(task_id)
            self._stats["total_failed"] += 1
            self._notify_task_outcome(
                task,
                "failed",
                {"status": "failed", "reason": "Task exceeded retry limit"},
            )
            self._queue.task_done()
            self._stats["current_size"] = self._queue.qsize()
            return False

        task.priority += 1000
        success = await self.put(task, is_retry=True)
        if success:
            self._queue.task_done()
            self._stats["total_retried"] += 1
            self._stats["current_size"] = self._queue.qsize()
            self.logger.info(
                f"Retrying task (attempt {task.attempts}/{task.max_attempts})"
            )
            return True

        self.logger.warning("Failed to requeue task for retry, marking as critical")
        task_id = self._generate_task_id(task.media_info)
        if task_id in self._pending_tasks:
            del self._pending_tasks[task_id]
        self._critical_tasks.add(task_id)
        self._stats["total_critical"] += 1
        self._record_critical_failure(task_id, "Could not requeue task for retry")
        self._notify_task_outcome(
            task,
            "critical",
            {"status": "critical", "reason": "Could not requeue task for retry"},
        )
        self._queue.task_done()
        self._stats["current_size"] = self._queue.qsize()
        return False

    def _generate_task_id(self, media_info: Dict[str, Any]) -> str:
        return f"{media_info.get('channel_id', 'unknown')}_{media_info.get('message_id', 0)}"

    def get_stats(self) -> Dict[str, Any]:
        total_failed = len(self._failed_tasks) + len(self._critical_tasks)
        return {
            **self._stats,
            "pending_tasks": len(self._pending_tasks),
            "completed_tasks": len(self._completed_tasks),
            "skipped_tasks": len(self._skipped_tasks),
            "failed_tasks": total_failed,
            "critical_tasks": len(self._critical_tasks),
            "queue_size": self._queue.qsize(),
            "is_empty": self._queue.empty(),
            "is_full": self._queue.full(),
        }

    def has_critical_failure(self) -> bool:
        return self._critical_failure_reason is not None

    def get_critical_failure_reason(self) -> Optional[str]:
        return self._critical_failure_reason

    async def wait_empty(self):
        await self._queue.join()

    def clear(self, outcome: Optional[str] = None):
        while not self._queue.empty():
            try:
                task = self._queue.get_nowait()
                if outcome in TERMINAL_OUTCOMES:
                    self.task_done(
                        task,
                        outcome=outcome,
                        result={
                            "status": outcome,
                            "reason": "Task cleared during queue shutdown",
                        },
                    )
                else:
                    self._queue.task_done()
            except asyncio.QueueEmpty:
                break

        self._pending_tasks.clear()
        self._stats["current_size"] = 0

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    def full(self) -> bool:
        return self._queue.full()

    def _notify_task_outcome(
        self, task: DownloadTask, outcome: str, result: Optional[Dict[str, Any]]
    ) -> None:
        if not task.outcome_callback:
            return
        try:
            task.outcome_callback(outcome, task, result)
        except Exception as exc:
            self.logger.error(f"Task outcome callback failed: {exc}")

    def _record_critical_failure(self, task_id: str, reason: str) -> None:
        message = f"[CRITICAL] Task {task_id}: {reason}"
        if self._critical_failure_reason is None:
            self._critical_failure_reason = message
        self.logger.critical(format_critical_message(message))


class RateLimiter:
    def __init__(self, requests_per_second: float = 2.0, burst_size: int = 5):
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size
        self.tokens = burst_size
        self.last_update = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()
        self.logger = get_logger()

    async def acquire(self, worker_id: str = "unknown"):
        async with self._lock:
            now = asyncio.get_event_loop().time()
            time_passed = now - self.last_update
            self.tokens = min(
                self.burst_size, self.tokens + time_passed * self.requests_per_second
            )
            self.last_update = now

            if self.tokens >= 1:
                self.tokens -= 1
                self.logger.debug(
                    f"Rate limit acquired for worker {worker_id}, tokens left: {self.tokens:.2f}"
                )
                return

            wait_time = (1 - self.tokens) / self.requests_per_second
            self.logger.debug(
                f"Rate limit hit for worker {worker_id}, waiting {wait_time:.2f}s"
            )
            await asyncio.sleep(wait_time)
            self.tokens = 0
            self.last_update = asyncio.get_event_loop().time()


class DownloadWorker:
    def __init__(
        self,
        worker_id: str,
        downloader,
        queue: DownloadQueue,
        rate_limiter: RateLimiter,
    ):
        self.worker_id = worker_id
        self.downloader = downloader
        self.queue = queue
        self.rate_limiter = rate_limiter
        self.logger = get_logger()
        self.is_running = False
        self.current_task: Optional[DownloadTask] = None
        self.stats = {
            "tasks_completed": 0,
            "tasks_skipped": 0,
            "tasks_failed": 0,
            "bytes_downloaded": 0,
            "start_time": None,
            "last_activity": None,
        }

    @property
    def log_worker_id(self) -> str:
        return self.worker_id.upper()

    async def start(self):
        self.is_running = True
        self.stats["start_time"] = datetime.now()
        self.logger.info(f"[{self.log_worker_id}] Started")

        try:
            while self.is_running:
                await self._process_next_task()
        except asyncio.CancelledError:
            self.logger.info(f"[{self.log_worker_id}] Cancelled")
        except Exception as exc:
            self.logger.error(f"[{self.log_worker_id}] [FAIL] Crashed: {exc}")
        finally:
            self.logger.info(f"[{self.log_worker_id}] Stopped")

    async def stop(self):
        self.is_running = False
        if self.current_task:
            self.logger.info(
                f"[{self.log_worker_id}] Stopping - current task will complete first"
            )

    async def _process_next_task(self):
        try:
            task = await self.queue.get(timeout=0.5)
            if not task:
                return

            self.current_task = task
            self.stats["last_activity"] = datetime.now()
            await self.rate_limiter.acquire(self.worker_id)
            result = await self._download_file(task)
            outcome = result.terminal_outcome

            if outcome == "completed":
                self.stats["tasks_completed"] += 1
                self.queue.task_done(task, outcome="completed", result=result.to_dict())
                self.logger.info(
                    f"[{self.log_worker_id}] [OK] Completed: {task.request.filename}"
                )
            elif outcome == "skipped":
                self.stats["tasks_skipped"] += 1
                self.queue.task_done(task, outcome="skipped", result=result.to_dict())
                self.logger.info(
                    f"[{self.log_worker_id}] [SKIP] Skipped: {task.request.filename}"
                )
            else:
                retry_success = await self.queue.retry_task(task)
                if not retry_success:
                    self.stats["tasks_failed"] += 1
                    self.logger.warning(
                        f"[{self.log_worker_id}] [FAIL] Failed: {task.request.filename}"
                    )
        except Exception as exc:
            self.logger.error(
                f"[{self.log_worker_id}] [FAIL] Error processing task: {exc}"
            )
            if self.current_task:
                self.queue.task_done(
                    self.current_task,
                    outcome="critical",
                    result=DownloadOutcome(
                        status="critical", reason=str(exc), file_path=None, logged=True
                    ).to_dict(),
                )
                self.stats["tasks_failed"] += 1
        finally:
            self.current_task = None

    async def _download_file(self, task: DownloadTask) -> DownloadOutcome:
        try:
            self.logger.info(
                f"[{self.log_worker_id}] [DOWN] Downloading: {task.request.filename} {task.file_info_str}"
            )
            result = await self.downloader.download_media_file(
                task.request, task.file_info_str
            )
            outcome = DownloadOutcome.from_payload(result)
            if outcome.status == "success":
                self.stats["bytes_downloaded"] += task.request.file_size
            return outcome
        except Exception as exc:
            self.logger.error(f"[{self.log_worker_id}] [FAIL] Download error: {exc}")
            return DownloadOutcome(
                status="failed", reason=str(exc), file_path=None, logged=True
            )

    def get_stats(self) -> Dict[str, Any]:
        stats = self.stats.copy()
        stats.update(
            {
                "worker_id": self.worker_id,
                "is_running": self.is_running,
                "current_task": self.current_task.request.filename
                if self.current_task
                else None,
                "uptime_seconds": (
                    datetime.now() - self.stats["start_time"]
                ).total_seconds()
                if self.stats["start_time"]
                else 0,
            }
        )
        return stats


class WorkerPool:
    def __init__(
        self,
        downloader,
        queue: DownloadQueue,
        rate_limiter: RateLimiter,
        num_workers: int = 3,
    ):
        self.downloader = downloader
        self.queue = queue
        self.rate_limiter = rate_limiter
        self.num_workers = num_workers
        self.workers: Dict[str, DownloadWorker] = {}
        self.worker_tasks: Dict[str, asyncio.Task] = {}
        self.logger = get_logger()
        self.shutdown_timeout = 5.0

    async def start(self):
        self.logger.info(f"[INIT] Starting worker pool: {self.num_workers} workers")
        for index in range(self.num_workers):
            worker_id = f"worker_{index + 1}"
            worker = DownloadWorker(
                worker_id, self.downloader, self.queue, self.rate_limiter
            )
            self.workers[worker_id] = worker
            self.worker_tasks[worker_id] = asyncio.create_task(worker.start())
        self.logger.info(f"[INIT] All {self.num_workers} workers started")

    async def stop(self):
        self.logger.info("[STOP] Stopping worker pool...")
        for worker in self.workers.values():
            await worker.stop()

        if self.worker_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.worker_tasks.values(), return_exceptions=True),
                    timeout=self.shutdown_timeout,
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    "[WARN] Worker shutdown timeout exceeded, cancelling remaining tasks"
                )
                for task in self.worker_tasks.values():
                    task.cancel()
                await asyncio.gather(
                    *self.worker_tasks.values(), return_exceptions=True
                )

        self.workers.clear()
        self.worker_tasks.clear()
        self.logger.info("[STOP] Worker pool stopped")

    async def wait_completion(self):
        await self.queue.wait_empty()
        self.logger.debug("[WAIT] All tasks in queue completed")

    def get_stats(self) -> Dict[str, Any]:
        worker_stats = [worker.get_stats() for worker in self.workers.values()]
        total_completed = sum(stats["tasks_completed"] for stats in worker_stats)
        total_skipped = sum(stats["tasks_skipped"] for stats in worker_stats)
        total_failed = sum(stats["tasks_failed"] for stats in worker_stats)
        total_bytes = sum(stats["bytes_downloaded"] for stats in worker_stats)
        return {
            "num_workers": self.num_workers,
            "active_workers": sum(1 for stats in worker_stats if stats["is_running"]),
            "total_completed": total_completed,
            "total_skipped": total_skipped,
            "total_failed": total_failed,
            "total_bytes_downloaded": total_bytes,
            "total_mb_downloaded": round(total_bytes / (1024 * 1024), 2),
            "workers": worker_stats,
        }

    def get_active_downloads(self) -> list:
        active = []
        for worker in self.workers.values():
            if worker.current_task:
                active.append(
                    {
                        "worker_id": worker.worker_id,
                        "filename": worker.current_task.request.filename,
                        "file_size_mb": round(
                            worker.current_task.request.file_size / (1024 * 1024), 2
                        ),
                    }
                )
        return active


class DownloadCoordinator:
    def __init__(self, downloader, config_loader):
        self.downloader = downloader
        self.config = config_loader
        self.logger = get_logger()
        self.concurrent_downloads = self.config.get_concurrent_downloads()
        self.max_queue_size = self.config.get_max_queue_size()
        self.requests_per_second = self.config.get_requests_per_second()
        self.burst_size = self.config.get_burst_size()
        self.queue = DownloadQueue(max_size=self.max_queue_size)
        self.rate_limiter = RateLimiter(
            requests_per_second=self.requests_per_second,
            burst_size=self.burst_size,
        )
        self.worker_pool = WorkerPool(
            downloader=self.downloader,
            queue=self.queue,
            rate_limiter=self.rate_limiter,
            num_workers=self.concurrent_downloads,
        )
        self.is_running = False
        self.start_time: Optional[datetime] = None
        self.session_stats = {
            "files_queued": 0,
            "files_completed": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "total_bytes_downloaded": 0,
        }

    async def start(self):
        if self.is_running:
            self.logger.warning("Coordinator is already running")
            return

        self.is_running = True
        self.start_time = datetime.now()
        self.logger.info(
            f"[INIT] Download coordinator starting: {self.concurrent_downloads} workers, queue {self.max_queue_size}, rate {self.requests_per_second} req/sec"
        )
        self.logger.debug(f"Rate limit burst: {self.burst_size}")
        await self.worker_pool.start()

    async def stop(self):
        if not self.is_running:
            return

        self.logger.info("[STOP] Download coordinator stopping...")
        self._update_session_stats()
        self.is_running = False
        await self.worker_pool.stop()
        self.queue.clear(outcome="critical")
        self.logger.info("[STOP] Download coordinator stopped")

    async def add_download_task(self, media_info: Any, file_info_str: str = "") -> bool:
        if not self.is_running:
            self.logger.error("[FAIL] Coordinator is not running, cannot add task")
            return False

        request = DownloadRequest.from_payload(media_info)
        task = DownloadTask(
            request=request,
            file_info_str=file_info_str,
            outcome_callback=request.outcome_callback,
        )

        success = await self.queue.put(task)
        if success:
            self.session_stats["files_queued"] += 1
            self.logger.debug(f"Added download task: {request.filename}")
        else:
            self.logger.warning(f"Failed to add download task: {request.filename}")
        return success

    async def wait_completion(self):
        if not self.is_running:
            self.logger.warning("Coordinator is not running")
            return

        self.logger.info("[WAIT] Waiting for all downloads to complete...")
        while self.is_running:
            if self.queue.has_critical_failure():
                reason = self.queue.get_critical_failure_reason() or "unknown reason"
                critical_message = format_critical_message(
                    f"[CRITICAL] Stopping session due to critical failure: {reason}"
                )
                self.logger.critical(critical_message)
                raise RuntimeError(reason)
            try:
                await asyncio.wait_for(self.worker_pool.wait_completion(), timeout=0.25)
                break
            except asyncio.TimeoutError:
                continue
        self.logger.info("[WAIT] All downloads completed")
        self._update_session_stats()

    def _update_session_stats(self):
        queue_stats = self.queue.get_stats()
        worker_stats = self.worker_pool.get_stats()
        total_bytes_downloaded = max(
            self.session_stats["total_bytes_downloaded"],
            worker_stats["total_bytes_downloaded"],
        )
        self.session_stats.update(
            {
                "files_completed": queue_stats["completed_tasks"],
                "files_skipped": queue_stats["skipped_tasks"],
                "files_failed": queue_stats["failed_tasks"],
                "total_bytes_downloaded": total_bytes_downloaded,
            }
        )

    def get_progress_info(self) -> Dict[str, Any]:
        if not self.is_running:
            return {"status": "not_running"}

        queue_stats = self.queue.get_stats()
        worker_stats = self.worker_pool.get_stats()
        active_downloads = self.worker_pool.get_active_downloads()
        total_tasks = queue_stats["total_added"]
        completed_tasks = queue_stats["completed_tasks"]
        skipped_tasks = queue_stats["skipped_tasks"]
        failed_tasks = queue_stats["failed_tasks"]
        pending_tasks = queue_stats["pending_tasks"]
        terminal_tasks = completed_tasks + skipped_tasks + failed_tasks
        progress_percentage = 0
        if total_tasks > 0:
            progress_percentage = (terminal_tasks / total_tasks) * 100

        elapsed_time = (
            (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        )
        download_speed_mbps = 0
        if elapsed_time > 0:
            total_mb = worker_stats["total_bytes_downloaded"] / (1024 * 1024)
            download_speed_mbps = total_mb / elapsed_time * 60

        return {
            "status": "running",
            "progress_percentage": round(progress_percentage, 1),
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "skipped_tasks": skipped_tasks,
            "failed_tasks": failed_tasks,
            "terminal_tasks": terminal_tasks,
            "pending_tasks": pending_tasks,
            "queue_size": queue_stats["queue_size"],
            "active_workers": worker_stats["active_workers"],
            "total_workers": worker_stats["num_workers"],
            "active_downloads": active_downloads,
            "total_mb_downloaded": worker_stats["total_mb_downloaded"],
            "download_speed_mbpm": round(download_speed_mbps, 2),
            "elapsed_time_seconds": round(elapsed_time),
            "estimated_time_remaining": self._estimate_time_remaining(
                pending_tasks, terminal_tasks, elapsed_time
            ),
        }

    def _estimate_time_remaining(
        self, pending_tasks: int, completed_tasks: int, elapsed_time: float
    ) -> Optional[int]:
        if completed_tasks == 0 or elapsed_time == 0 or pending_tasks == 0:
            return None
        avg_time_per_task = elapsed_time / completed_tasks
        return int(pending_tasks * avg_time_per_task)

    def get_session_summary(self) -> Dict[str, Any]:
        self._update_session_stats()
        elapsed_time = (
            (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        )
        return {
            "session_duration_seconds": round(elapsed_time),
            "files_queued": self.session_stats["files_queued"],
            "files_completed": self.session_stats["files_completed"],
            "files_skipped": self.session_stats["files_skipped"],
            "files_failed": self.session_stats["files_failed"],
            "total_mb_downloaded": round(
                self.session_stats["total_bytes_downloaded"] / (1024 * 1024), 2
            ),
            "average_speed_mbpm": round(
                (self.session_stats["total_bytes_downloaded"] / (1024 * 1024))
                / (elapsed_time / 60),
                2,
            )
            if elapsed_time > 0
            else 0,
            "success_rate": round(
                (
                    (
                        self.session_stats["files_completed"]
                        + self.session_stats["files_skipped"]
                    )
                    / max(1, self.session_stats["files_queued"])
                )
                * 100,
                1,
            ),
        }


def create_download_coordinator(downloader, config_loader) -> DownloadCoordinator:
    return DownloadCoordinator(downloader, config_loader)


class DownloadMonitor:
    def __init__(self, coordinator: DownloadCoordinator, update_interval: float = 2.0):
        self.coordinator = coordinator
        self.update_interval = update_interval
        self.logger = get_logger()
        self.is_monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start_monitoring(self):
        if self.is_monitoring:
            return
        self.is_monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self.logger.info("Download monitoring started")

    async def stop_monitoring(self):
        if not self.is_monitoring:
            return
        self.is_monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self.logger.info("Download monitoring stopped")

    async def _monitor_loop(self):
        try:
            while self.is_monitoring:
                progress_info = self.coordinator.get_progress_info()
                if progress_info["status"] == "running":
                    self._display_progress(progress_info)
                await asyncio.sleep(self.update_interval)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.logger.error(f"Monitor loop error: {exc}")

    def _display_progress(self, progress_info: Dict[str, Any]):
        print("\r" + " " * 100 + "\r", end="")
        progress_bar = self._create_progress_bar(progress_info["progress_percentage"])
        print(
            f"\rProgress: {progress_bar} {progress_info['progress_percentage']:.1f}% "
            f"({progress_info['terminal_tasks']}/{progress_info['total_tasks']}) "
            f"| Done: {progress_info['completed_tasks']} "
            f"| Skipped: {progress_info['skipped_tasks']} "
            f"| Failed: {progress_info['failed_tasks']} "
            f"| Active: {progress_info['active_workers']}/{progress_info['total_workers']} workers "
            f"| Queue: {progress_info['queue_size']} "
            f"| Speed: {progress_info['download_speed_mbpm']:.1f} MB/min",
            end="",
        )

        if progress_info["active_downloads"]:
            print()
            for download in progress_info["active_downloads"]:
                filename = download["filename"]
                if len(filename) > 50:
                    filename = filename[:47] + "..."
                print(
                    f"  * {download['worker_id']}: {filename} ({download['file_size_mb']:.1f} MB)"
                )

        if progress_info["estimated_time_remaining"]:
            eta_minutes = progress_info["estimated_time_remaining"] // 60
            eta_seconds = progress_info["estimated_time_remaining"] % 60
            print(f" | ETA: {eta_minutes:02d}:{eta_seconds:02d}", end="")

    def _create_progress_bar(self, percentage: float, width: int = 20) -> str:
        filled = int(width * percentage / 100)
        return f"[{'#' * filled}{'-' * (width - filled)}]"

    def display_summary(self):
        summary = self.coordinator.get_session_summary()
        duration_minutes = summary["session_duration_seconds"] // 60
        duration_seconds = summary["session_duration_seconds"] % 60
        sep = "=" * 50
        summary_lines = [
            sep,
            "[SUMMARY] Download Session Complete",
            sep,
            f"Files queued:     {summary['files_queued']}",
            f"Files completed:  {summary['files_completed']}",
            f"Files skipped:    {summary['files_skipped']}",
            f"Files failed:     {summary['files_failed']}",
            f"Total downloaded: {summary['total_mb_downloaded']:.1f} MB",
            f"Duration:         {duration_minutes:02d}:{duration_seconds:02d}",
            f"Avg speed:        {summary['average_speed_mbpm']:.1f} MB/min",
            f"Success rate:     {summary['success_rate']:.1f}%",
            sep,
        ]
        emit_session_lines(summary_lines, logger=self.logger)


class ProgressDisplay:
    @staticmethod
    def show_progress_once(coordinator: DownloadCoordinator):
        progress_info = coordinator.get_progress_info()
        if progress_info["status"] != "running":
            emit_session_message("Download coordinator is not running")
            return

        sep = "-" * 40
        progress_lines = [
            sep,
            "[PROGRESS] Download Status",
            sep,
            f"  Progress:  {progress_info['progress_percentage']:.1f}% ({progress_info['terminal_tasks']}/{progress_info['total_tasks']})",
            f"  Done:      {progress_info['completed_tasks']}   Skipped: {progress_info['skipped_tasks']}   Failed: {progress_info['failed_tasks']}",
            f"  Workers:   {progress_info['active_workers']}/{progress_info['total_workers']} active",
            f"  Queue:     {progress_info['queue_size']} pending",
            f"  Speed:     {progress_info['download_speed_mbpm']:.1f} MB/min  Downloaded: {progress_info['total_mb_downloaded']:.1f} MB",
        ]

        if progress_info["active_downloads"]:
            progress_lines.append("  Active:")
            for download in progress_info["active_downloads"]:
                progress_lines.append(
                    f"    [{download['worker_id']}] {download['filename']} ({download['file_size_mb']:.1f} MB)"
                )

        if progress_info["estimated_time_remaining"]:
            eta_minutes = progress_info["estimated_time_remaining"] // 60
            eta_seconds = progress_info["estimated_time_remaining"] % 60
            progress_lines.append(f"  ETA:       {eta_minutes:02d}:{eta_seconds:02d}")

        progress_lines.append(sep)
        emit_session_lines(progress_lines, logger=get_logger())


def create_download_monitor(
    coordinator: DownloadCoordinator, update_interval: float = 2.0
) -> DownloadMonitor:
    return DownloadMonitor(coordinator, update_interval)
