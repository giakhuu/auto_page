from app.bot.telegram_bot import build_telegram_application, build_telegram_slash_commands
from app.config import Settings
from app.services.job_manager import JobManager
from app.services.orchestrator import JobOrchestrator


def build_settings() -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="123456:test-token",
        TELEGRAM_ALLOWED_USER_IDS="123",
        FACEBOOK_PAGE_URL="https://facebook.example/page",
    )


def test_build_telegram_application_registers_expected_commands() -> None:
    application = build_telegram_application(build_settings())

    handlers = application.handlers[0]
    command_names = set()
    for handler in handlers:
        command_names.update(handler.commands)

    assert command_names == {"start", "help", "publish", "schedule"}


def test_build_telegram_application_keeps_settings_in_bot_data() -> None:
    settings = build_settings()

    application = build_telegram_application(settings)

    assert application.bot_data["settings"] is settings


def test_build_telegram_application_keeps_job_manager_in_bot_data() -> None:
    job_manager = JobManager()

    application = build_telegram_application(build_settings(), job_manager=job_manager)

    assert application.bot_data["job_manager"] is job_manager


def test_build_telegram_application_keeps_orchestrator_in_bot_data() -> None:
    orchestrator = JobOrchestrator(settings=build_settings())

    application = build_telegram_application(build_settings(), orchestrator=orchestrator)

    assert application.bot_data["orchestrator"] is orchestrator


def test_build_telegram_application_prepares_slash_command_catalog() -> None:
    application = build_telegram_application(build_settings())

    assert [command.command for command in application.bot_data["telegram_command_catalog"]] == [
        "start",
        "help",
        "publish",
        "schedule",
    ]
    assert application.bot_data["telegram_slash_commands_registered"] is False


def test_build_telegram_slash_commands_matches_supported_commands() -> None:
    assert [command.command for command in build_telegram_slash_commands()] == [
        "start",
        "help",
        "publish",
        "schedule",
    ]
