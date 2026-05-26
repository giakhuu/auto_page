from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_env_example_contains_phase_one_contract() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    for key in [
        "TELEGRAM_BOT_TOKEN=",
        "TELEGRAM_ALLOWED_USER_IDS=",
        "FACEBOOK_PAGE_URL=",
        "FACEBOOK_COLLABORATOR_URL=",
        "FACEBOOK_COLLABORATOR_NAME=",
        "PLAYWRIGHT_HEADLESS=",
        "DOWNLOAD_DIR=data/downloads",
        "SESSION_DIR=data/sessions",
        "SCREENSHOT_DIR=data/screenshots",
        "LOG_LEVEL=INFO",
        "LOG_DIR=logs",
        "APP_ENV=development",
    ]:
        assert key in env_example
