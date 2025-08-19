import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from download_queue import DownloadQueue, DownloadTask, RateLimiter
from download_worker import WorkerPool


class DownloadCoordinator:
    """Координирует процесс многопоточного скачивания"""
    
    def __init__(self, downloader, config_loader):
        self.downloader = downloader
        self.config = config_loader
        self.logger = logging.getLogger(__name__)
        
        # Настройки из конфигурации
        self.concurrent_downloads = self.config.get_concurrent_downloads()
        self.max_queue_size = self.config.get_max_queue_size()
        self.requests_per_second = self.config.get_requests_per_second()
        self.burst_size = self.config.get_burst_size()
        
        # Компоненты системы
        self.queue = DownloadQueue(max_size=self.max_queue_size)
        self.rate_limiter = RateLimiter(
            requests_per_second=self.requests_per_second,
            burst_size=self.burst_size
        )
        self.worker_pool = WorkerPool(
            downloader=self.downloader,
            queue=self.queue,
            rate_limiter=self.rate_limiter,
            num_workers=self.concurrent_downloads
        )
        
        # Состояние координатора
        self.is_running = False
        self.start_time: Optional[datetime] = None
        self.session_stats = {
            'files_queued': 0,
            'files_completed': 0,
            'files_failed': 0,
            'files_skipped': 0,
            'total_bytes_downloaded': 0
        }
    
    async def start(self):
        """Запустить координатор и пул воркеров"""
        if self.is_running:
            self.logger.warning("Coordinator is already running")
            return
        
        self.is_running = True
        self.start_time = datetime.now()
        
        self.logger.info(f"Starting download coordinator with {self.concurrent_downloads} workers")
        self.logger.info(f"Rate limit: {self.requests_per_second} req/sec, burst: {self.burst_size}")
        self.logger.info(f"Queue size: {self.max_queue_size}")
        
        # Запускаем пул воркеров
        await self.worker_pool.start()
        
        self.logger.info("Download coordinator started successfully")
    
    async def stop(self):
        """Остановить координатор"""
        if not self.is_running:
            return
        
        self.logger.info("Stopping download coordinator...")
        self.is_running = False
        
        # Останавливаем воркеры
        await self.worker_pool.stop()
        
        # Очищаем очередь
        self.queue.clear()
        
        self.logger.info("Download coordinator stopped")
    
    async def add_download_task(self, media_info: Dict[str, Any], file_info_str: str = "") -> bool:
        """Добавить задачу на скачивание"""
        if not self.is_running:
            self.logger.error("Coordinator is not running, cannot add task")
            return False
        
        task = DownloadTask(
            media_info=media_info,
            file_info_str=file_info_str
        )
        
        success = await self.queue.put(task)
        if success:
            self.session_stats['files_queued'] += 1
            self.logger.debug(f"Added download task: {media_info['filename']}")
        else:
            self.logger.warning(f"Failed to add download task: {media_info['filename']}")
        
        return success
    
    async def wait_completion(self):
        """Ждать завершения всех задач"""
        if not self.is_running:
            self.logger.warning("Coordinator is not running")
            return
        
        self.logger.info("Waiting for all downloads to complete...")
        await self.worker_pool.wait_completion()
        self.logger.info("All downloads completed")
        
        # Обновляем финальную статистику
        self._update_session_stats()
    
    def _update_session_stats(self):
        """Обновить статистику сессии"""
        queue_stats = self.queue.get_stats()
        worker_stats = self.worker_pool.get_stats()
        
        self.session_stats.update({
            'files_completed': queue_stats['completed_tasks'],
            'files_failed': queue_stats['failed_tasks'],
            'total_bytes_downloaded': worker_stats['total_bytes_downloaded']
        })
    
    def get_progress_info(self) -> Dict[str, Any]:
        """Получить информацию о прогрессе"""
        if not self.is_running:
            return {'status': 'not_running'}
        
        queue_stats = self.queue.get_stats()
        worker_stats = self.worker_pool.get_stats()
        active_downloads = self.worker_pool.get_active_downloads()
        
        # Вычисляем прогресс
        total_tasks = queue_stats['total_added']
        completed_tasks = queue_stats['completed_tasks']
        failed_tasks = queue_stats['failed_tasks']
        pending_tasks = queue_stats['pending_tasks']
        
        progress_percentage = 0
        if total_tasks > 0:
            progress_percentage = ((completed_tasks + failed_tasks) / total_tasks) * 100
        
        # Вычисляем скорость
        elapsed_time = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        download_speed_mbps = 0
        if elapsed_time > 0:
            total_mb = worker_stats['total_bytes_downloaded'] / (1024 * 1024)
            download_speed_mbps = total_mb / elapsed_time * 60  # MB per minute
        
        return {
            'status': 'running',
            'progress_percentage': round(progress_percentage, 1),
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'failed_tasks': failed_tasks,
            'pending_tasks': pending_tasks,
            'queue_size': queue_stats['queue_size'],
            'active_workers': worker_stats['active_workers'],
            'total_workers': worker_stats['num_workers'],
            'active_downloads': active_downloads,
            'total_mb_downloaded': worker_stats['total_mb_downloaded'],
            'download_speed_mbpm': round(download_speed_mbps, 2),
            'elapsed_time_seconds': round(elapsed_time),
            'estimated_time_remaining': self._estimate_time_remaining(
                pending_tasks, completed_tasks, elapsed_time
            )
        }
    
    def _estimate_time_remaining(self, pending_tasks: int, completed_tasks: int, 
                               elapsed_time: float) -> Optional[int]:
        """Оценить оставшееся время"""
        if completed_tasks == 0 or elapsed_time == 0 or pending_tasks == 0:
            return None
        
        avg_time_per_task = elapsed_time / completed_tasks
        estimated_seconds = pending_tasks * avg_time_per_task
        
        return int(estimated_seconds)
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Получить итоговую статистику сессии"""
        self._update_session_stats()
        
        elapsed_time = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        
        return {
            'session_duration_seconds': round(elapsed_time),
            'files_queued': self.session_stats['files_queued'],
            'files_completed': self.session_stats['files_completed'],
            'files_failed': self.session_stats['files_failed'],
            'total_mb_downloaded': round(self.session_stats['total_bytes_downloaded'] / (1024 * 1024), 2),
            'average_speed_mbpm': round(
                (self.session_stats['total_bytes_downloaded'] / (1024 * 1024)) / (elapsed_time / 60), 2
            ) if elapsed_time > 0 else 0,
            'success_rate': round(
                (self.session_stats['files_completed'] / max(1, self.session_stats['files_queued'])) * 100, 1
            )
        }


def create_download_coordinator(downloader, config_loader) -> DownloadCoordinator:
    """Создать координатор скачивания"""
    return DownloadCoordinator(downloader, config_loader)