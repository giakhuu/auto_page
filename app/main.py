"""Application bootstrap entrypoint."""

from __future__ import annotations

import asyncio
from pathlib import Path

from telegram.ext import Application

from app.bot.telegram_bot import build_telegram_application
from app.config import Settings, get_settings
from app.core.logger import configure_logging
from app.core.paths import ensure_runtime_dirs
from app.services.downloader import VideoDownloader
from app.services.job_manager import JobManager
from app.services.job_store import JobStore
from app.services.notifier import TelegramJobNotifier
from app.services.orchestrator import JobOrchestrator
from app.services.publisher import create_publisher
from app.services.session_manager import SessionManager


def build_startup_summary(settings: Settings) -> str:
    """Build a safe startup summary without exposing secrets."""
    runtime_dirs = ", ".join(str(path) for path in settings.runtime_dirs)
    return (
        f"env={settings.app_env}, "
        f"headless={settings.playwright_headless}, "
        f"publish_provider={settings.facebook_publish_provider}, "
        f"business_asset_configured={bool(settings.facebook_business_asset_id)}, "
        f"allowed_users={len(settings.telegram_allowed_user_ids)}, "
        f"runtime_dirs=[{runtime_dirs}]"
    )


def build_runtime_components(settings: Settings) -> tuple[JobManager, Application]:
    """Build reusable in-process services without starting long-running loops."""
    job_manager = JobManager()
    session_manager = SessionManager(settings)
    orchestrator = JobOrchestrator(
        settings=settings,
        job_manager=job_manager,
        downloader=VideoDownloader(settings),
        session_manager=session_manager,
        publisher=create_publisher(settings=settings, session_manager=session_manager),
        job_store=JobStore(settings),
        notifier=TelegramJobNotifier(),
    )
    telegram_application = build_telegram_application(
        settings,
        job_manager=job_manager,
        orchestrator=orchestrator,
    )
    return job_manager, telegram_application


def has_configured_telegram_token(settings: Settings) -> bool:
    """Return whether settings look ready for Telegram application bootstrap."""
    return bool(settings.telegram_bot_token and ":" in settings.telegram_bot_token)


def ensure_main_event_loop() -> asyncio.AbstractEventLoop:
    """Ensure libraries expecting a default main-thread loop can start on Python 3.14+."""
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def bootstrap(settings: Settings | None = None) -> list[Path]:
    """Load settings, configure logging, and ensure runtime directories exist."""
    active_settings = settings or get_settings()
    logger = configure_logging(active_settings.log_level, active_settings.log_dir)
    created_dirs = ensure_runtime_dirs(active_settings)
    logger.info("application startup complete: %s", build_startup_summary(active_settings))
    if has_configured_telegram_token(active_settings):
        _, telegram_application = build_runtime_components(active_settings)
        logger.info(
            "telegram application prepared with commands=%s",
            ",".join(sorted({command for handler in telegram_application.handlers[0] for command in handler.commands})),
        )
        catalog = telegram_application.bot_data.get("telegram_command_catalog", [])
        logger.info(
            "telegram slash command catalog prepared: %s",
            ",".join(command.command for command in catalog),
        )
    else:
        logger.info("telegram application bootstrap skipped because TELEGRAM_BOT_TOKEN is not configured")

    return created_dirs


def main() -> None:
    """Entrypoint used by `python -m app.main`."""
    settings = get_settings()
    bootstrap(settings)
    if not has_configured_telegram_token(settings):
        return

    ensure_main_event_loop()
    _, telegram_application = build_runtime_components(settings)
    telegram_application.run_polling()


if __name__ == "__main__":
    main()
