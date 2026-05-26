import asyncio
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.models.job import Job, JobStatus
from app.services.job_manager import JobManager
from app.services.job_store import JobStore
from app.services.notifier import TelegramJobNotifier
from app.services.orchestrator import JobOrchestrator


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="123456:test-token",
        TELEGRAM_ALLOWED_USER_IDS="123",
        FACEBOOK_PAGE_URL="https://facebook.example/page",
        DOWNLOAD_DIR=tmp_path / "downloads",
        SESSION_DIR=tmp_path / "sessions",
        SCREENSHOT_DIR=tmp_path / "screenshots",
        AUTO_SCHEDULE_SLOT_STATE_FILE=tmp_path / "auto_schedule_slot.txt",
        LOG_DIR=tmp_path / "logs",
    )


class FakeDownloader:
    def __init__(self, tmp_path: Path, should_fail: bool = False) -> None:
        self.tmp_path = tmp_path
        self.should_fail = should_fail
        self.calls: list[str] = []

    def download(self, source_url: str, job: Job | None = None):
        self.calls.append(source_url)
        if self.should_fail:
            if job is not None:
                job.set_status(JobStatus.FAILED, error_message="Download failed")
            raise RuntimeError("Download failed")

        if job is not None:
            download_path = self.tmp_path / "downloads" / "clip.mp4"
            download_path.parent.mkdir(parents=True, exist_ok=True)
            download_path.write_text("video", encoding="utf-8")
            job.download_path = download_path
            job.download_filename = "clip.mp4"
            job.set_status(JobStatus.DOWNLOADED)
        return SimpleNamespace(caption="Caption here", title="Demo title")


class FakePublisher:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[str] = []
        self.download_filenames: list[str | None] = []
        self.default_captions: list[str] = []

    def publish_job(self, page, job: Job, default_caption: str = ""):
        self.calls.append(job.job_id)
        self.download_filenames.append(job.download_filename)
        self.default_captions.append(default_caption)
        if self.should_fail:
            job.set_status(
                JobStatus.FAILED,
                error_message="Facebook publish failed. Screenshot: data/screenshots/fail.png",
            )
            raise RuntimeError("Publish failed")

        job.facebook_post_url = "https://facebook.com/example/posts/123"
        job.set_status(JobStatus.PUBLISHED)
        return job


class FakeCaptionEditor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def edit(self, caption: str) -> str:
        self.calls.append(caption)
        return f"Edited: {caption}"


class FakeVideoProcessor:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def process(self, input_path: Path, job: Job | None = None):
        self.calls.append(input_path)
        processed_path = input_path.with_name(f"{input_path.stem}-processed.mp4")
        input_path.replace(processed_path)
        if job is not None:
            job.download_path = processed_path
            job.download_filename = processed_path.name
            job.download_duration_seconds = 1.1
            job.download_file_size_bytes = processed_path.stat().st_size
        return job


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


@contextmanager
def fake_page_session():
    yield object()


