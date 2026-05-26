"""Shared logging bootstrap for the application."""

from __future__ import annotations

import logging
from pathlib import Path

CONSOLE_HANDLER_NAME = "page_automation_console"
FILE_HANDLER_NAME = "page_automation_file"


class JobContextFilter(logging.Filter):
    """Ensure every log record has a job_id field."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "job_id"):
            record.job_id = "-"
        return True


class JobLoggerAdapter(logging.LoggerAdapter):
    """Bind a default job_id to structured log records."""

    def process(self, msg: str, kwargs: dict[str, object]) -> tuple[str, dict[str, object]]:
        extra = dict(kwargs.get("extra", {}))
        extra.setdefault("job_id", self.extra.get("job_id", "-"))
        kwargs["extra"] = extra
        return msg, kwargs


def configure_logging(log_level: str, log_dir: Path) -> logging.Logger:
    """Configure console and file logging for the application."""
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | job_id=%(job_id)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    context_filter = JobContextFilter()

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root_logger.handlers = [
        handler
        for handler in root_logger.handlers
        if handler.get_name() not in {CONSOLE_HANDLER_NAME, FILE_HANDLER_NAME}
    ]

    if not any(isinstance(current_filter, JobContextFilter) for current_filter in root_logger.filters):
        root_logger.addFilter(context_filter)

    console_handler = logging.StreamHandler()
    console_handler.set_name(CONSOLE_HANDLER_NAME)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(context_filter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.set_name(FILE_HANDLER_NAME)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(context_filter)
    root_logger.addHandler(file_handler)

    return logging.getLogger("page_automation")


def get_job_logger(name: str, job_id: str = "-") -> JobLoggerAdapter:
    """Return a logger adapter that always includes the provided job_id."""
    return JobLoggerAdapter(logging.getLogger(name), {"job_id": job_id})
