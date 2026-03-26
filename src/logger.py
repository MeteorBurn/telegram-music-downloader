import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable, Optional


PROJECT_LOGGER_NAME = "telegram_music_downloader"
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
ANSI_RED = "\x1b[31m"
ANSI_RESET = "\x1b[0m"


class SafeConsoleHandler(logging.StreamHandler):
    """Console handler that degrades unsupported characters safely."""

    def emit(self, record):
        try:
            message = self.format(record)
            _write_safe_line(message, stream=self.stream)
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


class SafeRotatingFileHandler(RotatingFileHandler):
    """Rotating file handler that recreates missing parent directories."""

    def emit(self, record):
        log_path = Path(self.baseFilename)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        super().emit(record)


def get_logger() -> logging.Logger:
    return logging.getLogger(PROJECT_LOGGER_NAME)


def setup_logging(config_loader) -> logging.Logger:
    logger = get_logger()
    log_level = _resolve_log_level(config_loader.get_log_level())
    log_file = config_loader.get_log_file()
    console_enabled = config_loader.is_console_logging_enabled()
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    _clear_handlers(logger)
    logger.setLevel(log_level)
    logger.propagate = False

    if console_enabled:
        console_handler = SafeConsoleHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = SafeRotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logging.getLogger().setLevel(logging.WARNING)
    logger.info(
        "Centralized logger initialized - Level: %s, File: %s, Console: %s",
        logging.getLevelName(log_level),
        log_file,
        console_enabled,
    )
    return logger


def emit_session_message(
    message: str,
    level: str = "info",
    logger: Optional[logging.Logger] = None,
    console: bool = True,
) -> None:
    target_logger = logger or get_logger()
    log_method = getattr(target_logger, level.lower(), target_logger.info)
    log_method(message)

    if console and not has_console_handler(target_logger):
        _write_safe_line(message)


def emit_session_lines(
    lines: Iterable[str],
    level: str = "info",
    logger: Optional[logging.Logger] = None,
    console: bool = True,
) -> None:
    for line in lines:
        if not line.strip():
            # Empty lines go to console only — do not create empty log records
            if console and not has_console_handler(logger or get_logger()):
                _write_safe_line("")
            continue
        emit_session_message(line, level=level, logger=logger, console=console)


def log_exception(
    message: str,
    logger: Optional[logging.Logger] = None,
    console: bool = True,
) -> None:
    target_logger = logger or get_logger()
    target_logger.exception(message)

    if console and not has_console_handler(target_logger):
        exc_lines = traceback.format_exc().rstrip().splitlines()
        for line in exc_lines:
            _write_safe_line(line)


def has_console_handler(logger: Optional[logging.Logger] = None) -> bool:
    target_logger = logger or get_logger()
    return any(
        isinstance(handler, SafeConsoleHandler) for handler in target_logger.handlers
    )


def _clear_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        try:
            handler.flush()
            handler.close()
        except Exception:
            pass
        logger.removeHandler(handler)


def _resolve_log_level(level: str) -> int:
    return getattr(logging, str(level).upper(), logging.INFO)


def _write_safe_line(message: str, stream=None) -> None:
    target_stream = stream or sys.stdout
    encoding = getattr(target_stream, "encoding", None) or "utf-8"
    safe_message = message.encode(encoding, errors="replace").decode(
        encoding, errors="replace"
    )
    target_stream.write(safe_message + "\n")
    target_stream.flush()


def format_critical_message(message: str) -> str:
    return f"{ANSI_RED}{message}{ANSI_RESET}"
