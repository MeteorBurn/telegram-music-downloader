import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Any, Optional

from download_models import DownloadRequest
from logger import get_logger


TERMINAL_OUTCOMES = {"completed", "skipped", "failed"}


@dataclass
class DownloadTask:
    """Задача на скачивание файла"""

    request: DownloadRequest
    file_info_str: str = ""
    priority: int = 0  # Чем меньше число, тем выше приоритет
    created_at: datetime = field(default_factory=datetime.now)
    attempts: int = 0
    max_attempts: int = 3
    outcome_callback: Optional[
        Callable[[str, "DownloadTask", Optional[Dict[str, Any]]], None]
    ] = None

    def __lt__(self, other):
        """Для сортировки в priority queue"""
        return self.priority < other.priority

    @property
    def media_info(self) -> Dict[str, Any]:
        return self.request.to_media_info()


class DownloadQueue:
    """Очередь задач на скачивание с приоритетами"""

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._queue = asyncio.PriorityQueue(maxsize=max_size)
        self._pending_tasks = {}  # task_id -> DownloadTask
        self._completed_tasks = set()
        self._skipped_tasks = set()
        self._failed_tasks = set()
        self.logger = get_logger()

        # Статистика
        self._stats = {
            "total_added": 0,
            "total_completed": 0,
            "total_skipped": 0,
            "total_failed": 0,
            "total_retried": 0,
            "current_size": 0,
        }

    async def put(self, task: DownloadTask, is_retry: bool = False) -> bool:
        """Добавить задачу в очередь"""
        try:
            task_id = self._generate_task_id(task.media_info)

            # Проверяем, не добавлена ли уже эта задача
            if not is_retry and (
                task_id in self._pending_tasks
                or task_id in self._completed_tasks
                or task_id in self._skipped_tasks
            ):
                self.logger.debug(f"Task {task_id} already exists, skipping")
                return False

            # Устанавливаем приоритет на основе ID сообщения (порядок добавления в очередь)
            # Файлы будут скачиваться в том порядке, в котором они были добавлены
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
        except Exception as e:
            self.logger.error(f"Error adding task to queue: {e}")
            return False

    async def get(self, timeout: Optional[float] = None) -> Optional[DownloadTask]:
        """Получить задачу из очереди"""
        try:
            if timeout is None:
                task = await self._queue.get()
            else:
                task = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            self._stats["current_size"] = self._queue.qsize()
            return task
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            self.logger.error(f"Error getting task from queue: {e}")
            return None

    def task_done(
        self,
        task: DownloadTask,
        outcome: str = "completed",
        result: Optional[Dict[str, Any]] = None,
    ):
        """Отметить задачу как выполненную"""
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
        else:
            self._failed_tasks.add(task_id)
            self._stats["total_failed"] += 1
            self.logger.debug(f"Task {task_id} failed")

        self._notify_task_outcome(task, outcome, result)
        self._queue.task_done()
        self._stats["current_size"] = self._queue.qsize()

    async def retry_task(self, task: DownloadTask) -> bool:
        """Повторить задачу при ошибке"""
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

        # Увеличиваем приоритет (делаем менее приоритетной) для повторных попыток
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

        self.logger.warning("Failed to requeue task for retry, marking as failed")
        task_id = self._generate_task_id(task.media_info)
        if task_id in self._pending_tasks:
            del self._pending_tasks[task_id]
        self._failed_tasks.add(task_id)
        self._stats["total_failed"] += 1
        self._notify_task_outcome(
            task,
            "failed",
            {"status": "failed", "reason": "Could not requeue task for retry"},
        )
        self._queue.task_done()
        self._stats["current_size"] = self._queue.qsize()

        return False

    def _generate_task_id(self, media_info: Dict[str, Any]) -> str:
        """Генерировать уникальный ID для задачи"""
        channel_id = media_info.get("channel_id", "unknown")
        message_id = media_info.get("message_id", 0)
        return f"{channel_id}_{message_id}"

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику очереди"""
        return {
            **self._stats,
            "pending_tasks": len(self._pending_tasks),
            "completed_tasks": len(self._completed_tasks),
            "skipped_tasks": len(self._skipped_tasks),
            "failed_tasks": len(self._failed_tasks),
            "queue_size": self._queue.qsize(),
            "is_empty": self._queue.empty(),
            "is_full": self._queue.full(),
        }

    async def wait_empty(self):
        """Ждать пока очередь не опустеет"""
        await self._queue.join()

    def clear(self, outcome: Optional[str] = None):
        """Очистить очередь"""
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
        """Получить текущий размер очереди"""
        return self._queue.qsize()

    def empty(self) -> bool:
        """Проверить, пуста ли очередь"""
        return self._queue.empty()

    def full(self) -> bool:
        """Проверить, заполнена ли очередь"""
        return self._queue.full()

    def _notify_task_outcome(
        self, task: DownloadTask, outcome: str, result: Optional[Dict[str, Any]]
    ) -> None:
        """Вызвать callback задачи при терминальном исходе"""
        if not task.outcome_callback:
            return

        try:
            task.outcome_callback(outcome, task, result)
        except Exception as e:
            self.logger.error(f"Task outcome callback failed: {e}")


class RateLimiter:
    """Rate limiter для соблюдения лимитов Telegram API"""

    def __init__(self, requests_per_second: float = 2.0, burst_size: int = 5):
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size
        self.tokens = burst_size
        self.last_update = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()
        self.logger = get_logger()

    async def acquire(self, worker_id: str = "unknown"):
        """Получить разрешение на выполнение запроса"""
        async with self._lock:
            now = asyncio.get_event_loop().time()

            # Добавляем токены на основе прошедшего времени
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

            # Нужно подождать
            wait_time = (1 - self.tokens) / self.requests_per_second
            self.logger.debug(
                f"Rate limit hit for worker {worker_id}, waiting {wait_time:.2f}s"
            )
            await asyncio.sleep(wait_time)

            # После ожидания берем токен
            self.tokens = 0
            self.last_update = asyncio.get_event_loop().time()
