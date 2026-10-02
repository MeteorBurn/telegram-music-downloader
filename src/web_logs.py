import asyncio
import logging
import re
import threading
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Tuple

from logger import get_logger


ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SUBSCRIBER_QUEUE_SIZE = 1000


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_PATTERN.sub("", text)


class LogBuffer(logging.Handler):
    """In-memory ring buffer of log entries with live fan-out to asyncio queues."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__(level=logging.NOTSET)
        self._entries: deque = deque(maxlen=capacity)
        self._next_id = 1
        self._buffer_lock = threading.Lock()
        self._subscribers: List[Tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = []
        self._exception_formatter = logging.Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message = (
                    f"{message}\n"
                    f"{self._exception_formatter.formatException(record.exc_info)}"
                )
            timestamp = datetime.fromtimestamp(record.created).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
            with self._buffer_lock:
                entry = {
                    "id": self._next_id,
                    "ts": timestamp,
                    "level": record.levelname,
                    "message": strip_ansi(message),
                }
                self._next_id += 1
                self._entries.append(entry)
                subscribers = list(self._subscribers)

            for queue, loop in subscribers:
                try:
                    loop.call_soon_threadsafe(self._deliver, queue, dict(entry))
                except RuntimeError:
                    # The subscriber's loop is closed; it can no longer receive entries.
                    self.unsubscribe(queue)
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)

    @staticmethod
    def _deliver(queue: asyncio.Queue, entry: Dict[str, Any]) -> None:
        try:
            queue.put_nowait(entry)
        except asyncio.QueueFull:
            pass

    def snapshot(self, limit: int = 500, after_id: int = 0) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        with self._buffer_lock:
            entries = [dict(entry) for entry in self._entries if entry["id"] > after_id]
        return entries[-limit:]

    def subscribe(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        with self._buffer_lock:
            self._subscribers.append((queue, loop))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._buffer_lock:
            self._subscribers = [
                subscriber for subscriber in self._subscribers if subscriber[0] is not queue
            ]


def attach_log_buffer(buffer: LogBuffer) -> None:
    logger = get_logger()
    if buffer not in logger.handlers:
        logger.addHandler(buffer)
