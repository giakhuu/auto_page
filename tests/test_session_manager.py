import logging
from types import SimpleNamespace
from pathlib import Path

from app.core.logger import configure_logging
from app.config import Settings
from app.services.session_manager import SessionHealthStatus, SessionManager


def build_settings(tmp_path: Path, headless: bool = False) -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="123456:test-token",
        TELEGRAM_ALLOWED_USER_IDS="123",
        FACEBOOK_PAGE_URL="https://facebook.com/example.page",
        PLAYWRIGHT_HEADLESS=headless,
        DOWNLOAD_DIR=tmp_path / "downloads",
        SESSION_DIR=tmp_path / "sessions",
        SCREENSHOT_DIR=tmp_path / "screenshots",
        LOG_DIR=tmp_path / "logs",
    )


def test_session_manager_uses_project_controlled_paths(tmp_path: Path) -> None:
    manager = SessionManager(build_settings(tmp_path))

    created_paths = manager.ensure_session_dirs()

    assert manager.session_root == tmp_path / "sessions" / "facebook"
    assert manager.user_data_dir == tmp_path / "sessions" / "facebook" / "user-data"
    assert manager.storage_state_path == tmp_path / "sessions" / "facebook" / "storage-state.json"
    assert created_paths == [manager.session_root, manager.user_data_dir]
    assert all(path.exists() for path in created_paths)


def test_bootstrap_config_reflects_settings(tmp_path: Path) -> None:
    manager = SessionManager(build_settings(tmp_path, headless=True))

    config = manager.build_bootstrap_config()

    assert config.user_data_dir == tmp_path / "sessions" / "facebook" / "user-data"
    assert config.storage_state_path == tmp_path / "sessions" / "facebook" / "storage-state.json"
    assert config.downloads_path == tmp_path / "downloads"
    assert config.headless is True
    assert "--disable-notifications" in config.launch_args


def test_business_suite_urls_include_configured_asset_id(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings.facebook_business_asset_id = "123456"
    manager = SessionManager(settings)

    assert manager.build_business_suite_composer_url().endswith("/latest/reels_composer/?asset_id=123456&context_ref=HOME")
    assert "asset_id=123456" in manager.build_business_suite_content_url("scheduled_posts")
    assert "content_table=scheduled_posts" in manager.build_business_suite_content_url("scheduled_posts")


class FakePage:
    def __init__(self, url: str, title: str, content: str, error: Exception | None = None) -> None:
        self.url = url
        self._title = title
        self._content = content
        self._error = error
        self.goto_calls: list[tuple[str, str]] = []

    def goto(self, url: str, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        if self._error is not None:
            raise self._error

    def wait_for_load_state(self, state: str) -> None:
        return None

    def title(self) -> str:
        return self._title

    def content(self) -> str:
        return self._content


def test_check_fanpage_reachability_reports_ready(tmp_path: Path, caplog) -> None:
    configure_logging("INFO", tmp_path / "logs")
    caplog.set_level(logging.INFO)
    manager = SessionManager(build_settings(tmp_path))
    page = FakePage(
        url="https://facebook.com/example.page",
        title="Example Page",
        content="<html>Page content</html>",
    )

    diagnostic = manager.check_fanpage_reachability(page, job_id="job-123")

    assert diagnostic.status is SessionHealthStatus.READY
    assert page.goto_calls == [("https://facebook.com/example.page", "domcontentloaded")]
    assert any(record.job_id == "job-123" for record in caplog.records)


def test_check_fanpage_reachability_reports_login_required(tmp_path: Path) -> None:
    manager = SessionManager(build_settings(tmp_path))
    page = FakePage(
        url="https://facebook.com/login",
        title="Facebook - Log In",
        content="<html>Log in to continue</html>",
    )

    diagnostic = manager.check_fanpage_reachability(page)

    assert diagnostic.status is SessionHealthStatus.LOGIN_REQUIRED
    assert "re-login" in diagnostic.message.lower()


def test_check_fanpage_reachability_reports_navigation_failure(tmp_path: Path) -> None:
    manager = SessionManager(build_settings(tmp_path))
    page = FakePage(
        url="",
        title="",
        content="",
        error=RuntimeError("timeout while navigating"),
    )

    diagnostic = manager.check_fanpage_reachability(page)

    assert diagnostic.status is SessionHealthStatus.NAVIGATION_FAILED
    assert "timeout while navigating" in diagnostic.message
