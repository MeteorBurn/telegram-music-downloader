import asyncio
from typing import Dict, Any, Optional

from download_coordinator import DownloadCoordinator
from logger import emit_session_lines, emit_session_message, get_logger


class DownloadMonitor:
    """Мониторинг процесса скачивания в реальном времени"""

    def __init__(self, coordinator: DownloadCoordinator, update_interval: float = 2.0):
        self.coordinator = coordinator
        self.update_interval = update_interval
        self.logger = get_logger()
        self.is_monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start_monitoring(self):
        """Запустить мониторинг"""
        if self.is_monitoring:
            return

        self.is_monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self.logger.info("Download monitoring started")

    async def stop_monitoring(self):
        """Остановить мониторинг"""
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
        """Основной цикл мониторинга"""
        try:
            while self.is_monitoring:
                progress_info = self.coordinator.get_progress_info()

                if progress_info["status"] == "running":
                    self._display_progress(progress_info)

                await asyncio.sleep(self.update_interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Monitor loop error: {e}")

    def _display_progress(self, progress_info: Dict[str, Any]):
        """Отобразить прогресс скачивания"""
        # Очищаем предыдущую строку (для обновления в реальном времени)
        print("\r" + " " * 100 + "\r", end="")

        # Основная информация о прогрессе
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

        # Показываем активные скачивания
        if progress_info["active_downloads"]:
            print()  # Новая строка
            for download in progress_info["active_downloads"]:
                filename = download["filename"]
                if len(filename) > 50:
                    filename = filename[:47] + "..."
                print(
                    f"  * {download['worker_id']}: {filename} ({download['file_size_mb']:.1f} MB)"
                )

        # ETA
        if progress_info["estimated_time_remaining"]:
            eta_minutes = progress_info["estimated_time_remaining"] // 60
            eta_seconds = progress_info["estimated_time_remaining"] % 60
            print(f" | ETA: {eta_minutes:02d}:{eta_seconds:02d}", end="")

    def _create_progress_bar(self, percentage: float, width: int = 20) -> str:
        """Создать текстовый прогресс-бар"""
        filled = int(width * percentage / 100)
        bar = "#" * filled + "-" * (width - filled)
        return f"[{bar}]"

    def display_summary(self):
        """Показать итоговую статистику"""
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
    """Простой класс для отображения прогресса без фонового мониторинга"""

    @staticmethod
    def show_progress_once(coordinator: DownloadCoordinator):
        """Показать текущий прогресс один раз"""
        progress_info = coordinator.get_progress_info()

        if progress_info["status"] != "running":
            emit_session_message("Download coordinator is not running")
            return

        sep = "-" * 40
        progress_lines = [
            sep,
            "[PROGRESS] Download Status",
            sep,
            f"  Progress:  {progress_info['progress_percentage']:.1f}% "
            f"({progress_info['terminal_tasks']}/{progress_info['total_tasks']})",
            f"  Done:      {progress_info['completed_tasks']}   "
            f"Skipped: {progress_info['skipped_tasks']}   "
            f"Failed: {progress_info['failed_tasks']}",
            f"  Workers:   {progress_info['active_workers']}/{progress_info['total_workers']} active",
            f"  Queue:     {progress_info['queue_size']} pending",
            f"  Speed:     {progress_info['download_speed_mbpm']:.1f} MB/min  "
            f"Downloaded: {progress_info['total_mb_downloaded']:.1f} MB",
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
    """Создать монитор скачивания"""
    return DownloadMonitor(coordinator, update_interval)
