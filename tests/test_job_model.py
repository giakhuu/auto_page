from app.models.job import Job, JobStatus


def test_job_defaults_to_queued_with_generated_id() -> None:
    job = Job(source_url="https://example.com/video")

    assert job.job_id
    assert job.status is JobStatus.QUEUED
    assert job.created_at == job.updated_at
    assert job.download_filename is None
    assert job.download_duration_seconds is None
    assert job.download_file_size_bytes is None
    assert job.persisted_record_path is None
    assert job.is_terminal is False


def test_job_status_updates_refresh_timestamp_and_error_message() -> None:
    job = Job(source_url="https://example.com/video")
    before = job.updated_at

    job.set_status(JobStatus.FAILED, error_message="network error")

    assert job.status is JobStatus.FAILED
    assert job.error_message == "network error"
    assert job.updated_at >= before
    assert job.is_terminal is True


def test_job_builds_clip_caption_labels() -> None:
    first = Job(
        source_url="https://example.com/video",
        clip_start_seconds=0,
        clip_end_seconds=90,
        clip_index=0,
        clip_total=2,
    )
    last = Job(
        source_url="https://example.com/video",
        clip_start_seconds=90,
        clip_end_seconds=180,
        clip_index=1,
        clip_total=2,
    )

    assert first.clip_label == "Phần 1"
    assert first.build_clip_caption("Caption here") == "Caption here\n\nPhần 1"
    assert last.clip_label == "Phần 2"
    assert last.build_clip_caption("") == "Phần 2"
