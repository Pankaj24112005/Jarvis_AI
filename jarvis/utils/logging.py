"""Structured and secure logging for JARVIS using Rich."""

import logging
import os
import re
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler

_console = Console()

# Pattern to detect and redact potential Google Gemini API keys (starts with AIzaSy...)
_API_KEY_PATTERN = re.compile(r"AIzaSy[A-Za-z0-9_\-]{33}")


class SensitiveDataFilter(logging.Filter):
    """Logging filter that redacts API keys and sensitive tokens."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _API_KEY_PATTERN.sub("AIzaSy[REDACTED_API_KEY]", record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (_API_KEY_PATTERN.sub("AIzaSy[REDACTED_API_KEY]", str(v)) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    (_API_KEY_PATTERN.sub("AIzaSy[REDACTED_API_KEY]", str(v)) if isinstance(v, str) else v)
                    for v in record.args
                )
        return True


def setup_logger(name: str = "jarvis", log_level: str = "INFO", log_to_file: bool = True) -> logging.Logger:
    """Set up and return a configured logger with console and optional file output."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Avoid duplicate handlers if already configured
    if logger.handlers:
        return logger

    # Console handler with Rich formatting
    console_handler = RichHandler(
        console=_console,
        rich_tracebacks=True,
        show_time=True,
        show_path=False,
    )
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console_handler.addFilter(SensitiveDataFilter())
    logger.addHandler(console_handler)

    if log_to_file:
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "jarvis.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(SensitiveDataFilter())
        logger.addHandler(file_handler)

    return logger


logger = setup_logger()
