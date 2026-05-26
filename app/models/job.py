"""Shared job model and lifecycle values."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import uuid4


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class JobStatus(StrEnum):
    """Lifecycle states shared across job-processing modules."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    SCHEDULED = "scheduled"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass(slots=True)
class Job:
    """Represents a single automation job and its current state."""

    source_url: str
    caption: str = ""
    job_id: str = field(default_factory=lambda: uuid4().hex)
    status: JobStatus = JobStatus.QUEUED
    download_path: Path | None = None
    download_filename: str | None = None
    download_duration_seconds: float | None = None
    download_file_size_bytes: int | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(init=False)
    error_message: str | None = None
    facebook_post_url: str | None = None
    persisted_record_path: Path | None = None
    publish_mode: str = "publish"
    scheduled_at: datetime | None = None
    auto_schedule_slot_index: int | None = None

    def __post_init__(self) -> None:
        """Keep the initial timestamps aligned until the first mutation."""
        self.updated_at = self.created_at

    def set_status(self, status: JobStatus, error_message: str | None = None) -> None:
        """Update job state while tracking the latest timestamp."""
        self.status = status
        self.error_message = error_message
        self.updated_at = utc_now()

    @property
    def is_terminal(self) -> bool:
        """Return whether the job already reached a terminal state."""
        return self.status in {JobStatus.PUBLISHED, JobStatus.SCHEDULED, JobStatus.FAILED}
