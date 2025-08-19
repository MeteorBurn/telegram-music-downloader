import asyncio
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import heapq


@dataclass
class DownloadTask:
    """Задача на скачивание файла"""
    media_info: Dict[str, Any]
    file_info_str: str = ""
    priority: int = 0  # Чем меньше число, тем выше приоритет
    created_at: datetime = field(default_factory=datetime.now)
    attempts: int = 0
    max_attempts: int = 3
    
    def __lt__(self, other):
        """Для сортировки в priority queue"""
        return self.priority < other.priority


class DownloadQueue:
    """Очередь задач на скачивание с приоритетами"""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._queue = asyncio.PriorityQueue(maxsize=max_size)
        self._pending_tasks = {}  # task_id -> DownloadTask
        self._completed_tasks = set()
        self._failed_tasks = set()
        self.logger = logging.getLogger(__name__)
        
        # Статистика
        self._stats = {
            'total_added': 0,
            'total_completed': 0,
            'total_failed': 0,
            'current_size': 0
        }
    
    async def put(self, task: DownloadTask) -> bool:
        """Добавить задачу в очередь"""
        try:
            task_id = self._generate_task_id(task.media_info)
            
            # Проверяем, не добавлена ли уже эта задача
            if task_id in self._pending_tasks or task_id in self._completed_tasks:
                self.logger.debug(f"Task {task_id} already exists, skipping")
                return False
            
            # Устанавливаем приоритет на основе размера файла (меньшие файлы - выше приоритет)
            file_size_mb = task.media_info.get('file_size', 0) / (1024 * 1024)
            task.priority = int(file_size_mb)  # Меньшие файлы будут скачиваться первыми
            
            await self._queue.put(task)
            self._pending_tasks[task_id] = task
            self._stats['total_added'] += 1
            self._stats['current_size'] = self._queue.qsize()
            
            self.logger.debug(f"Added task {task_id} to queue (priority: {task.priority})")
            return True
            
        except asyncio.QueueFull:
            self.logger.warning("Download queue is full, cannot add more tasks")
            return False
        except Exception as e:
            self.logger.error(f"Error adding task to queue: {e}")
            return False
    
    async def get(self) -> Optional[DownloadTask]:
        """Получить задачу из очереди"""
        try:
            task = await self._queue.get()
            self._stats['current_size'] = self._queue.qsize()
            return task
        except Exception as e:
            self.logger.error(f"Error getting task from queue: {e}")
            return None
    
    def task_done(self, task: DownloadTask, success: bool = True):
        """Отметить задачу как выполненную"""
        task_id = self._generate_task_id(task.media_info)
        
        if task_id in self._pending_tasks:
            del self._pending_tasks[task_id]
        
        if success:
            self._completed_tasks.add(task_id)
            self._stats['total_completed'] += 1
            self.logger.debug(f"Task {task_id} completed successfully")
        else:
            self._failed_tasks.add(task_id)
            self._stats['total_failed'] += 1
            self.logger.debug(f"Task {task_id} failed")
        
        self._queue.task_done()
    
    async def retry_task(self, task: DownloadTask) -> bool:
        """Повторить задачу при ошибке"""
        task.attempts += 1
        
        if task.attempts >= task.max_attempts:
            self.logger.warning(f"Task exceeded max attempts ({task.max_attempts}), marking as failed")
            self.task_done(task, success=False)
            return False
        
        # Увеличиваем приоритет (делаем менее приоритетной) для повторных попыток
        task.priority += 1000
        
        success = await self.put(task)
        if success:
            self.logger.info(f"Retrying task (attempt {task.attempts}/{task.max_attempts})")
        
        return success
    
    def _generate_task_id(self, media_info: Dict[str, Any]) -> str:
        """Генерировать уникальный ID для задачи"""
        channel_id = media_info.get('channel_id', 'unknown')
        message_id = media_info.get('message_id', 0)
        return f"{channel_id}_{message_id}"
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику очереди"""
        return {
            **self._stats,
            'pending_tasks': len(self._pending_tasks),
            'completed_tasks': len(self._completed_tasks),
            'failed_tasks': len(self._failed_tasks),
            'queue_size': self._queue.qsize(),
            'is_empty': self._queue.empty(),
            'is_full': self._queue.full()
        }
    
    async def wait_empty(self):
        """Ждать пока очередь не опустеет"""
        await self._queue.join()
    
    def clear(self):
        """Очистить очередь"""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
        
        self._pending_tasks.clear()
        self._stats['current_size'] = 0
        self.logger.info("Download queue cleared")


class RateLimiter:
    """Rate limiter для соблюдения лимитов Telegram API"""
    
    def __init__(self, requests_per_second: float = 2.0, burst_size: int = 5):
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size
        self.tokens = burst_size
        self.last_update = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)
    
    async def acquire(self, worker_id: str = "unknown"):
        """Получить разрешение на выполнение запроса"""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            
            # Добавляем токены на основе прошедшего времени
            time_passed = now - self.last_update
            self.tokens = min(self.burst_size, self.tokens + time_passed * self.requests_per_second)
            self.last_update = now
            
            if self.tokens >= 1:
                self.tokens -= 1
                self.logger.debug(f"Rate limit acquired for worker {worker_id}, tokens left: {self.tokens:.2f}")
                return
            
            # Нужно подождать
            wait_time = (1 - self.tokens) / self.requests_per_second
            self.logger.debug(f"Rate limit hit for worker {worker_id}, waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)
            
            # После ожидания берем токен
            self.tokens = 0
            self.last_update = asyncio.get_event_loop().time()