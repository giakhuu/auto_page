"""Shared job creation and lookup service."""

from __future__ import annotations

from datetime import datetime

from app.models.job import Job


class JobManager:
    """Manage queued jobs for the local MVP runtime."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._active_job_id: str | None = None

    def create_job(
        self,
        source_url: str,
        caption: str = "",
        publish_mode: str = "publish",
        scheduled_at: datetime | None = None,
        auto_schedule_slot_index: int | None = None,
    ) -> Job:
        """Create and store a new queued job."""
        job = Job(
            source_url=source_url,
            caption=caption,
            publish_mode=publish_mode,
            scheduled_at=scheduled_at,
            auto_schedule_slot_index=auto_schedule_slot_index,
        )
        self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> Job | None:
        """Return a queued job by ID if it exists."""
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        """Return jobs in creation order."""
        return list(self._jobs.values())

    @property
    def active_job_id(self) -> str | None:
        """Return the currently active job ID when orchestration is running."""
        return self._active_job_id

    def has_active_job(self) -> bool:
        """Return whether the runtime is currently processing a job."""
        return self._active_job_id is not None

    def set_active_job(self, job_id: str) -> None:
        """Mark one job as active for the single-job MVP runtime."""
        self._active_job_id = job_id

    def clear_active_job(self, job_id: str | None = None) -> None:
        """Clear the active job marker once orchestration finishes."""
        if job_id is None or self._active_job_id == job_id:
            self._active_job_id = None
