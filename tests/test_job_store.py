import json
from pathlib import Path

from app.config import Settings
from app.models.job import Job, JobStatus
from app.services.job_store import JobStore


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="123456:test-token",
        TELEGRAM_ALLOWED_USER_IDS="123",
        FACEBOOK_PAGE_URL="https://facebook.example/page",
        DOWNLOAD_DIR=tmp_path / "downloads",
        SESSION_DIR=tmp_path / "sessions",
        SCREENSHOT_DIR=tmp_path / "screenshots",
        LOG_DIR=tmp_path / "logs",
    )


def test_job_store_writes_json_snapshot_with_artifact_refs(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    store = JobStore(settings)
    job = Job(
        source_url="https://example.com/video",
        caption="Caption here",
        download_path=tmp_path / "downloads" / "clip.mp4",
        download_filename="clip.mp4",
        facebook_post_url="https://facebook.com/example/posts/123",
    )
    job.set_status(JobStatus.PUBLISHED)

    record_path = store.save(job)
    payload = json.loads(record_path.read_text(encoding="utf-8"))

    assert record_path.exists()
    assert payload["job_id"] == job.job_id
    assert payload["status"] == "published"
    assert payload["caption"] == "Caption here"
    assert payload["download_filename"] == "clip.mp4"
    assert payload["facebook_post_url"].endswith("/123")
    assert payload["artifacts"]["download_path"].endswith("clip.mp4")
    assert job.persisted_record_path == record_path


def test_job_store_extracts_publish_failure_screenshot_from_error_text(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    store = JobStore(settings)
    screenshot_path = tmp_path / "screenshots" / "failed.png"
    job = Job(source_url="https://example.com/video")
    job.set_status(
        JobStatus.FAILED,
        error_message=f"Facebook publish failed. Screenshot: {screenshot_path}",
    )

    payload = store.build_record(job)

    assert payload["artifacts"]["publish_failure_screenshot_path"] == str(screenshot_path)


def test_job_store_can_load_a_saved_snapshot_by_job_id(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    store = JobStore(settings)
    job = Job(source_url="https://example.com/video", caption="Stored job")
    job.set_status(JobStatus.FAILED, error_message="Network timeout")
    store.save(job)

    payload = store.load(job.job_id)

    assert store.get_record_path(job.job_id).exists()
    assert payload["job_id"] == job.job_id
    assert payload["status"] == "failed"