def test_orchestrator_runs_job_serially_and_persists_success(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    job_manager = JobManager()
    bot = FakeBot()
    publisher = FakePublisher()
    orchestrator = JobOrchestrator(
        settings=settings,
        job_manager=job_manager,
        downloader=FakeDownloader(tmp_path),
        video_processor=FakeVideoProcessor(),
        publisher=publisher,
        job_store=JobStore(settings),
        notifier=TelegramJobNotifier(),
        page_session_factory=fake_page_session,
    )
    job = job_manager.create_job("https://example.com/video", "Caption here")

    result = asyncio.run(orchestrator.run_job(job, bot=bot, chat_id=321))
    payload = json.loads(result.persisted_record_path.read_text(encoding="utf-8"))

    assert result.job.status is JobStatus.PUBLISHED
    assert result.job.facebook_post_url.endswith("/123")
    assert payload["status"] == "published"
    assert payload["facebook_post_url"].endswith("/123")
    assert publisher.download_filenames == ["clip-processed.mp4"]
    assert bot.messages and bot.messages[0][0] == 321
    assert job_manager.active_job_id is None
    assert not (tmp_path / "downloads" / "clip.mp4").exists()
    assert not (tmp_path / "downloads" / "clip-processed.mp4").exists()


def test_orchestrator_persists_auto_schedule_slot_after_success(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    job_manager = JobManager()
    orchestrator = JobOrchestrator(
        settings=settings,
        job_manager=job_manager,
        downloader=FakeDownloader(tmp_path),
        video_processor=FakeVideoProcessor(),
        publisher=FakePublisher(),
        job_store=JobStore(settings),
        notifier=TelegramJobNotifier(),
        page_session_factory=fake_page_session,
    )
    job = job_manager.create_job(
        "https://example.com/video",
        publish_mode="scheduled",
        scheduled_at=datetime(2026, 5, 3, 12, 30, tzinfo=timezone.utc),
        auto_schedule_slot_index=2,
    )

    asyncio.run(orchestrator.run_job(job))

    assert settings.auto_schedule_slot_state_file.exists()
    content = settings.auto_schedule_slot_state_file.read_text(encoding="utf-8")
    assert "last_slot_index=2" in content
    assert f"last_job_id={job.job_id}" in content
    assert "scheduled_slot=2026-05-03 12:30" in content


def test_orchestrator_edits_source_caption_only_when_job_caption_is_empty(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    job_manager = JobManager()
    publisher = FakePublisher()
    caption_editor = FakeCaptionEditor()
    orchestrator = JobOrchestrator(
        settings=settings,
        job_manager=job_manager,
        downloader=FakeDownloader(tmp_path),
        video_processor=FakeVideoProcessor(),
        publisher=publisher,
        job_store=JobStore(settings),
        notifier=TelegramJobNotifier(),
        caption_editor=caption_editor,
        page_session_factory=fake_page_session,
    )
    job = job_manager.create_job("https://example.com/video")

    asyncio.run(orchestrator.run_job(job))

    assert caption_editor.calls == ["Caption here"]
    assert publisher.default_captions == ["Edited: Caption here"]


def test_orchestrator_keeps_manual_caption_unedited(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    job_manager = JobManager()
    caption_editor = FakeCaptionEditor()
    orchestrator = JobOrchestrator(
        settings=settings,
        job_manager=job_manager,
        downloader=FakeDownloader(tmp_path),
        video_processor=FakeVideoProcessor(),
        publisher=FakePublisher(),
        job_store=JobStore(settings),
        notifier=TelegramJobNotifier(),
        caption_editor=caption_editor,
        page_session_factory=fake_page_session,
    )
    job = job_manager.create_job("https://example.com/video", "Caption tu Telegram")

    asyncio.run(orchestrator.run_job(job))

    assert caption_editor.calls == []


def test_orchestrator_persists_failure_and_still_notifies_operator(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    job_manager = JobManager()
    bot = FakeBot()
    orchestrator = JobOrchestrator(
        settings=settings,
        job_manager=job_manager,
        downloader=FakeDownloader(tmp_path),
        video_processor=FakeVideoProcessor(),
        publisher=FakePublisher(should_fail=True),
        job_store=JobStore(settings),
        notifier=TelegramJobNotifier(),
        page_session_factory=fake_page_session,
    )
    job = job_manager.create_job("https://example.com/video")

    result = asyncio.run(orchestrator.run_job(job, bot=bot, chat_id=654))
    payload = json.loads(result.persisted_record_path.read_text(encoding="utf-8"))

    assert result.job.status is JobStatus.FAILED
    assert "Screenshot:" in (result.job.error_message or "")
    assert payload["status"] == "failed"
    assert payload["artifacts"]["publish_failure_screenshot_path"].endswith("fail.png")
    assert "Publish job failed." in bot.messages[0][1]
    assert not (tmp_path / "downloads" / "clip.mp4").exists()
    assert not (tmp_path / "downloads" / "clip-processed.mp4").exists()
