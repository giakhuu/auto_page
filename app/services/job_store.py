"""Filesystem-backed persistence for final job outcome records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.models.job import Job


class JobStore:
    """Persist MVP job snapshots to project-controlled JSON files."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def records_dir(self) -> Path:
        """Directory used for persisted job records."""
        return self.settings.download_dir.parent / "jobs"

    def ensure_records_dir(self) -> Path:
        """Create the job-record directory if needed."""
        self.records_dir.mkdir(parents=True, exist_ok=True)
        return self.records_dir

    def get_record_path(self, job_id: str) -> Path:
        """Return the deterministic record path for one job ID."""
        return self.records_dir / f"{job_id}.json"

    @staticmethod
    def _stringify_path(path: Path | None) -> str | None:
        return str(path) if path is not None else None

    @staticmethod
    def _extract_screenshot_path(job: Job) -> str | None:
        if not job.error_message or "Screenshot:" not in job.error_message:
            return None
        return job.error_message.rsplit("Screenshot:", maxsplit=1)[1].strip()

    def build_record(self, job: Job) -> dict[str, Any]:
        """Convert the shared job model into a JSON-safe persisted record."""
        screenshot_path = self._extract_screenshot_path(job)
        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "source_url": job.source_url,
            "caption": job.caption,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "completed_at": job.updated_at.isoformat() if job.is_terminal else None,
            "publish_mode": job.publish_mode,
            "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at is not None else None,
            "download_path": self._stringify_path(job.download_path),
            "download_filename": job.download_filename,
            "download_duration_seconds": job.download_duration_seconds,
            "download_file_size_bytes": job.download_file_size_bytes,
            "facebook_post_url": job.facebook_post_url,
            "auto_schedule_slot_index": job.auto_schedule_slot_index,
            "error_message": job.error_message,
            "artifacts": {
                "download_path": self._stringify_path(job.download_path),
                "publish_failure_screenshot_path": screenshot_path,
            },
        }

    def save(self, job: Job) -> Path:
        """Persist one job snapshot to a deterministic JSON path."""
        records_dir = self.ensure_records_dir()
        record_path = records_dir / f"{job.job_id}.json"
        record_path.write_text(json.dumps(self.build_record(job), indent=2), encoding="utf-8")
        job.persisted_record_path = record_path
        return record_path

    def load(self, job_id: str) -> dict[str, Any]:
        """Load one persisted job snapshot back from disk."""
        record_path = self.get_record_path(job_id)
        return json.loads(record_path.read_text(encoding="utf-8"))
