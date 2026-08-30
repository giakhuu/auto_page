"""Serial end-to-end job orchestration for the MVP pipeline."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from app.config import Settings, get_settings
from app.core.logger import get_job_logger
from app.models.job import Job, JobStatus
from app.services.caption_editor import CaptionEditor
from app.services.downloader import VideoDownloader
from app.services.job_manager import JobManager
from app.services.job_store import JobStore
from app.services.notifier import TelegramJobNotifier
from app.services.publisher import FacebookPublisher, create_publisher
from app.services.session_manager import SessionManager
from app.services.slot_store import AutoScheduleSlotStore
from app.services.video_processor import VideoProcessor


@dataclass(slots=True)
class JobRunResult:
    """Represents one orchestration run and its side effects."""

    job: Job
    persisted_record_path: Path | None = None
    notification_text: str = ""


@dataclass(slots=True)
class ClipBatchRunResult:
    """Represents one clip-batch orchestration run and its side effects."""

    jobs: tuple[Job, ...]
    persisted_record_paths: tuple[Path, ...] = ()
    notification_texts: tuple[str, ...] = ()


class JobOrchestrator:
    """Run one job through download, publish, persistence, and notification."""

    def __init__(
        self,
        settings: Settings | None = None,
        job_manager: JobManager | None = None,
        downloader: VideoDownloader | None = None,
        session_manager: SessionManager | None = None,
        video_processor: VideoProcessor | None = None,
        publisher: FacebookPublisher | None = None,
        job_store: JobStore | None = None,
        slot_store: AutoScheduleSlotStore | None = None,
        notifier: TelegramJobNotifier | None = None,
        caption_editor: CaptionEditor | None = None,
        page_session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.job_manager = job_manager or JobManager()
        self.downloader = downloader or VideoDownloader(self.settings)
        self.session_manager = session_manager or SessionManager(self.settings)
        self.video_processor = video_processor or VideoProcessor()
        self.publisher = publisher or create_publisher(settings=self.settings, session_manager=self.session_manager)
        self.job_store = job_store or JobStore(self.settings)
        self.slot_store = slot_store or AutoScheduleSlotStore(self.settings)
        self.notifier = notifier or TelegramJobNotifier()
        self.caption_editor = caption_editor or CaptionEditor(self.settings)
        self.page_session_factory = page_session_factory or self._open_page_session
        self._serial_lock = asyncio.Lock()

    @contextmanager
    def _open_page_session(self) -> Any:
        """Open a Playwright page backed by the stored Facebook session."""
        from playwright.sync_api import sync_playwright

        bootstrap = self.session_manager.build_bootstrap_config()
        playwright = sync_playwright().start()
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(bootstrap.user_data_dir),
            headless=bootstrap.headless,
            args=list(bootstrap.launch_args),
            downloads_path=str(bootstrap.downloads_path),
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            yield page
        finally:
            context.close()
            playwright.stop()

    def _execute_pipeline(self, job: Job) -> Path:
        """Run the blocking download + publish pipeline and persist the result."""
        logger = get_job_logger("page_automation.orchestrator", job.job_id)
        logger.info("starting job orchestration", extra={"source_url": job.source_url})

        try:
            download_result = self.downloader.download(job.source_url, job=job)
            if job.download_path is None:
                raise RuntimeError("Downloaded job does not have a local video path.")
            self.video_processor.process(job.download_path, job=job)
            default_caption = getattr(download_result, "caption", "") or getattr(download_result, "title", "") or ""
            if not job.caption and default_caption:
                default_caption = self.caption_editor.edit(default_caption)
            with self.page_session_factory() as page:
                self.publisher.publish_job(page, job, default_caption=default_caption)
            slot_state_path = self.slot_store.mark_job_complete(job)
            if slot_state_path is not None:
                logger.info("auto-schedule slot cursor persisted", extra={"slot_state_path": str(slot_state_path)})
        except Exception as error:
            if job.status is not JobStatus.FAILED:
                job.set_status(JobStatus.FAILED, error_message=str(error))
            logger.error("job orchestration failed: %s", job.error_message or error)
        finally:
            self._cleanup_download_artifact(job, logger)

        record_path = self.job_store.save(job)
        logger.info(
            "job orchestration persisted result",
            extra={"record_path": str(record_path), "final_status": job.status.value},
        )
        return record_path

    def _execute_clip_batch(self, jobs: Sequence[Job]) -> tuple[Path, ...]:
        """Run one source download through multiple clip publish jobs."""
        if not jobs:
            return ()

        first_job = jobs[0]
        group_id = first_job.clip_group_id or first_job.job_id
        logger = get_job_logger("page_automation.orchestrator", group_id)
        logger.info(
            "starting clip batch orchestration",
            extra={"source_url": first_job.source_url, "clip_count": len(jobs)},
        )

        source_path: Path | None = None
        record_paths: list[Path] = []

        try:
            download_result = self.downloader.download(first_job.source_url)
            source_path = download_result.download_path
            default_caption = getattr(download_result, "caption", "") or getattr(download_result, "title", "") or ""
            if default_caption and any(not job.caption for job in jobs):
                default_caption = self.caption_editor.edit(default_caption)
        except Exception as error:
            detail = str(error)
            logger.error("clip batch source download failed: %s", detail)
            for job in jobs:
                if job.status is not JobStatus.FAILED:
                    job.set_status(JobStatus.FAILED, error_message=detail)
                record_paths.append(self.job_store.save(job))
            return tuple(record_paths)

        try:
            for job in jobs:
                try:
                    if not job.is_clip_job:
                        raise RuntimeError("Clip batch job is missing clip metadata.")

                    logger.info(
                        "starting clip job orchestration",
                        extra={
                            "job_id": job.job_id,
                            "clip_start_seconds": job.clip_start_seconds,
                            "clip_end_seconds": job.clip_end_seconds,
                            "clip_index": job.clip_index,
                        },
                    )
                    self.video_processor.trim(
                        source_path,
                        job.clip_start_seconds or 0,
                        job.clip_end_seconds or 0,
                        job.clip_index or 0,
                        job=job,
                    )
                    if job.download_path is None:
                        raise RuntimeError("Trimmed job does not have a local video path.")
                    self.video_processor.process(job.download_path, job=job)
                    job.caption = job.build_clip_caption(job.caption or default_caption)
                    with self.page_session_factory() as page:
                        self.publisher.publish_job(page, job, default_caption="")
                    slot_state_path = self.slot_store.mark_job_complete(job)
                    if slot_state_path is not None:
                        logger.info("auto-schedule slot cursor persisted", extra={"slot_state_path": str(slot_state_path)})
                except Exception as error:
                    if job.status is not JobStatus.FAILED:
                        job.set_status(JobStatus.FAILED, error_message=str(error))
                    logger.error("clip job orchestration failed: %s", job.error_message or error)
                finally:
                    self._cleanup_download_artifact(job, logger)
                    record_path = self.job_store.save(job)
                    record_paths.append(record_path)
                    logger.info(
                        "clip job orchestration persisted result",
                        extra={"record_path": str(record_path), "final_status": job.status.value},
                    )
        finally:
            if source_path is not None:
                self._delete_download_artifact_path(source_path, logger)

        return tuple(record_paths)

    def _cleanup_download_artifact(self, job: Job, logger: Any) -> None:
        """Delete the local downloaded video after the job finishes or fails."""
        if job.download_path is None:
            return

        self._delete_download_artifact_path(Path(job.download_path), logger)

    def _delete_download_artifact_path(self, download_path: Path, logger: Any) -> None:
        """Delete a local video artifact when it lives under the download directory."""
        try:
            resolved_download = download_path.resolve()
            resolved_root = self.settings.download_dir.resolve()
            if resolved_download == resolved_root or resolved_root not in resolved_download.parents:
                logger.warning("skipped cleanup outside download directory", extra={"download_path": str(download_path)})
                return
            if resolved_download.is_file():
                resolved_download.unlink()
                logger.info("deleted local downloaded video", extra={"download_path": str(download_path)})
        except Exception as error:
            logger.warning("could not delete local downloaded video: %s", error, extra={"download_path": str(download_path)})

    async def run_job(self, job: Job, bot: Any | None = None, chat_id: int | None = None) -> JobRunResult:
        """Run one job serially and optionally send the final Telegram notification."""
        logger = get_job_logger("page_automation.orchestrator", job.job_id)

        async with self._serial_lock:
            self.job_manager.set_active_job(job.job_id)
            try:
                record_path = await asyncio.to_thread(self._execute_pipeline, job)
                notification_text = ""

                if bot is not None and chat_id is not None:
                    try:
                        notification_text = await self.notifier.send_job_result(bot, chat_id, job)
                        logger.info("sent final telegram notification", extra={"chat_id": chat_id})
                    except Exception as error:
                        logger.error("failed to send final telegram notification: %s", error)

                return JobRunResult(
                    job=job,
                    persisted_record_path=record_path,
                    notification_text=notification_text,
                )
            finally:
                self.job_manager.clear_active_job(job.job_id)

    async def run_clip_batch(
        self,
        jobs: Sequence[Job],
        bot: Any | None = None,
        chat_id: int | None = None,
    ) -> ClipBatchRunResult:
        """Run multiple clip jobs serially from one source download."""
        if not jobs:
            return ClipBatchRunResult(jobs=())

        batch_jobs = tuple(jobs)
        active_job_id = batch_jobs[0].job_id
        logger = get_job_logger("page_automation.orchestrator", batch_jobs[0].clip_group_id or active_job_id)

        async with self._serial_lock:
            self.job_manager.set_active_job(active_job_id)
            try:
                record_paths = await asyncio.to_thread(self._execute_clip_batch, batch_jobs)
                notification_texts: list[str] = []

                if bot is not None and chat_id is not None:
                    for job in batch_jobs:
                        try:
                            notification_text = await self.notifier.send_job_result(bot, chat_id, job)
                            notification_texts.append(notification_text)
                            logger.info(
                                "sent final clip telegram notification",
                                extra={"chat_id": chat_id, "job_id": job.job_id},
                            )
                        except Exception as error:
                            logger.error("failed to send final clip telegram notification: %s", error)

                return ClipBatchRunResult(
                    jobs=batch_jobs,
                    persisted_record_paths=record_paths,
                    notification_texts=tuple(notification_texts),
                )
            finally:
                self.job_manager.clear_active_job(active_job_id)
