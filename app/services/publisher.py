"""Playwright-backed Facebook video publishing service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from app.config import Settings, get_settings
from app.core.logger import get_job_logger
from app.models.job import Job, JobStatus
from app.services.session_manager import SessionDiagnostic, SessionHealthStatus, SessionManager

DEFAULT_INTERACTION_TIMEOUT_MS = 15_000
DEFAULT_PUBLISH_TIMEOUT_MS = 120_000

BUSINESS_CALENDAR_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
BUSINESS_CALENDAR_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass(frozen=True, slots=True)
class PublisherSelectors:
    """Selector contract used by the publisher service."""

    composer_entrypoints: tuple[str, ...] = (
        "[aria-label='Create post']",
        "[aria-label='Create a post']",
        "[role='button'][aria-label*='Photo/video']",
        "[role='button'][aria-label*='Video']",
        "div[role='button']:has-text('Create post')",
        "div[role='button']:has-text('Photo/video')",
        "button:has-text('Create post')",
        "button:has-text('Photo/video')",
    )
    file_inputs: tuple[str, ...] = (
        "input[type='file'][accept*='video']",
        "input[type='file']",
    )
    caption_editors: tuple[str, ...] = (
        "div[role='textbox'][contenteditable='true']",
        "div[contenteditable='true'][data-lexical-editor='true']",
        "textarea[placeholder*='Write']",
        "textarea[aria-label*='Write']",
    )
    publish_buttons: tuple[str, ...] = (
        "[aria-label='Publish']",
        "[role='button'][aria-label='Publish']",
        "div[role='button']:has-text('Publish')",
        "button:has-text('Publish')",
        "button[type='submit']",
    )
    ready_indicators: tuple[str, ...] = (
        "div[role='textbox'][contenteditable='true']",
        "div[contenteditable='true'][data-lexical-editor='true']",
        "[aria-label='Publish']",
        "div[role='button']:has-text('Publish')",
        "[data-pagelet*='FeedUnit']",
    )
    success_indicators: tuple[str, ...] = (
        "text='Your post is now published'",
        "text='Post published'",
        "text='Video uploaded'",
        "text='Published'",
    )
    failure_indicators: tuple[str, ...] = (
        "text='Something went wrong'",
        "text='Try again'",
        "text='Unable to publish'",
        "[role='alert']",
    )


@dataclass(slots=True)
class PublishEvidence:
    """Failure diagnostics captured from the browser surface."""

    stage: str
    screenshot_path: Path
    page_url: str
    page_title: str
    visible_signals: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class PublishResult:
    """Represents a publish attempt outcome."""

    success: bool
    post_url: str
    applied_caption: str
    uploaded_video_name: str
    detected_signal: str
    resolved_url: str
    evidence: PublishEvidence | None = None


class PublisherError(RuntimeError):
    """Raised when the publish flow cannot complete successfully."""


@dataclass(frozen=True, slots=True)
class BusinessSuiteSelectors:
    """Selector contract for Meta Business Suite publishing."""

    upload_entrypoints: tuple[str, ...] = (
        "[aria-label='Thêm video']",
        "div[role='button']:has-text('Thêm video')",
        "button:has-text('Thêm video')",
        "[aria-label='Add video']",
        "[aria-label='Thêm video']",
        "div[role='button']:has-text('Add video')",
        "div[role='button']:has-text('Thêm video')",
        "button:has-text('Add video')",
        "button:has-text('Thêm video')",
    )
    upload_from_computer: tuple[str, ...] = (
        "text='Tải lên từ máy tính'",
        "div[role='button']:has-text('Tải lên từ máy tính')",
        "text='Upload from computer'",
        "text='Tải lên từ máy tính'",
        "div[role='button']:has-text('Upload from computer')",
        "div[role='button']:has-text('Tải lên từ máy tính')",
    )
    file_inputs: tuple[str, ...] = (
        "input[type='file'][accept*='video']",
        "input[type='file']",
    )
    caption_editors: tuple[str, ...] = (
        "textarea[placeholder*='Mô tả']",
        "textarea[aria-label*='Mô tả']",
        "div[role='textbox'][contenteditable='true']",
        "div[contenteditable='true'][data-lexical-editor='true']",
        "textarea[placeholder*='caption']",
        "textarea[aria-label*='caption']",
        "textarea[placeholder*='Mô tả']",
        "textarea[aria-label*='Mô tả']",
    )
    collaborator_entrypoints: tuple[str, ...] = (
        "[aria-label*='Collaborator']",
        "[aria-label*='collaborator']",
        "[aria-label*='Collaboration']",
        "[aria-label*='Cộng tác viên']",
        "div[role='button']:has-text('Collaborator')",
        "div[role='button']:has-text('Collaboration')",
        "div[role='button']:has-text('Cộng tác viên')",
        "button:has-text('Collaborator')",
        "button:has-text('Collaboration')",
        "button:has-text('Cộng tác viên')",
    )
    collaborator_search_inputs: tuple[str, ...] = (
        "input[placeholder*='Search']",
        "input[aria-label*='Search']",
        "input[placeholder*='Tìm kiếm']",
        "input[aria-label*='Tìm kiếm']",
        "input[placeholder*='người dùng']",
        "input[aria-label*='người dùng']",
        "input[placeholder*='URL Trang']",
        "input[aria-label*='URL Trang']",
        "input[placeholder*='collaborator']",
        "input[aria-label*='collaborator']",
        "input[placeholder*='cộng tác']",
        "input[aria-label*='cộng tác']",
        "[role='dialog'] div[role='textbox'][contenteditable='true']",
        "[aria-modal='true'] div[role='textbox'][contenteditable='true']",
    )
    collaborator_confirm_buttons: tuple[str, ...] = (
        "[aria-label='Done']",
        "[aria-label='Save']",
        "[aria-label='Add']",
        "[aria-label='Invite']",
        "[aria-label='Xong']",
        "[aria-label='Lưu']",
        "[aria-label='Thêm']",
        "[aria-label='Mời']",
        "div[role='button']:has-text('Done')",
        "div[role='button']:has-text('Save')",
        "div[role='button']:has-text('Add')",
        "div[role='button']:has-text('Invite')",
        "div[role='button']:has-text('Xong')",
        "div[role='button']:has-text('Lưu')",
        "div[role='button']:has-text('Thêm')",
        "div[role='button']:has-text('Mời')",
        "button:has-text('Done')",
        "button:has-text('Save')",
        "button:has-text('Add')",
        "button:has-text('Invite')",
        "button:has-text('Xong')",
        "button:has-text('Lưu')",
        "button:has-text('Thêm')",
        "button:has-text('Mời')",
    )
    publish_buttons: tuple[str, ...] = (
        "[aria-label='Đăng']",
        "[aria-label='Chia sẻ']",
        "div[role='button']:has-text('Đăng')",
        "div[role='button']:has-text('Chia sẻ')",
        "button:has-text('Đăng')",
        "button:has-text('Chia sẻ')",
        "[aria-label='Publish']",
        "[aria-label='Share']",
        "[aria-label='Đăng']",
        "div[role='button']:has-text('Publish')",
        "div[role='button']:has-text('Share')",
        "div[role='button']:has-text('Đăng')",
        "div[role='button']:has-text('Chia sẻ')",
        "button:has-text('Publish')",
        "button:has-text('Share')",
        "button:has-text('Đăng')",
        "button:has-text('Chia sẻ')",
    )
    schedule_mode_buttons: tuple[str, ...] = (
        "text='Lên lịch'",
        "[aria-label='Lên lịch']",
        "div[role='button']:has-text('Lên lịch')",
        "text='Schedule'",
        "text='Lên lịch'",
        "[aria-label='Schedule']",
        "[aria-label='Lên lịch']",
        "div[role='button']:has-text('Schedule')",
        "div[role='button']:has-text('Lên lịch')",
    )
    schedule_datetime_inputs: tuple[str, ...] = (
        "input[aria-label*='Ngày']",
        "input[placeholder*='Ngày']",
        "input[placeholder*='dd/mm']",
        "input[type='datetime-local']",
        "input[aria-label*='Date']",
        "input[aria-label*='Ngày']",
        "input[placeholder*='Date']",
        "input[placeholder*='Ngày']",
        "input[placeholder*='dd/mm']",
    )
    schedule_hour_inputs: tuple[str, ...] = (
        "input[aria-label='giờ']",
        "input[aria-label*='Giờ']",
        "input[aria-label*='hour']",
        "input[aria-label*='Hour']",
    )
    schedule_minute_inputs: tuple[str, ...] = (
        "input[aria-label='phút']",
        "input[aria-label*='Phút']",
        "input[aria-label*='minute']",
        "input[aria-label*='Minute']",
    )
    schedule_submit_buttons: tuple[str, ...] = (
        "[aria-label='Lên lịch']",
        "div[role='button']:has-text('Lên lịch')",
        "button:has-text('Lên lịch')",
        "[aria-label='Schedule']",
        "[aria-label='Lên lịch']",
        "div[role='button']:has-text('Schedule')",
        "div[role='button']:has-text('Lên lịch')",
        "button:has-text('Schedule')",
        "button:has-text('Lên lịch')",
    )
    reels_next_buttons: tuple[str, ...] = (
        "[aria-label='Next']",
        "[aria-label='Tiếp']",
        "div[role='button']:has-text('Next')",
        "div[role='button']:has-text('Tiếp')",
        "button:has-text('Next')",
        "button:has-text('Tiếp')",
    )
    reels_action_ready_indicators: tuple[str, ...] = (
        "[aria-label='Đăng']",
        "[aria-label='Chia sẻ']",
        "[aria-label='Publish']",
        "[aria-label='Share']",
        "[aria-label='Lên lịch']",
        "[aria-label='Schedule']",
        "div[role='button']:has-text('Đăng')",
        "div[role='button']:has-text('Chia sẻ')",
        "div[role='button']:has-text('Publish')",
        "div[role='button']:has-text('Share')",
        "div[role='button']:has-text('Lên lịch')",
        "div[role='button']:has-text('Schedule')",
        "input[aria-label*='Ngày']",
        "input[aria-label*='Date']",
    )
    success_indicators: tuple[str, ...] = (
        "text='Đã đăng'",
        "text='Post published'",
        "text='Your post is now published'",
        "text='Đã đăng'",
        "text='Published'",
    )
    scheduled_indicators: tuple[str, ...] = (
        "text='Đã lên lịch'",
        "text='Lên lịch'",
        "text='Scheduled'",
        "text='Đã lên lịch'",
        "text='Lên lịch'",
    )
    failure_indicators: tuple[str, ...] = (
        "text='Không thể đăng'",
        "text='Something went wrong'",
        "text='Try again'",
        "text='Unable to publish'",
        "text='Không thể đăng'",
        "[role='alert']",
    )
    composer_ready_indicators: tuple[str, ...] = (
        "input[type='file'][accept*='video']",
        "input[type='file']",
        "[aria-label='Add video']",
        "[aria-label='Thêm video']",
        "div[role='button']:has-text('Add video')",
        "div[role='button']:has-text('Thêm video')",
        "div[role='textbox'][contenteditable='true']",
        "div[contenteditable='true'][data-lexical-editor='true']",
        "[aria-label='Publish']",
        "[aria-label='Đăng']",
        "[aria-label='Schedule']",
        "[aria-label='Lên lịch']",
    )
    explicit_login_indicators: tuple[str, ...] = (
        "input[name='email']",
        "input[name='pass']",
        "text='Log in to Facebook'",
        "text='Log into Facebook'",
        "text='Đăng nhập Facebook'",
        "text='Đăng nhập vào Facebook'",
    )
    optional_dialog_dismiss_buttons: tuple[str, ...] = (
        "[aria-label='Not now']",
        "[aria-label='Maybe later']",
        "[aria-label='Lúc khác']",
        "[aria-label='Để sau']",
        "div[role='button']:has-text('Not now')",
        "div[role='button']:has-text('Maybe later')",
        "div[role='button']:has-text('Lúc khác')",
        "div[role='button']:has-text('Để sau')",
    )


class FacebookPublisher:
    """Encapsulate Playwright interactions for Fanpage video publishing."""

    def __init__(
        self,
        settings: Settings | None = None,
        session_manager: SessionManager | None = None,
        selectors: PublisherSelectors | None = None,
        interaction_timeout_ms: int = DEFAULT_INTERACTION_TIMEOUT_MS,
        publish_timeout_ms: int = DEFAULT_PUBLISH_TIMEOUT_MS,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_manager = session_manager or SessionManager(self.settings)
        self.selectors = selectors or PublisherSelectors()
        self.interaction_timeout_ms = interaction_timeout_ms
        self.publish_timeout_ms = publish_timeout_ms

    def build_logger(self, job_id: str = "-") -> Any:
        """Return a job-aware logger for publish events."""
        return get_job_logger("page_automation.publisher", job_id)

    @staticmethod
    def _get_locator(page: object, selector: str) -> object:
        locator = page.locator(selector)
        first = getattr(locator, "first", None)
        if callable(first):
            return first()
        if first is not None:
            return first
        return locator

    @staticmethod
    def _iter_locators(page: object, selector: str) -> list[object]:
        locator = page.locator(selector)
        count = getattr(locator, "count", None)
        nth = getattr(locator, "nth", None)
        if callable(count) and callable(nth):
            try:
                return [nth(index) for index in range(count())]
            except Exception:
                pass
        return [FacebookPublisher._get_locator(page, selector)]

    @staticmethod
    def _locator_exists(locator: object) -> bool:
        count = getattr(locator, "count", None)
        if callable(count):
            return count() > 0
        return True

    @staticmethod
    def _locator_visible(locator: object) -> bool:
        if not FacebookPublisher._locator_exists(locator):
            return False
        is_visible = getattr(locator, "is_visible", None)
        if callable(is_visible):
            return bool(is_visible())
        return True

    @staticmethod
    def _locator_enabled(locator: object) -> bool:
        is_enabled = getattr(locator, "is_enabled", None)
        if callable(is_enabled):
            return bool(is_enabled())
        return True

    @staticmethod
    def _wait_for_locator(locator: object, timeout_ms: int, state: str = "visible") -> bool:
        wait_for = getattr(locator, "wait_for", None)
        if not callable(wait_for):
            return FacebookPublisher._locator_visible(locator)

        try:
            wait_for(state=state, timeout=timeout_ms)
            return True
        except Exception:
            return False

    def _find_first_visible(self, page: object, selectors: tuple[str, ...]) -> tuple[str, object] | None:
        for selector in selectors:
            for locator in self._iter_locators(page, selector):
                if self._locator_visible(locator):
                    return selector, locator
        return None

    def _wait_for_any(
        self,
        page: object,
        selectors: tuple[str, ...],
        timeout_ms: int,
        require_enabled: bool = False,
    ) -> tuple[str, object] | None:
        end_time = monotonic() + (timeout_ms / 1000)
        while monotonic() <= end_time:
            for selector in selectors:
                for locator in self._iter_locators(page, selector):
                    if not self._wait_for_locator(locator, timeout_ms=250):
                        continue
                    if require_enabled and not self._locator_enabled(locator):
                        continue
                    if self._locator_visible(locator):
                        return selector, locator

            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                wait_for_timeout(250)
            else:
                break

        return self._find_first_visible(page, selectors)

    def _wait_for_any_attached(
        self,
        page: object,
        selectors: tuple[str, ...],
        timeout_ms: int,
    ) -> tuple[str, object] | None:
        end_time = monotonic() + (timeout_ms / 1000)
        while monotonic() <= end_time:
            for selector in selectors:
                for locator in self._iter_locators(page, selector):
                    if self._wait_for_locator(locator, timeout_ms=250, state="attached"):
                        return selector, locator

            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                wait_for_timeout(250)
            else:
                break

        return None

    @staticmethod
    def _click(locator: object) -> None:
        click = getattr(locator, "click", None)
        if not callable(click):
            raise PublisherError("Target locator does not support click().")
        click()

    @staticmethod
    def _fill(locator: object, text: str) -> None:
        fill = getattr(locator, "fill", None)
        if callable(fill):
            fill(text)
            return

        click = getattr(locator, "click", None)
        if callable(click):
            click()

        type_text = getattr(locator, "type", None)
        if callable(type_text):
            type_text(text)
            return

        raise PublisherError("Target locator does not support fill() or type().")

    @staticmethod
    def _set_input_files(locator: object, video_path: Path) -> None:
        set_input_files = getattr(locator, "set_input_files", None)
        if not callable(set_input_files):
            raise PublisherError("Upload locator does not support set_input_files().")
        set_input_files(str(video_path))

    @staticmethod
    def _page_title(page: object) -> str:
        title = getattr(page, "title", None)
        if callable(title):
            return title()
        return ""

    @staticmethod
    def _page_url(page: object) -> str:
        return str(getattr(page, "url", "") or "")

    def _looks_like_post_url(self, url: str) -> bool:
        lowered = url.lower()
        return any(marker in lowered for marker in ("/posts/", "story_fbid=", "/videos/"))

    def preflight(self, page: object, job_id: str = "-") -> SessionDiagnostic:
        """Run the session reachability diagnostic before any publish action."""
        diagnostic = self.session_manager.check_fanpage_reachability(page, job_id=job_id)
        if diagnostic.status is not SessionHealthStatus.READY:
            raise PublisherError(diagnostic.message)
        return diagnostic

    def open_publish_surface(self, page: object, job_id: str = "-") -> SessionDiagnostic:
        """Open the publish-ready Fanpage surface and composer entrypoint."""
        logger = self.build_logger(job_id)
        diagnostic = self.preflight(page, job_id=job_id)
        logger.info("fanpage preflight passed", extra={"target_url": diagnostic.target_url})

        composer = self._wait_for_any(page, self.selectors.composer_entrypoints, timeout_ms=self.interaction_timeout_ms)
        if composer is not None:
            selector, locator = composer
            self._click(locator)
            logger.info("opened publish composer", extra={"selector": selector})
        else:
            file_input = self._wait_for_any(page, self.selectors.file_inputs, timeout_ms=2_000)
            if file_input is None:
                raise PublisherError("Could not locate a publish entrypoint or a direct video upload field.")
            logger.info("using direct upload surface", extra={"selector": file_input[0]})

        readiness = self._wait_for_any(page, self.selectors.ready_indicators, timeout_ms=self.interaction_timeout_ms)
        if readiness is None:
            raise PublisherError("Publish composer did not expose a ready caption or publish surface.")

        logger.info("publish surface ready", extra={"selector": readiness[0]})
        return diagnostic

    def upload_video(self, page: object, video_path: Path, job_id: str = "-") -> Path:
        """Upload a local video file to the active publish surface."""
        resolved_path = Path(video_path)
        logger = self.build_logger(job_id)
        video_filename = resolved_path.name

        if not resolved_path.exists():
            raise PublisherError(f"Local video file does not exist: {resolved_path}")

        upload_target = self._wait_for_any(page, self.selectors.file_inputs, timeout_ms=self.interaction_timeout_ms)
        if upload_target is None:
            raise PublisherError("No video upload input is available on the publish surface.")

        self._set_input_files(upload_target[1], resolved_path)
        logger.info(
            "selected local video for upload",
            extra={"video_path": str(resolved_path), "video_filename": video_filename, "selector": upload_target[0]},
        )

        readiness = self._wait_for_any(page, self.selectors.ready_indicators, timeout_ms=self.interaction_timeout_ms)
        if readiness is None:
            raise PublisherError("The publish surface did not become ready after selecting the local video.")

        logger.info("upload surface ready after file selection", extra={"selector": readiness[0]})
        return resolved_path

    @staticmethod
    def resolve_caption(caption: str, default_caption: str = "") -> str:
        """Choose the explicit caption first, then a caller-supplied default."""
        return caption.strip() or default_caption.strip()

    def apply_caption(self, page: object, caption: str, job_id: str = "-") -> str:
        """Populate the caption editor when content is available."""
        resolved_caption = caption.strip()
        logger = self.build_logger(job_id)
        if not resolved_caption:
            logger.info("caption step skipped because no caption text was provided")
            return ""

        caption_target = self._wait_for_any(page, self.selectors.caption_editors, timeout_ms=self.interaction_timeout_ms)
        if caption_target is None:
            raise PublisherError("No caption editor became available on the publish surface.")

        self._fill(caption_target[1], resolved_caption)
        logger.info("caption applied", extra={"selector": caption_target[0], "caption_length": len(resolved_caption)})
        return resolved_caption

    def trigger_publish(self, page: object, job_id: str = "-") -> str:
        """Click the publish action once the UI reports the control is ready."""
        logger = self.build_logger(job_id)
        publish_target = self._wait_for_any(
            page,
            self.selectors.publish_buttons,
            timeout_ms=self.interaction_timeout_ms,
            require_enabled=True,
        )
        if publish_target is None:
            raise PublisherError("No enabled publish button became available.")

        self._click(publish_target[1])
        logger.info("publish action triggered", extra={"selector": publish_target[0]})
        return publish_target[0]

    def wait_for_publish_outcome(self, page: object, job_id: str = "-") -> PublishResult:
        """Wait for success or failure signals from the Facebook publish surface."""
        logger = self.build_logger(job_id)
        end_time = monotonic() + (self.publish_timeout_ms / 1000)

        while monotonic() <= end_time:
            success = self._find_first_visible(page, self.selectors.success_indicators)
            if success is not None:
                signal = success[0]
                resolved_url = self._page_url(page)
                logger.info("publish success detected", extra={"signal": signal, "resolved_url": resolved_url})
                return PublishResult(
                    success=True,
                    post_url=resolved_url or self.settings.facebook_page_url,
                    applied_caption="",
                    uploaded_video_name="",
                    detected_signal=signal,
                    resolved_url=resolved_url,
                )

            resolved_url = self._page_url(page)
            if resolved_url and self._looks_like_post_url(resolved_url):
                logger.info("publish success detected from page redirect", extra={"resolved_url": resolved_url})
                return PublishResult(
                    success=True,
                    post_url=resolved_url,
                    applied_caption="",
                    uploaded_video_name="",
                    detected_signal="url_redirect",
                    resolved_url=resolved_url,
                )

            failure = self._find_first_visible(page, self.selectors.failure_indicators)
            if failure is not None:
                raise PublisherError(f"Facebook reported a publish failure via selector: {failure[0]}")

            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                wait_for_timeout(250)
            else:
                break

        raise PublisherError("Timed out while waiting for Facebook publish completion signals.")

    def capture_failure_evidence(self, page: object, job_id: str, stage: str) -> PublishEvidence:
        """Capture a screenshot and the visible failure signals for later debugging."""
        self.settings.screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = self.settings.screenshot_dir / f"{job_id}-publish-{stage}-failure.png"
        screenshot = getattr(page, "screenshot", None)
        if callable(screenshot):
            screenshot(path=str(screenshot_path), full_page=True)
        else:
            screenshot_path.write_text("Screenshot API unavailable on the page object.", encoding="utf-8")

        visible_signals = tuple(
            selector for selector in self.selectors.failure_indicators if self._find_first_visible(page, (selector,)) is not None
        )
        return PublishEvidence(
            stage=stage,
            screenshot_path=screenshot_path,
            page_url=self._page_url(page),
            page_title=self._page_title(page),
            visible_signals=visible_signals,
        )

    def publish_job(self, page: object, job: Job, default_caption: str = "") -> PublishResult:
        """Drive the full upload and publish workflow for one job."""
        logger = self.build_logger(job.job_id)
        applied_caption = self.resolve_caption(job.caption, default_caption)
        active_stage = "preflight"

        if job.download_path is None:
            detail = "Job does not have a local download path ready for publishing."
            job.set_status(JobStatus.FAILED, error_message=detail)
            raise PublisherError(detail)

        try:
            job.set_status(JobStatus.PUBLISHING)
            normalized_filename = job.download_filename or job.download_path.name
            logger.info(
                "starting Facebook publish flow",
                extra={"download_path": str(job.download_path), "normalized_filename": normalized_filename},
            )

            active_stage = "open-surface"
            self.open_publish_surface(page, job_id=job.job_id)

            active_stage = "upload-video"
            self.upload_video(page, job.download_path, job_id=job.job_id)

            active_stage = "apply-caption"
            applied_caption = self.apply_caption(page, applied_caption, job_id=job.job_id)

            active_stage = "trigger-publish"
            self.trigger_publish(page, job_id=job.job_id)

            active_stage = "wait-for-outcome"
            result = self.wait_for_publish_outcome(page, job_id=job.job_id)
            result.applied_caption = applied_caption
            result.uploaded_video_name = normalized_filename

            job.facebook_post_url = result.post_url
            job.download_filename = normalized_filename
            job.set_status(JobStatus.PUBLISHED)
            logger.info(
                "facebook publish completed",
                extra={"post_url": result.post_url, "detected_signal": result.detected_signal},
            )
            return result
        except Exception as error:
            evidence = self.capture_failure_evidence(page, job.job_id, active_stage)
            signal_summary = ", ".join(evidence.visible_signals) or "none"
            detail = (
                f"Facebook publish failed during {active_stage}: {error}. "
                f"Page: {evidence.page_title or '-'} @ {evidence.page_url or '-'}. "
                f"Signals: {signal_summary}. "
                f"Screenshot: {evidence.screenshot_path}"
            )
            job.set_status(JobStatus.FAILED, error_message=detail)
            logger.error(
                "facebook publish failed",
                extra={
                    "stage": active_stage,
                    "page_url": evidence.page_url,
                    "screenshot_path": str(evidence.screenshot_path),
                    "visible_signals": ",".join(evidence.visible_signals),
                },
            )
            raise PublisherError(detail) from error


class BusinessSuitePublisher(FacebookPublisher):
    """Meta Business Suite-first publisher used by the production bot."""

    def __init__(
        self,
        settings: Settings | None = None,
        session_manager: SessionManager | None = None,
        selectors: BusinessSuiteSelectors | None = None,
        interaction_timeout_ms: int = DEFAULT_INTERACTION_TIMEOUT_MS,
        publish_timeout_ms: int = DEFAULT_PUBLISH_TIMEOUT_MS,
    ) -> None:
        super().__init__(
            settings=settings,
            session_manager=session_manager,
            interaction_timeout_ms=interaction_timeout_ms,
            publish_timeout_ms=publish_timeout_ms,
        )
        self.business_selectors = selectors or BusinessSuiteSelectors()

    @staticmethod
    def _page_content(page: object) -> str:
        content = getattr(page, "content", None)
        if callable(content):
            return content()
        return ""

    def _has_explicit_business_login_signal(self, page: object) -> bool:
        """Return true only for clear login surfaces, not transient loading HTML."""
        resolved_url = self._page_url(page).lower()
        page_title = self._page_title(page).lower()
        if any(marker in resolved_url for marker in ("/login", "login.php", "/checkpoint")):
            return True
        if any(marker in page_title for marker in ("log in", "login", "checkpoint")):
            return True
        return self._find_first_visible(page, self.business_selectors.explicit_login_indicators) is not None

    def _wait_for_business_suite_ready(self, page: object, job_id: str) -> str | None:
        """Wait for composer controls while allowing Business Suite shell spinners to settle."""
        logger = self.build_logger(job_id)
        end_time = monotonic() + (self.interaction_timeout_ms / 1000)

        while monotonic() <= end_time:
            ready = self._find_first_visible(page, self.business_selectors.composer_ready_indicators)
            if ready is not None:
                logger.info("Business Suite composer readiness detected", extra={"selector": ready[0]})
                return ready[0]

            if self._has_explicit_business_login_signal(page):
                logger.warning(
                    "Business Suite login surface detected",
                    extra={"resolved_url": self._page_url(page), "page_title": self._page_title(page)},
                )
                return None

            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                wait_for_timeout(500)
            else:
                break

        return None

    def _dismiss_optional_business_dialogs(self, page: object, job_id: str = "-") -> None:
        """Close non-essential Meta upsell dialogs such as WhatsApp prompts."""
        dismiss = self._find_first_visible(page, self.business_selectors.optional_dialog_dismiss_buttons)
        if dismiss is None:
            return
        self._click(dismiss[1])
        self.build_logger(job_id).info("dismissed optional Business Suite dialog", extra={"selector": dismiss[0]})

    def open_publish_surface(self, page: object, job_id: str = "-") -> SessionDiagnostic:
        """Open the Business Suite composer surface."""
        logger = self.build_logger(job_id)
        target_url = self.session_manager.build_business_suite_composer_url()
        logger.info("opening Business Suite composer", extra={"target_url": target_url})
        page.goto(target_url, wait_until="domcontentloaded")
        wait_for_load_state = getattr(page, "wait_for_load_state", None)
        if callable(wait_for_load_state):
            wait_for_load_state("domcontentloaded")

        ready_selector = self._wait_for_business_suite_ready(page, job_id=job_id)
        resolved_url = self._page_url(page)
        page_title = self._page_title(page)
        content = self._page_content(page)
        explicit_login = self._has_explicit_business_login_signal(page)
        legacy_login_hint = self.session_manager._looks_like_login_page(resolved_url, page_title, content)
        business_shell_url = "business.facebook.com" in resolved_url.lower()
        if explicit_login or (legacy_login_hint and not business_shell_url):
            raise PublisherError("Stored Business Suite session is not authenticated. Operator re-login is required.")
        if ready_selector is None:
            raise PublisherError(
                "Business Suite composer did not become ready before timeout. "
                "The page may still be loading or Meta may have changed the composer UI."
            )

        self._dismiss_optional_business_dialogs(page, job_id=job_id)
        logger.info("Business Suite composer opened", extra={"resolved_url": resolved_url, "ready_selector": ready_selector})
        return SessionDiagnostic(
            status=SessionHealthStatus.READY,
            target_url=target_url,
            resolved_url=resolved_url,
            page_title=page_title,
            message="Business Suite composer is reachable with the stored session.",
        )

    def _upload_with_file_chooser(self, page: object, video_path: Path, job_id: str = "-") -> bool:
        """Try Business Suite upload buttons that open a native file chooser."""
        expect_file_chooser = getattr(page, "expect_file_chooser", None)
        if not callable(expect_file_chooser):
            return False

        upload_entrypoint = self._wait_for_any(page, self.business_selectors.upload_entrypoints, 3_000)
        if upload_entrypoint is None:
            return False

        with expect_file_chooser() as chooser_info:
            self._click(upload_entrypoint[1])
        chooser = chooser_info.value
        set_files = getattr(chooser, "set_files", None)
        if not callable(set_files):
            return False
        set_files(str(video_path))
        self.build_logger(job_id).info("selected video through Business Suite file chooser")
        return True

    def upload_video(self, page: object, video_path: Path, job_id: str = "-") -> Path:
        """Upload a local video file through Business Suite."""
        resolved_path = Path(video_path)
        if not resolved_path.exists():
            raise PublisherError(f"Local video file does not exist: {resolved_path}")

        self._dismiss_optional_business_dialogs(page, job_id=job_id)
        upload_target = self._wait_for_any_attached(page, self.business_selectors.file_inputs, 5_000)
        if upload_target is not None:
            self._set_input_files(upload_target[1], resolved_path)
            self.build_logger(job_id).info("selected local video for Business Suite upload", extra={"selector": upload_target[0]})
            return resolved_path

        if self._upload_with_file_chooser(page, resolved_path, job_id=job_id):
            return resolved_path

        raise PublisherError("No Business Suite video upload control is available.")

    def apply_caption(self, page: object, caption: str, job_id: str = "-") -> str:
        """Populate the Business Suite caption editor."""
        resolved_caption = caption.strip()
        if not resolved_caption:
            self.build_logger(job_id).info("caption step skipped because no caption text was provided")
            return ""

        caption_target = self._wait_for_any(
            page,
            self.business_selectors.caption_editors,
            timeout_ms=self.interaction_timeout_ms,
        )
        if caption_target is None:
            raise PublisherError("No Business Suite caption editor became available.")

        self._fill(caption_target[1], resolved_caption)
        self.build_logger(job_id).info("Business Suite caption applied", extra={"selector": caption_target[0]})
        return resolved_caption

    @staticmethod
    def _playwright_text(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _collaborator_result_selectors(self, name: str, url: str) -> tuple[str, ...]:
        terms = tuple(dict.fromkeys(term.strip() for term in (name, url) if term.strip() and "'" not in term))
        selectors: list[str] = []
        for term in terms:
            safe_term = self._playwright_text(term)
            selectors.extend(
                (
                    f"text='{safe_term}'",
                    f"[role='option']:has-text('{safe_term}')",
                    f"[role='button']:has-text('{safe_term}')",
                    f"div:has-text('{safe_term}')",
                )
            )
        return tuple(selectors)

    def _open_collaborator_picker(self, page: object, job_id: str) -> str | None:
        entrypoint = self._wait_for_any(
            page,
            self.business_selectors.collaborator_entrypoints,
            timeout_ms=3_000,
            require_enabled=True,
        )
        if entrypoint is not None:
            self._click(entrypoint[1])
            return entrypoint[0]

        labels = (
            "Add collaborator",
            "Invite collaborator",
            "Collaborator",
            "Collaboration",
            "Thêm cộng tác viên",
            "Mời cộng tác viên",
            "Cộng tác viên",
            "Người cộng tác",
        )
        if self._click_left_side_button_by_dom_text(page, labels, timeout_ms=3_000):
            return "dom-text:collaborator-entrypoint"
        return None

    def _click_collaborator_result_by_dom_text(
        self,
        page: object,
        terms: tuple[str, ...],
        timeout_ms: int = 5_000,
    ) -> str | None:
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return None

        cleaned_terms = [term.strip().lower() for term in terms if term.strip()]
        if not cleaned_terms:
            return None

        end_time = monotonic() + (timeout_ms / 1000)
        while monotonic() <= end_time:
            target = evaluate(
                """
                (terms) => {
                    const visible = (element) => {
                        return !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
                    };
                    const enabled = (element) => {
                        return element.getAttribute('aria-disabled') !== 'true' && element.disabled !== true;
                    };
                    const textOf = (element) => {
                        return [
                            element.innerText || '',
                            element.textContent || '',
                            element.getAttribute('aria-label') || ''
                        ].join(' ').trim();
                    };
                    const candidates = Array.from(
                        document.querySelectorAll('[role="option"], [role="button"], button, li, div[aria-label]')
                    )
                        .map((element) => {
                            const text = textOf(element);
                            const rect = element.getBoundingClientRect();
                            return { element, text, rect };
                        })
                        .filter(({ element, text, rect }) => {
                            const lowered = text.toLocaleLowerCase('vi-VN');
                            return text
                                && visible(element)
                                && enabled(element)
                                && rect.width > 0
                                && rect.height > 0
                                && terms.some((term) => lowered.includes(term));
                        });
                    const target = candidates[0];
                    if (!target) {
                        return null;
                    }
                    const x = target.rect.left + target.rect.width / 2;
                    const y = target.rect.top + target.rect.height / 2;
                    target.element.click();
                    return { text: target.text, x, y };
                }
                """,
                cleaned_terms,
            )
            if target is not None:
                return str(target.get("text") or "dom-text:collaborator-result")

            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                wait_for_timeout(500)
            else:
                break

        return None

    @staticmethod
    def _press_tab(page: object, locator: object) -> bool:
        keyboard = getattr(page, "keyboard", None)
        keyboard_press = getattr(keyboard, "press", None)
        if callable(keyboard_press):
            keyboard_press("Tab")
            return True

        locator_press = getattr(locator, "press", None)
        if callable(locator_press):
            locator_press("Tab")
            return True

        return False

    def add_collaborator(self, page: object, job_id: str = "-") -> str:
        """Add the configured collaborator before the final publish/schedule action."""
        collaborator_name = self.settings.facebook_collaborator_name.strip()
        collaborator_url = self.settings.facebook_collaborator_url.strip()
        logger = self.build_logger(job_id)
        if not collaborator_name and not collaborator_url:
            logger.info("collaborator step skipped because no collaborator is configured")
            return "skipped"

        self._dismiss_optional_business_dialogs(page, job_id=job_id)
        entrypoint_selector = self._open_collaborator_picker(page, job_id=job_id)
        search_target = self._wait_for_any(
            page,
            self.business_selectors.collaborator_search_inputs,
            timeout_ms=self.interaction_timeout_ms,
        )
        if entrypoint_selector is None and search_target is None:
            raise PublisherError("No Business Suite collaborator entrypoint or search field became available.")
        if search_target is None:
            raise PublisherError("Business Suite collaborator picker did not expose a search field.")

        collaborator_value = collaborator_url or collaborator_name
        self._fill(search_target[1], collaborator_value)
        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if callable(wait_for_timeout):
            wait_for_timeout(1_500)
        tab_pressed = self._press_tab(page, search_target[1])

        logger.info(
            "Business Suite collaborator added",
            extra={
                "entrypoint_selector": entrypoint_selector,
                "search_selector": search_target[0],
                "tab_pressed": tab_pressed,
                "collaborator_name": collaborator_name,
                "collaborator_url": collaborator_url,
            },
        )
        return f"filled:{search_target[0]}"

    def _is_reels_composer(self, page: object) -> bool:
        """Return whether the active Business Suite surface is the Reels composer."""
        resolved_url = self._page_url(page).lower()
        if "reels_composer" in resolved_url:
            return True

        content = self._page_content(page).lower()
        return "reels" in content or "thước phim" in content

    def _click_right_side_button_by_dom_text(
        self,
        page: object,
        labels: tuple[str, ...],
        timeout_ms: int = 5_000,
    ) -> bool:
        """Click the right-side/footer action button by visible text."""
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return False

        end_time = monotonic() + (timeout_ms / 1000)
        while monotonic() <= end_time:
            target = evaluate(
                """
                (labels) => {
                    const candidates = Array.from(document.querySelectorAll('[role="button"], button'))
                        .map((element) => {
                            const text = (element.innerText || element.textContent || '').trim();
                            const rect = element.getBoundingClientRect();
                            const disabled = element.getAttribute('aria-disabled') === 'true'
                                || element.disabled === true;
                            const visible = !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
                            return {
                                element,
                                text,
                                disabled,
                                visible,
                                x: rect.left + rect.width / 2,
                                y: rect.top + rect.height / 2,
                            };
                        })
                        .filter((candidate) => {
                            return candidate.visible
                                && !candidate.disabled
                                && labels.some((label) => candidate.text.startsWith(label));
                        });

                    const rightSide = candidates.filter((candidate) => candidate.x > window.innerWidth * 0.65);
                    const target = rightSide[rightSide.length - 1] || (candidates.length > 1 ? candidates[candidates.length - 1] : null);
                    if (!target) {
                        return null;
                        }
                        return { x: target.x, y: target.y, text: target.text };
                }
                """,
                list(labels),
            )
            if target is not None:
                mouse = getattr(page, "mouse", None)
                click = getattr(mouse, "click", None)
                if callable(click):
                    click(float(target["x"]), float(target["y"]))
                else:
                    evaluate(
                        """
                        ({ x, y }) => {
                            const target = document.elementFromPoint(x, y);
                            if (target) {
                                target.click();
                            }
                        }
                        """,
                        {"x": target["x"], "y": target["y"]},
                    )
                return True

            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                wait_for_timeout(500)
            else:
                break

        return False

    def _click_reels_next_by_dom_text(self, page: object, timeout_ms: int = 5_000) -> bool:
        """Fallback click for Reels' Next button when Playwright text selectors miss Meta wrappers."""
        return self._click_right_side_button_by_dom_text(page, ("Next", "Tiếp"), timeout_ms=timeout_ms)

    def _click_left_side_button_by_dom_text(
        self,
        page: object,
        labels: tuple[str, ...],
        timeout_ms: int = 5_000,
    ) -> bool:
        """Click a left/content-panel button by visible text, avoiding footer actions."""
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return False

        end_time = monotonic() + (timeout_ms / 1000)
        while monotonic() <= end_time:
            target = evaluate(
                """
                (labels) => {
                    const candidates = Array.from(document.querySelectorAll('[role="button"], button'))
                        .map((element) => {
                            const text = (element.innerText || element.textContent || '').trim();
                            const rect = element.getBoundingClientRect();
                            const disabled = element.getAttribute('aria-disabled') === 'true'
                                || element.disabled === true;
                            const visible = !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
                            return {
                                text,
                                disabled,
                                visible,
                                x: rect.left + rect.width / 2,
                                y: rect.top + rect.height / 2,
                            };
                        })
                        .filter((candidate) => {
                            return candidate.visible
                                && !candidate.disabled
                                && candidate.x > 80
                                && candidate.x < window.innerWidth * 0.65
                                && labels.some((label) => candidate.text.startsWith(label));
                        });
                    const target = candidates[0];
                    if (!target) {
                        return null;
                    }
                    return { x: target.x, y: target.y, text: target.text };
                }
                """,
                list(labels),
            )
            if target is not None:
                mouse = getattr(page, "mouse", None)
                click = getattr(mouse, "click", None)
                if callable(click):
                    click(float(target["x"]), float(target["y"]))
                else:
                    evaluate(
                        """
                        ({ x, y }) => {
                            const target = document.elementFromPoint(x, y);
                            if (target) {
                                target.click();
                            }
                        }
                        """,
                        {"x": target["x"], "y": target["y"]},
                    )
                return True

            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                wait_for_timeout(500)
            else:
                break

        return False

    def _reels_final_step_ready(self, page: object, timeout_ms: int = 5_000) -> bool:
        """Return true only when Reels is on the final share/schedule settings step."""
        evaluate = getattr(page, "evaluate", None)
        end_time = monotonic() + (timeout_ms / 1000)

        while monotonic() <= end_time:
            if callable(evaluate):
                ready = bool(
                    evaluate(
                        """
                        () => {
                            const text = document.body ? (document.body.innerText || '') : '';
                            const finalMarkers = [
                                'Lựa chọn lịch đăng',
                                'Chia sẻ ngay',
                                'Lưu làm bản nháp',
                                'Schedule options',
                                'Share now',
                                'Save as draft'
                            ];
                            const hasFinalMarker = finalMarkers.some((marker) => text.includes(marker));
                            if (!hasFinalMarker) {
                                return false;
                            }
                            const actions = Array.from(document.querySelectorAll('[role="button"], button'))
                                .map((element) => {
                                    const label = (element.innerText || element.textContent || element.getAttribute('aria-label') || '').trim();
                                    const rect = element.getBoundingClientRect();
                                    const visible = !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
                                    const disabled = element.getAttribute('aria-disabled') === 'true' || element.disabled === true;
                                    return {
                                        label,
                                        visible,
                                        disabled,
                                        x: rect.left + rect.width / 2,
                                        y: rect.top + rect.height / 2,
                                    };
                                })
                                .filter((button) => {
                                    return button.visible
                                        && !button.disabled
                                        && button.x > window.innerWidth * 0.55
                                        && ['Chia sẻ', 'Share', 'Đăng', 'Publish', 'Lên lịch', 'Schedule']
                                            .some((label) => button.label.startsWith(label));
                                });
                            return actions.length > 0;
                        }
                        """
                    )
                )
                if ready:
                    return True
            else:
                content = self._page_content(page)
                if any(
                    marker in content
                    for marker in (
                        "Lựa chọn lịch đăng",
                        "Chia sẻ ngay",
                        "Lưu làm bản nháp",
                        "Schedule options",
                        "Share now",
                        "Save as draft",
                    )
                ):
                    return True

            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                wait_for_timeout(500)
            else:
                break

        return False

    def advance_reels_step(self, page: object, job_id: str = "-") -> str:
        """Advance from Reels upload/details to the final publish/schedule step."""
        if not self._is_reels_composer(page):
            self.build_logger(job_id).info("Reels advance skipped because current surface is not reels_composer")
            return "not-reels"

        clicked_selectors: list[str] = []
        ready_timeout_ms = min(self.interaction_timeout_ms, 10_000)
        if self._reels_final_step_ready(page, timeout_ms=1_000):
            return "already-final"

        for step_index in range(3):
            if self._click_reels_next_by_dom_text(page, timeout_ms=self.interaction_timeout_ms):
                clicked_selector = "dom-text:Next/Tiếp"
            else:
                next_target = self._wait_for_any(
                    page,
                    self.business_selectors.reels_next_buttons,
                    timeout_ms=5_000,
                    require_enabled=True,
                )
                if next_target is None:
                    raise PublisherError("No enabled Business Suite Reels next button became available.")
                self._click(next_target[1])
                clicked_selector = next_target[0]

            clicked_selectors.append(clicked_selector)
            self.build_logger(job_id).info(
                "Business Suite Reels next step triggered",
                extra={"selector": clicked_selector, "step_index": step_index + 1},
            )
            if self._reels_final_step_ready(page, timeout_ms=ready_timeout_ms):
                self.build_logger(job_id).info("Business Suite Reels final step ready")
                return " -> ".join(clicked_selectors)

        raise PublisherError("Business Suite Reels final publish/schedule step did not become ready.")

    @staticmethod
    def _business_calendar_label(value: datetime) -> str:
        """Return the English aria-label used by Meta's date-picker day buttons."""
        weekday = BUSINESS_CALENDAR_WEEKDAYS[value.weekday()]
        month = BUSINESS_CALENDAR_MONTHS[value.month - 1]
        return f"{weekday}, {value.day} {month} {value.year}"

    def _select_reels_schedule_mode(self, page: object, timeout_ms: int = 7_000) -> bool:
        """Select the Reels schedule tab and verify that schedule controls appeared."""
        def schedule_controls_visible() -> bool:
            return self._find_first_visible(page, self.business_selectors.schedule_datetime_inputs) is not None

        if schedule_controls_visible():
            return True

        schedule_mode = self._wait_for_any(
            page,
            self.business_selectors.schedule_mode_buttons,
            timeout_ms=2_000,
            require_enabled=True,
        )
        if schedule_mode is not None:
            self._click(schedule_mode[1])
            if self._wait_for_any(page, self.business_selectors.schedule_datetime_inputs, timeout_ms=2_000) is not None:
                return True

        if self._click_left_side_button_by_dom_text(page, ("Schedule", "Lên lịch"), timeout_ms=timeout_ms):
            return self._wait_for_any(page, self.business_selectors.schedule_datetime_inputs, timeout_ms=3_000) is not None

        return False

    def _click_reels_schedule_date(self, page: object, value: datetime, timeout_ms: int = 10_000) -> bool:
        """Choose a date in the Reels schedule calendar without filling the date input directly."""
        date_input = self._wait_for_any(page, self.business_selectors.schedule_datetime_inputs, 5_000)
        if date_input is None:
            return False

        self._click(date_input[1])
        target_label = self._business_calendar_label(value)
        target_day = value.day
        target_month = value.month
        target_year = value.year
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return False

        end_time = monotonic() + (timeout_ms / 1000)
        attempts = 0
        while monotonic() <= end_time and attempts < 36:
            result = evaluate(
                """
                ({ targetLabel, targetDay, targetMonth, targetYear }) => {
                    const visible = (element) => {
                        return !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
                    };
                    const enabled = (element) => {
                        return element.getAttribute('aria-disabled') !== 'true' && element.disabled !== true;
                    };
                    const text = (element) => (element.innerText || element.textContent || '').trim();
                    const aria = (element) => (element.getAttribute('aria-label') || '').trim();
                    const normalized = (value) => value.toLocaleLowerCase('vi-VN');
                    const target = Array.from(document.querySelectorAll('[role="button"], button'))
                        .find((element) => {
                            const label = aria(element);
                            const buttonText = text(element);
                            const labelText = normalized(`${label} ${buttonText}`);
                            return visible(element)
                                && enabled(element)
                                && (
                                    label === targetLabel
                                    || (
                                        buttonText === String(targetDay)
                                        && labelText.includes(String(targetYear))
                                        && (
                                            labelText.includes(String(targetMonth))
                                            || labelText.includes(targetLabel.toLocaleLowerCase('en-US').split(' ')[2])
                                        )
                                    )
                                );
                        });
                    if (target) {
                        const rect = target.getBoundingClientRect();
                        target.click();
                        return {
                            status: 'clicked-date',
                            x: rect.left + rect.width / 2,
                            y: rect.top + rect.height / 2,
                        };
                    }

                    const grid = Array.from(document.querySelectorAll('[role="grid"]'))
                        .find((element) => {
                            const rect = element.getBoundingClientRect();
                            return visible(element) && rect.bottom >= 0 && rect.top <= window.innerHeight;
                        });
                    if (!grid) {
                        return { status: 'no-grid' };
                    }
                    const gridRect = grid.getBoundingClientRect();
                    const next = Array.from(document.querySelectorAll('[role="button"], button'))
                        .map((element) => {
                            const rect = element.getBoundingClientRect();
                            return { element, rect };
                        })
                        .filter(({ element, rect }) => {
                            return visible(element)
                                && enabled(element)
                                && rect.left >= gridRect.right - 70
                                && rect.left <= gridRect.right + 30
                                && rect.top >= gridRect.top - 80
                                && rect.top <= gridRect.top + 5;
                        })
                        .sort((left, right) => right.rect.left - left.rect.left)[0];
                    if (!next) {
                        return { status: 'no-next-month' };
                    }
                    next.element.click();
                    return { status: 'clicked-next-month' };
                }
                """,
                {
                    "targetLabel": target_label,
                    "targetDay": target_day,
                    "targetMonth": target_month,
                    "targetYear": target_year,
                },
            )
            if result and result.get("status") == "clicked-date":
                return True

            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                wait_for_timeout(400)
            attempts += 1

        return False

    def _fill_reels_schedule_time(self, page: object, value: datetime) -> None:
        """Set Reels schedule hour/minute using keyboard events that Meta's inputs observe."""
        locator = getattr(page, "locator", None)
        keyboard = getattr(page, "keyboard", None)
        if not callable(locator) or keyboard is None:
            return

        spinbuttons = locator('input[role="spinbutton"]')
        for index, text in ((0, value.strftime("%H")), (1, value.strftime("%M"))):
            field = spinbuttons.nth(index)
            try:
                field.click(timeout=5_000)
                keyboard.press("Control+A")
                keyboard.type(text)
                keyboard.press("Tab")
            except Exception:
                continue

    def _apply_schedule_time(self, page: object, job: Job, job_id: str) -> None:
        if job.scheduled_at is None:
            raise PublisherError("Scheduled jobs require scheduled_at.")

        if self._is_reels_composer(page):
            schedule_mode_selected = self._select_reels_schedule_mode(page)
        else:
            schedule_mode = self._wait_for_any(page, self.business_selectors.schedule_mode_buttons, 5_000)
            schedule_mode_selected = schedule_mode is not None
            if schedule_mode is not None:
                self._click(schedule_mode[1])

        if schedule_mode_selected:
            self.build_logger(job_id).info("Business Suite schedule mode selected")

        if self._is_reels_composer(page):
            if not self._click_reels_schedule_date(page, job.scheduled_at):
                raise PublisherError("Business Suite Reels schedule date picker did not expose the requested date.")
            self._fill_reels_schedule_time(page, job.scheduled_at)
            self.build_logger(job_id).info("Business Suite schedule time applied", extra={"scheduled_at": job.scheduled_at.isoformat()})
            return

        datetime_input = self._wait_for_any(page, self.business_selectors.schedule_datetime_inputs, 5_000)
        if datetime_input is not None:
            datetime_value = job.scheduled_at.strftime("%Y-%m-%dT%H:%M")
            date_value = job.scheduled_at.strftime("%d/%m/%Y")
            selector = datetime_input[0]
            if "datetime-local" in selector:
                self._fill(datetime_input[1], datetime_value)
            else:
                self._fill(datetime_input[1], date_value)
            self.build_logger(job_id).info(
                "Business Suite schedule time applied",
                extra={"scheduled_at": job.scheduled_at.isoformat()},
            )

        hour_input = self._wait_for_any(page, self.business_selectors.schedule_hour_inputs, 2_000)
        if hour_input is not None:
            self._fill(hour_input[1], job.scheduled_at.strftime("%H"))

        minute_input = self._wait_for_any(page, self.business_selectors.schedule_minute_inputs, 2_000)
        if minute_input is not None:
            self._fill(minute_input[1], job.scheduled_at.strftime("%M"))

    def trigger_publish(self, page: object, job_id: str = "-") -> str:
        """Click the Business Suite publish action."""
        if self._is_reels_composer(page) and self._click_right_side_button_by_dom_text(
            page,
            ("Share", "Chia sẻ", "Publish", "Đăng"),
            timeout_ms=self.interaction_timeout_ms,
        ):
            selector = "dom-text:Share/Chia sẻ"
            self.build_logger(job_id).info("Business Suite publish action triggered", extra={"selector": selector})
            return selector

        publish_target = self._wait_for_any(
            page,
            self.business_selectors.publish_buttons,
            timeout_ms=self.interaction_timeout_ms,
            require_enabled=True,
        )
        if publish_target is None:
            raise PublisherError("No enabled Business Suite publish button became available.")
        self._click(publish_target[1])
        self.build_logger(job_id).info("Business Suite publish action triggered", extra={"selector": publish_target[0]})
        return publish_target[0]

    def trigger_schedule(self, page: object, job: Job, job_id: str = "-") -> str:
        """Click the Business Suite schedule action."""
        self._apply_schedule_time(page, job, job_id)
        if self._is_reels_composer(page) and self._click_right_side_button_by_dom_text(
            page,
            ("Schedule", "Lên lịch"),
            timeout_ms=self.interaction_timeout_ms,
        ):
            selector = "dom-text:Schedule/Lên lịch"
            self.build_logger(job_id).info("Business Suite schedule action triggered", extra={"selector": selector})
            return selector

        schedule_target = self._wait_for_any(
            page,
            self.business_selectors.schedule_submit_buttons,
            timeout_ms=self.interaction_timeout_ms,
            require_enabled=True,
        )
        if schedule_target is None:
            raise PublisherError("No enabled Business Suite schedule button became available.")
        self._click(schedule_target[1])
        self.build_logger(job_id).info("Business Suite schedule action triggered", extra={"selector": schedule_target[0]})
        return schedule_target[0]

    def wait_for_business_suite_outcome(self, page: object, job: Job, job_id: str = "-") -> PublishResult:
        """Wait for Business Suite-native publish or schedule signals."""
        selectors = (
            self.business_selectors.scheduled_indicators
            if job.publish_mode == "scheduled"
            else self.business_selectors.success_indicators
        )
        content_table = "scheduled_posts" if job.publish_mode == "scheduled" else "published_posts"
        status = JobStatus.SCHEDULED if job.publish_mode == "scheduled" else JobStatus.PUBLISHED
        end_time = monotonic() + (self.publish_timeout_ms / 1000)

        while monotonic() <= end_time:
            self._dismiss_optional_business_dialogs(page, job_id=job_id)
            success = self._find_first_visible(page, selectors)
            if success is not None:
                return PublishResult(
                    success=True,
                    post_url=self._page_url(page) or self.session_manager.build_business_suite_content_url(content_table),
                    applied_caption="",
                    uploaded_video_name="",
                    detected_signal=success[0],
                    resolved_url=self._page_url(page),
                )
            failure = self._find_first_visible(page, self.business_selectors.failure_indicators)
            if failure is not None:
                raise PublisherError(f"Business Suite reported a failure via selector: {failure[0]}")

            wait_for_timeout = getattr(page, "wait_for_timeout", None)
            if callable(wait_for_timeout):
                wait_for_timeout(500)
            else:
                break

        content_url = self.session_manager.build_business_suite_content_url(content_table)
        page.goto(content_url, wait_until="domcontentloaded")
        wait_for_load_state = getattr(page, "wait_for_load_state", None)
        if callable(wait_for_load_state):
            wait_for_load_state("domcontentloaded")

        caption_signal = f"text='{job.caption}'" if job.caption else selectors[0]
        content_signal = self._find_first_visible(page, (caption_signal,) + selectors)
        if content_signal is None:
            raise PublisherError("Timed out while waiting for Business Suite publish completion signals.")

        job.set_status(status)
        return PublishResult(
            success=True,
            post_url=content_url,
            applied_caption="",
            uploaded_video_name="",
            detected_signal=content_signal[0],
            resolved_url=self._page_url(page),
        )

    def publish_job(self, page: object, job: Job, default_caption: str = "") -> PublishResult:
        """Drive the full Business Suite upload and publish/schedule workflow."""
        logger = self.build_logger(job.job_id)
        applied_caption = self.resolve_caption(job.caption, default_caption)
        active_stage = "open-business-suite"

        if job.download_path is None:
            detail = "Job does not have a local download path ready for publishing."
            job.set_status(JobStatus.FAILED, error_message=detail)
            raise PublisherError(detail)

        try:
            job.set_status(JobStatus.PUBLISHING)
            normalized_filename = job.download_filename or job.download_path.name
            logger.info(
                "starting Business Suite publish flow",
                extra={
                    "download_path": str(job.download_path),
                    "publish_mode": job.publish_mode,
                    "normalized_filename": normalized_filename,
                },
            )

            self.open_publish_surface(page, job_id=job.job_id)
            active_stage = "upload-video"
            self.upload_video(page, job.download_path, job_id=job.job_id)
            active_stage = "apply-caption"
            applied_caption = self.apply_caption(page, applied_caption, job_id=job.job_id)
            active_stage = "add-collaborator"
            self.add_collaborator(page, job_id=job.job_id)
            active_stage = "advance-reels-step"
            self.advance_reels_step(page, job_id=job.job_id)

            if job.publish_mode == "scheduled":
                active_stage = "trigger-schedule"
                self.trigger_schedule(page, job, job_id=job.job_id)
            else:
                active_stage = "trigger-publish"
                self.trigger_publish(page, job_id=job.job_id)

            active_stage = "wait-for-business-suite-outcome"
            result = self.wait_for_business_suite_outcome(page, job, job_id=job.job_id)
            result.applied_caption = applied_caption
            result.uploaded_video_name = normalized_filename
            job.facebook_post_url = result.post_url
            job.download_filename = normalized_filename
            if job.status is JobStatus.PUBLISHING:
                job.set_status(JobStatus.SCHEDULED if job.publish_mode == "scheduled" else JobStatus.PUBLISHED)
            logger.info("Business Suite publish flow completed", extra={"status": job.status.value})
            return result
        except Exception as error:
            evidence = self.capture_failure_evidence(page, job.job_id, active_stage)
            signal_summary = ", ".join(evidence.visible_signals) or "none"
            detail = (
                f"Business Suite publish failed during {active_stage}: {error}. "
                f"Page: {evidence.page_title or '-'} @ {evidence.page_url or '-'}. "
                f"Signals: {signal_summary}. "
                f"Screenshot: {evidence.screenshot_path}"
            )
            job.set_status(JobStatus.FAILED, error_message=detail)
            logger.error("Business Suite publish failed", extra={"stage": active_stage})
            raise PublisherError(detail) from error


def create_publisher(settings: Settings, session_manager: SessionManager) -> FacebookPublisher:
    """Create the configured publisher implementation."""
    provider = settings.facebook_publish_provider.strip().lower()
    if provider in {"business_suite", "business-suite", "meta_business_suite"}:
        return BusinessSuitePublisher(settings=settings, session_manager=session_manager)
    return FacebookPublisher(settings=settings, session_manager=session_manager)
