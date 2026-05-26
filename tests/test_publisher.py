import logging
from pathlib import Path
from datetime import datetime

import pytest

from app.config import Settings
from app.core.logger import configure_logging
from app.models.job import Job, JobStatus
from app.services.publisher import BusinessSuitePublisher, FacebookPublisher, PublisherError, create_publisher
from app.services.session_manager import SessionManager


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="123456:test-token",
        TELEGRAM_ALLOWED_USER_IDS="123",
        FACEBOOK_PAGE_URL="https://facebook.com/example.page",
        DOWNLOAD_DIR=tmp_path / "downloads",
        SESSION_DIR=tmp_path / "sessions",
        SCREENSHOT_DIR=tmp_path / "screenshots",
        LOG_DIR=tmp_path / "logs",
    )


class FakeLocator:
    def __init__(self, selector: str, visible: bool = False, enabled: bool = True) -> None:
        self.selector = selector
        self.visible = visible
        self.enabled = enabled
        self.click_calls = 0
        self.fill_calls: list[str] = []
        self.typed_calls: list[str] = []
        self.input_files_calls: list[str] = []
        self.on_click = None
        self.on_fill = None
        self.on_input_files = None

    @property
    def first(self) -> "FakeLocator":
        return self

    def count(self) -> int:
        return 1 if self.visible else 0

    def is_visible(self) -> bool:
        return self.visible

    def is_enabled(self) -> bool:
        return self.enabled

    def wait_for(self, state: str = "visible", timeout: int = 0) -> None:
        if state == "visible" and not self.visible:
            raise RuntimeError(f"{self.selector} is not visible")

    def click(self) -> None:
        self.click_calls += 1
        if callable(self.on_click):
            self.on_click()

    def fill(self, text: str) -> None:
        self.fill_calls.append(text)
        if callable(self.on_fill):
            self.on_fill(text)

    def type(self, text: str) -> None:
        self.typed_calls.append(text)
        if callable(self.on_fill):
            self.on_fill(text)

    def press(self, key: str) -> None:
        pass

    def set_input_files(self, path: str) -> None:
        self.input_files_calls.append(path)
        if callable(self.on_input_files):
            self.on_input_files(path)


class FakeKeyboard:
    def __init__(self) -> None:
        self.press_calls: list[str] = []

    def press(self, key: str) -> None:
        self.press_calls.append(key)


class FakePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self._title = "Example Fanpage"
        self._content = "<html>ready</html>"
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_states: list[str] = []
        self.timeout_calls: list[int] = []
        self.screenshot_calls: list[tuple[str, bool]] = []
        self.locators: dict[str, FakeLocator] = {}
        self.keyboard = FakeKeyboard()

    def set_locator(self, selector: str, locator: FakeLocator) -> FakeLocator:
        self.locators[selector] = locator
        return locator

    def locator(self, selector: str) -> FakeLocator:
        return self.locators.setdefault(selector, FakeLocator(selector, visible=False))

    def goto(self, url: str, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.url = url

    def wait_for_load_state(self, state: str) -> None:
        self.wait_states.append(state)

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.timeout_calls.append(timeout_ms)

    def title(self) -> str:
        return self._title

    def content(self) -> str:
        return self._content

    def screenshot(self, path: str, full_page: bool) -> None:
        self.screenshot_calls.append((path, full_page))
        Path(path).write_text("fake screenshot", encoding="utf-8")


def build_ready_page() -> FakePage:
    page = FakePage("https://facebook.com/example.page")
    compose = page.set_locator("[aria-label='Create post']", FakeLocator("[aria-label='Create post']", visible=True))
    file_input = page.set_locator("input[type='file'][accept*='video']", FakeLocator("input[type='file'][accept*='video']"))
    caption = page.set_locator(
        "div[role='textbox'][contenteditable='true']",
        FakeLocator("div[role='textbox'][contenteditable='true']"),
    )
    publish = page.set_locator("[aria-label='Publish']", FakeLocator("[aria-label='Publish']"))
    success = page.set_locator("text='Post published'", FakeLocator("text='Post published'"))
    failure = page.set_locator("text='Something went wrong'", FakeLocator("text='Something went wrong'"))

    def show_editor() -> None:
        file_input.visible = True
        caption.visible = True
        publish.visible = True
        publish.enabled = True

    def mark_uploaded(_: str) -> None:
        caption.visible = True
        publish.visible = True
        publish.enabled = True

    def mark_success() -> None:
        success.visible = True
        page.url = "https://facebook.com/example.page/posts/123"

    compose.on_click = show_editor
    file_input.on_input_files = mark_uploaded
    publish.on_click = mark_success
    failure.visible = False
    return page


def test_publisher_reuses_session_manager_and_exposes_selector_contract(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    session_manager = SessionManager(settings)
    publisher = FacebookPublisher(settings=settings, session_manager=session_manager)

    assert publisher.session_manager is session_manager
    assert "[aria-label='Create post']" in publisher.selectors.composer_entrypoints
    assert "input[type='file'][accept*='video']" in publisher.selectors.file_inputs


def test_create_publisher_uses_business_suite_by_default(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    session_manager = SessionManager(settings)

    publisher = create_publisher(settings, session_manager)

    assert isinstance(publisher, BusinessSuitePublisher)


def test_create_publisher_keeps_legacy_facebook_fallback(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings.facebook_publish_provider = "legacy_facebook"
    session_manager = SessionManager(settings)

    publisher = create_publisher(settings, session_manager)

    assert type(publisher) is FacebookPublisher


def test_business_suite_open_waits_for_composer_ready_before_auth_failure(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    page = FakePage("about:blank")
    page._title = "Meta Business Suite"
    page._content = "<html>Business Suite shell mentions login while loading</html>"
    ready = page.set_locator("[aria-label='Add video']", FakeLocator("[aria-label='Add video']", visible=False))
    publisher = BusinessSuitePublisher(settings=settings, interaction_timeout_ms=1_000)

    def settle_loading(timeout_ms: int) -> None:
        page.timeout_calls.append(timeout_ms)
        ready.visible = True

    page.wait_for_timeout = settle_loading

    diagnostic = publisher.open_publish_surface(page, job_id="job-business-ready")

    assert diagnostic.status.value == "ready"
    assert page.goto_calls[0][0].startswith("https://business.facebook.com/latest/reels_composer/")


def test_business_suite_open_requires_relogin_for_explicit_login_surface(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    page = FakePage("about:blank")
    page._title = "Log in to Facebook"
    page.set_locator("input[name='email']", FakeLocator("input[name='email']", visible=True))
    publisher = BusinessSuitePublisher(settings=settings, interaction_timeout_ms=500)

    with pytest.raises(PublisherError, match="Operator re-login is required"):
        publisher.open_publish_surface(page, job_id="job-business-login")


def test_business_suite_open_dismisses_optional_whatsapp_prompt(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    page = FakePage("about:blank")
    page.set_locator("[aria-label='Add video']", FakeLocator("[aria-label='Add video']", visible=True))
    later = page.set_locator("[aria-label='Lúc khác']", FakeLocator("[aria-label='Lúc khác']", visible=True))
    publisher = BusinessSuitePublisher(settings=settings, interaction_timeout_ms=500)

    publisher.open_publish_surface(page, job_id="job-whatsapp-prompt")

    assert later.click_calls == 1


def test_business_suite_reels_advance_clicks_next_before_publish_controls(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    page = FakePage("https://business.facebook.com/latest/reels_composer/?asset_id=123&context_ref=HOME")
    next_button = page.set_locator("[aria-label='Tiếp']", FakeLocator("[aria-label='Tiếp']", visible=True))
    publish_button = page.set_locator("[aria-label='Đăng']", FakeLocator("[aria-label='Đăng']", visible=False))
    publisher = BusinessSuitePublisher(settings=settings, interaction_timeout_ms=500)

    def reveal_publish_controls() -> None:
        publish_button.visible = True
        page._content = "<html>Lựa chọn lịch đăng Chia sẻ ngay Lên lịch</html>"

    next_button.on_click = reveal_publish_controls

    selector = publisher.advance_reels_step(page, job_id="job-reels-next")

    assert selector == "[aria-label='Tiếp']"
    assert next_button.click_calls == 1
    assert publish_button.visible is True


def test_business_suite_calendar_label_matches_meta_datepicker_format(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    publisher = BusinessSuitePublisher(settings=settings)

    label = publisher._business_calendar_label(datetime(2026, 5, 1, 12, 30))

    assert label == "Friday, 1 May 2026"


def test_business_suite_selects_reels_schedule_mode_before_date_picker(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    page = FakePage("https://business.facebook.com/latest/reels_composer/?asset_id=123&context_ref=HOME")
    schedule_tab = page.set_locator("text='Lên lịch'", FakeLocator("text='Lên lịch'", visible=True))
    date_input = page.set_locator("input[aria-label*='Ngày']", FakeLocator("input[aria-label*='Ngày']", visible=False))
    publisher = BusinessSuitePublisher(settings=settings, interaction_timeout_ms=500)

    def reveal_date_input() -> None:
        date_input.visible = True

    schedule_tab.on_click = reveal_date_input

    assert publisher._select_reels_schedule_mode(page, timeout_ms=500) is True
    assert schedule_tab.click_calls == 1
    assert date_input.visible is True


def test_business_suite_adds_configured_collaborator(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings.facebook_collaborator_url = "https://www.facebook.com/profile.php?id=100090799088843"
    settings.facebook_collaborator_name = "FamilyTV"
    page = FakePage("https://business.facebook.com/latest/reels_composer/?asset_id=123&context_ref=HOME")
    entrypoint = page.set_locator(
        "[aria-label*='Collaborator']",
        FakeLocator("[aria-label*='Collaborator']", visible=True),
    )
    search = page.set_locator("input[placeholder*='Search']", FakeLocator("input[placeholder*='Search']", visible=False))
    publisher = BusinessSuitePublisher(settings=settings, interaction_timeout_ms=500)

    def open_picker() -> None:
        search.visible = True

    entrypoint.on_click = open_picker

    selector = publisher.add_collaborator(page, job_id="job-collab")

    assert selector == "filled:input[placeholder*='Search']"
    assert entrypoint.click_calls == 1
    assert search.fill_calls == ["https://www.facebook.com/profile.php?id=100090799088843"]
    assert page.timeout_calls[-1] == 1_500
    assert page.keyboard.press_calls == ["Tab"]


def test_business_suite_adds_collaborator_from_visible_search_field(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings.facebook_collaborator_url = "https://www.facebook.com/profile.php?id=100090799088843"
    settings.facebook_collaborator_name = "FamilyTV"
    page = FakePage("https://business.facebook.com/latest/reels_composer/?asset_id=123&context_ref=HOME")
    search = page.set_locator("input[placeholder*='URL Trang']", FakeLocator("input[placeholder*='URL Trang']", visible=True))
    publisher = BusinessSuitePublisher(settings=settings, interaction_timeout_ms=500)

    selector = publisher.add_collaborator(page, job_id="job-direct-collab")

    assert selector == "filled:input[placeholder*='URL Trang']"
    assert search.fill_calls == ["https://www.facebook.com/profile.php?id=100090799088843"]
    assert page.timeout_calls[-1] == 1_500
    assert page.keyboard.press_calls == ["Tab"]


def test_open_publish_surface_clicks_composer_after_session_preflight(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    page = build_ready_page()
    publisher = FacebookPublisher(settings=settings, interaction_timeout_ms=500)

    diagnostic = publisher.open_publish_surface(page, job_id="job-001")

    assert diagnostic.status.value == "ready"
    assert page.goto_calls == [("https://facebook.com/example.page", "domcontentloaded")]
    assert page.locator("[aria-label='Create post']").click_calls == 1


def test_publish_job_uploads_video_applies_caption_and_marks_job_published(tmp_path: Path, caplog) -> None:
    configure_logging("INFO", tmp_path / "logs")
    caplog.set_level(logging.INFO)
    settings = build_settings(tmp_path)
    download_path = settings.download_dir / "clip.mp4"
    download_path.parent.mkdir(parents=True, exist_ok=True)
    download_path.write_text("video", encoding="utf-8")
    page = build_ready_page()
    publisher = FacebookPublisher(settings=settings, interaction_timeout_ms=500, publish_timeout_ms=500)
    job = Job(
        source_url="https://example.com/video",
        caption="Caption tu Telegram",
        download_path=download_path,
        download_filename="clip-da-normalize.mp4",
    )

    result = publisher.publish_job(page, job)

    assert result.success is True
    assert result.applied_caption == "Caption tu Telegram"
    assert result.uploaded_video_name == "clip-da-normalize.mp4"
    assert result.post_url.endswith("/posts/123")
    assert job.status is JobStatus.PUBLISHED
    assert job.facebook_post_url == result.post_url
    assert job.download_filename == "clip-da-normalize.mp4"
    assert page.locator("input[type='file'][accept*='video']").input_files_calls == [str(download_path)]
    assert page.locator("div[role='textbox'][contenteditable='true']").fill_calls == ["Caption tu Telegram"]
    assert any(record.job_id == job.job_id for record in caplog.records)


def test_publish_job_uses_default_caption_when_job_caption_is_empty(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    download_path = settings.download_dir / "clip.mp4"
    download_path.parent.mkdir(parents=True, exist_ok=True)
    download_path.write_text("video", encoding="utf-8")
    page = build_ready_page()
    publisher = FacebookPublisher(settings=settings, interaction_timeout_ms=500, publish_timeout_ms=500)
    job = Job(source_url="https://example.com/video", caption="", download_path=download_path)

    result = publisher.publish_job(page, job, default_caption="Caption mac dinh")

    assert result.applied_caption == "Caption mac dinh"
    assert page.locator("div[role='textbox'][contenteditable='true']").fill_calls == ["Caption mac dinh"]


def test_publish_job_captures_failure_screenshot_and_sets_job_failed(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    download_path = settings.download_dir / "clip.mp4"
    download_path.parent.mkdir(parents=True, exist_ok=True)
    download_path.write_text("video", encoding="utf-8")
    page = build_ready_page()
    failure = page.locator("text='Something went wrong'")
    publish = page.locator("[aria-label='Publish']")

    def mark_failure() -> None:
        failure.visible = True

    publish.on_click = mark_failure

    publisher = FacebookPublisher(settings=settings, interaction_timeout_ms=500, publish_timeout_ms=500)
    job = Job(source_url="https://example.com/video", caption="Se fail", download_path=download_path)

    with pytest.raises(PublisherError, match="Screenshot:"):
        publisher.publish_job(page, job)

    assert job.status is JobStatus.FAILED
    assert job.error_message is not None
    assert "wait-for-outcome" in job.error_message
    assert "Something went wrong" in job.error_message
    assert "Screenshot:" in job.error_message
    assert len(page.screenshot_calls) == 1
    screenshot_path = Path(page.screenshot_calls[0][0])
    assert screenshot_path.exists()
