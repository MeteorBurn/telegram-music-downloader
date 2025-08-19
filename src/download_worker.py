import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from download_queue import DownloadQueue, DownloadTask, RateLimiter


class DownloadWorker:
    """Воркер для скачивания файлов"""
    
    def __init__(self, worker_id: str, downloader, queue: DownloadQueue, 
                 rate_limiter: RateLimiter):
        self.worker_id = worker_id
        self.downloader = downloader
        self.queue = queue
        self.rate_limiter = rate_limiter
        self.logger = logging.getLogger(f"worker_{worker_id}")
        
        # Состояние воркера
        self.is_running = False
        self.current_task: Optional[DownloadTask] = None
        self.stats = {
            'tasks_completed': 0,
            'tasks_failed': 0,
            'bytes_downloaded': 0,
            'start_time': None,
            'last_activity': None
        }
    
    async def start(self):
        """Запустить воркер"""
        self.is_running = True
        self.stats['start_time'] = datetime.now()
        self.logger.info(f"Worker {self.worker_id} started")
        
        try:
            while self.is_running:
                await self._process_next_task()
        except asyncio.CancelledError:
            self.logger.info(f"Worker {self.worker_id} cancelled")
        except Exception as e:
            self.logger.error(f"Worker {self.worker_id} crashed: {e}")
        finally:
            self.logger.info(f"Worker {self.worker_id} stopped")
    
    async def stop(self):
        """Остановить воркер"""
        self.is_running = False
        if self.current_task:
            self.logger.info(f"Worker {self.worker_id} stopping, current task will be completed")
    
    async def _process_next_task(self):
        """Обработать следующую задачу из очереди"""
        try:
            # Получаем задачу из очереди
            task = await self.queue.get()
            if not task:
                await asyncio.sleep(0.1)  # Небольшая пауза если очередь пуста
                return
            
            self.current_task = task
            self.stats['last_activity'] = datetime.now()
            
            # Применяем rate limiting
            await self.rate_limiter.acquire(self.worker_id)
            
            # Выполняем скачивание
            success = await self._download_file(task)
            
            # Обновляем статистику и очередь
            if success:
                self.stats['tasks_completed'] += 1
                self.queue.task_done(task, success=True)
                self.logger.info(f"✓ Worker {self.worker_id} completed: {task.media_info['filename']}")
            else:
                # Пытаемся повторить задачу
                retry_success = await self.queue.retry_task(task)
                if not retry_success:
                    self.stats['tasks_failed'] += 1
                    self.logger.warning(f"✗ Worker {self.worker_id} failed: {task.media_info['filename']}")
            
        except Exception as e:
            self.logger.error(f"Worker {self.worker_id} error processing task: {e}")
            if self.current_task:
                self.queue.task_done(self.current_task, success=False)
                self.stats['tasks_failed'] += 1
        finally:
            self.current_task = None
    
    async def _download_file(self, task: DownloadTask) -> bool:
        """Скачать файл"""
        try:
            self.logger.info(f"→ Worker {self.worker_id} downloading: {task.media_info['filename']} {task.file_info_str}")
            
            # Используем существующий downloader
            result = await self.downloader.download_media_file(task.media_info, task.file_info_str)
            
            if result['status'] == 'success':
                # Обновляем статистику
                file_size = task.media_info.get('file_size', 0)
                self.stats['bytes_downloaded'] += file_size
                return True
            elif result['status'] == 'skipped':
                # Пропущенные файлы считаем успешными
                return True
            else:
                # Ошибка скачивания
                return False
                
        except Exception as e:
            self.logger.error(f"Worker {self.worker_id} download error: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику воркера"""
        stats = self.stats.copy()
        stats.update({
            'worker_id': self.worker_id,
            'is_running': self.is_running,
            'current_task': self.current_task.media_info['filename'] if self.current_task else None,
            'uptime_seconds': (datetime.now() - self.stats['start_time']).total_seconds() if self.stats['start_time'] else 0
        })
        return stats


class WorkerPool:
    """Управление пулом воркеров"""
    
    def __init__(self, downloader, queue: DownloadQueue, rate_limiter: RateLimiter, 
                 num_workers: int = 3):
        self.downloader = downloader
        self.queue = queue
        self.rate_limiter = rate_limiter
        self.num_workers = num_workers
        self.workers: Dict[str, DownloadWorker] = {}
        self.worker_tasks: Dict[str, asyncio.Task] = {}
        self.logger = logging.getLogger(__name__)
    
    async def start(self):
        """Запустить все воркеры"""
        self.logger.info(f"Starting worker pool with {self.num_workers} workers")
        
        for i in range(self.num_workers):
            worker_id = f"worker_{i+1}"
            worker = DownloadWorker(worker_id, self.downloader, self.queue, self.rate_limiter)
            self.workers[worker_id] = worker
            
            # Запускаем воркер в отдельной задаче
            task = asyncio.create_task(worker.start())
            self.worker_tasks[worker_id] = task
        
        self.logger.info(f"All {self.num_workers} workers started")
    
    async def stop(self):
        """Остановить все воркеры"""
        self.logger.info("Stopping worker pool...")
        
        # Сначала просим воркеры остановиться
        for worker in self.workers.values():
            await worker.stop()
        
        # Ждем завершения всех задач
        if self.worker_tasks:
            await asyncio.gather(*self.worker_tasks.values(), return_exceptions=True)
        
        self.workers.clear()
        self.worker_tasks.clear()
        self.logger.info("Worker pool stopped")
    
    async def wait_completion(self):
        """Ждать завершения всех задач в очереди"""
        await self.queue.wait_empty()
        self.logger.info("All download tasks completed")
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить общую статистику пула воркеров"""
        worker_stats = [worker.get_stats() for worker in self.workers.values()]
        
        total_completed = sum(stats['tasks_completed'] for stats in worker_stats)
        total_failed = sum(stats['tasks_failed'] for stats in worker_stats)
        total_bytes = sum(stats['bytes_downloaded'] for stats in worker_stats)
        
        return {
            'num_workers': self.num_workers,
            'active_workers': sum(1 for stats in worker_stats if stats['is_running']),
            'total_completed': total_completed,
            'total_failed': total_failed,
            'total_bytes_downloaded': total_bytes,
            'total_mb_downloaded': round(total_bytes / (1024 * 1024), 2),
            'workers': worker_stats
        }
    
    def get_active_downloads(self) -> list:
        """Получить список активных скачиваний"""
        active = []
        for worker in self.workers.values():
            if worker.current_task:
                active.append({
                    'worker_id': worker.worker_id,
                    'filename': worker.current_task.media_info['filename'],
                    'file_size_mb': round(worker.current_task.media_info.get('file_size', 0) / (1024 * 1024), 2)
                })
        return active