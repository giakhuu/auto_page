from pathlib import Path

from app.config import Settings
from app.core.paths import ensure_runtime_dirs, get_runtime_dirs


def test_settings_parse_allowed_user_ids_and_bool() -> None:
    settings = Settings(
        TELEGRAM_ALLOWED_USER_IDS="1, 2,3",
        PLAYWRIGHT_HEADLESS="true",
    )

    assert settings.telegram_allowed_user_ids == [1, 2, 3]
    assert settings.playwright_headless is True


def test_settings_use_default_runtime_paths() -> None:
    settings = Settings()

    assert settings.download_dir == Path("data/downloads")
    assert settings.session_dir == Path("data/sessions")
    assert settings.screenshot_dir == Path("data/screenshots")
    assert settings.log_dir == Path("logs")
    assert settings.facebook_publish_provider == "business_suite"
    assert settings.facebook_business_suite_url == "https://business.facebook.com/"
    assert settings.caption_editor_enabled is False
    assert settings.caption_editor_provider == "gemini"
    assert settings.caption_editor_model == "gemini-2.5-flash"


def test_ensure_runtime_dirs_creates_expected_directories(tmp_path: Path) -> None:
    settings = Settings(
        DOWNLOAD_DIR=tmp_path / "downloads",
        SESSION_DIR=tmp_path / "sessions",
        SCREENSHOT_DIR=tmp_path / "screenshots",
        LOG_DIR=tmp_path / "logs",
    )

    created = ensure_runtime_dirs(settings)

    assert created == get_runtime_dirs(settings)
    assert all(path.exists() for path in created)
