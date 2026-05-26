"""Telegram application bootstrap and command registration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from telegram import BotCommand
from telegram.ext import Application, ApplicationBuilder, CommandHandler

from app.bot.handlers import help_command, publish_command, schedule_command, start_command
from app.config import Settings, get_settings
from app.services.job_manager import JobManager
from app.services.orchestrator import JobOrchestrator

logger = logging.getLogger("page_automation.telegram")


@dataclass(frozen=True, slots=True)
class TelegramCommandSpec:
    """One Telegram command, its operator description, and handler."""

    name: str
    description: str
    handler: object


def get_telegram_command_specs() -> tuple[TelegramCommandSpec, ...]:
    """Return the canonical command catalog used by handlers and Telegram menu."""
    return (
        TelegramCommandSpec("start", "Start the bot", start_command),
        TelegramCommandSpec("help", "Show command help", help_command),
        TelegramCommandSpec("publish", "Auto-schedule video posts", publish_command),
        TelegramCommandSpec("schedule", "Schedule a video post", schedule_command),
    )


def build_telegram_slash_commands() -> list[BotCommand]:
    """Build the command payload sent to Telegram's slash-command menu."""
    return [BotCommand(spec.name, spec.description) for spec in get_telegram_command_specs()]


async def register_telegram_slash_commands(application: Application) -> None:
    """Register slash-command suggestions with Telegram."""
    commands = build_telegram_slash_commands()
    await application.bot.set_my_commands(commands)
    application.bot_data["telegram_slash_commands_registered"] = True


async def _post_init_register_telegram_slash_commands(application: Application) -> None:
    await register_telegram_slash_commands(application)


async def telegram_error_handler(update: object, context: object) -> None:
    """Capture Telegram runtime exceptions to avoid noisy default traceback spam."""
    error = getattr(context, "error", None)
    if error is None:
        logger.error("telegram runtime error raised without context payload")
        return

    logger.error(
        "telegram runtime error: %s",
        error,
        exc_info=(type(error), error, getattr(error, "__traceback__", None)),
    )


def build_telegram_application(
    settings: Settings | None = None,
    job_manager: JobManager | None = None,
    orchestrator: JobOrchestrator | None = None,
) -> Application:
    """Build the Telegram bot application and register supported commands."""
    active_settings = settings or get_settings()

    application = (
        ApplicationBuilder()
        .token(active_settings.telegram_bot_token)
        .post_init(_post_init_register_telegram_slash_commands)
        .build()
    )
    application.bot_data["settings"] = active_settings
    application.bot_data["job_manager"] = job_manager or JobManager()
    application.bot_data["orchestrator"] = orchestrator
    application.bot_data["telegram_command_catalog"] = build_telegram_slash_commands()
    application.bot_data["telegram_slash_commands_registered"] = False

    for spec in get_telegram_command_specs():
        application.add_handler(CommandHandler(spec.name, spec.handler))
    application.add_error_handler(telegram_error_handler)

    return application
