import logging
from pathlib import Path

from app.config import Settings
from app.main import bootstrap, build_runtime_components


def test_bootstrap_creates_runtime_directories(tmp_path: Path, caplog) -> None:
    settings = Settings(
        TELEGRAM_BOT_TOKEN="secret-token",
        TELEGRAM_ALLOWED_USER_IDS="123,456",
        FACEBOOK_PAGE_URL="https://facebook.example/page",
        DOWNLOAD_DIR=tmp_path / "downloads",
        SESSION_DIR=tmp_path / "sessions",
        SCREENSHOT_DIR=tmp_path / "screenshots",
        LOG_DIR=tmp_path / "logs",
    )

    caplog.set_level(logging.INFO)
    created_dirs = bootstrap(settings)

    assert all(path.exists() for path in created_dirs)
    assert "secret-token" not in caplog.text
    assert "runtime_dirs" in caplog.text


def test_build_runtime_components_wires_orchestrator_into_bot_data(tmp_path: Path) -> None:
    settings = Settings(
        TELEGRAM_BOT_TOKEN="123456:test-token",
        TELEGRAM_ALLOWED_USER_IDS="123",
        FACEBOOK_PAGE_URL="https://facebook.example/page",
        DOWNLOAD_DIR=tmp_path / "downloads",
        SESSION_DIR=tmp_path / "sessions",
        SCREENSHOT_DIR=tmp_path / "screenshots",
        LOG_DIR=tmp_path / "logs",
    )

    job_manager, application = build_runtime_components(settings)

    assert application.bot_data["job_manager"] is job_manager
    assert application.bot_data["orchestrator"] is not None
