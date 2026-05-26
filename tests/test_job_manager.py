from app.models.job import JobStatus
from app.services.job_manager import JobManager


def test_create_job_returns_queued_job_with_stored_state() -> None:
    manager = JobManager()

    job = manager.create_job("https://example.com/video", "Caption here")

    assert job.status is JobStatus.QUEUED
    assert job.caption == "Caption here"
    assert manager.get_job(job.job_id) is job


def test_list_jobs_preserves_creation_order() -> None:
    manager = JobManager()

    first = manager.create_job("https://example.com/one")
    second = manager.create_job("https://example.com/two")

    assert manager.list_jobs() == [first, second]


def test_job_manager_tracks_active_job_state() -> None:
    manager = JobManager()
    job = manager.create_job("https://example.com/video")

    manager.set_active_job(job.job_id)

    assert manager.active_job_id == job.job_id
    assert manager.has_active_job() is True

    manager.clear_active_job(job.job_id)

    assert manager.active_job_id is None
    assert manager.has_active_job() is False
