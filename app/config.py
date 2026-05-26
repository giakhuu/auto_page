"""Centralized application settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings loaded from environment variables and .env files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_ids: list[int] = Field(default_factory=list, alias="TELEGRAM_ALLOWED_USER_IDS")
    facebook_page_url: str = Field(default="", alias="FACEBOOK_PAGE_URL")
    facebook_publish_provider: str = Field(default="business_suite", alias="FACEBOOK_PUBLISH_PROVIDER")
    facebook_business_suite_url: str = Field(
        default="https://business.facebook.com/",
        alias="FACEBOOK_BUSINESS_SUITE_URL",
    )
    facebook_business_asset_id: str = Field(default="", alias="FACEBOOK_BUSINESS_ASSET_ID")
    facebook_collaborator_url: str = Field(default="", alias="FACEBOOK_COLLABORATOR_URL")
    facebook_collaborator_name: str = Field(default="", alias="FACEBOOK_COLLABORATOR_NAME")
    caption_editor_enabled: bool = Field(default=False, alias="CAPTION_EDITOR_ENABLED")
    caption_editor_provider: str = Field(default="gemini", alias="CAPTION_EDITOR_PROVIDER")
    caption_editor_model: str = Field(default="gemini-2.5-flash", alias="CAPTION_EDITOR_MODEL")
    caption_editor_api_key: str = Field(default="", alias="CAPTION_EDITOR_API_KEY")
    caption_editor_timeout_seconds: float = Field(default=30.0, alias="CAPTION_EDITOR_TIMEOUT_SECONDS")
    caption_editor_instruction: str = Field(
        default=(
            "Viet lai caption Facebook ngan gon, tu nhien, co dau cau tot hon. "
            "Giu nguyen ngon ngu chinh va y nghia goc. Khong them giai thich, "
            "khong markdown, chi tra ve caption da chinh sua."
        ),
        alias="CAPTION_EDITOR_INSTRUCTION",
    )
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    playwright_headless: bool = Field(default=False, alias="PLAYWRIGHT_HEADLESS")
    download_dir: Path = Field(default=Path("data/downloads"), alias="DOWNLOAD_DIR")
    session_dir: Path = Field(default=Path("data/sessions"), alias="SESSION_DIR")
    screenshot_dir: Path = Field(default=Path("data/screenshots"), alias="SCREENSHOT_DIR")
    auto_schedule_slot_state_file: Path = Field(
        default=Path("data/auto_schedule_slot.txt"),
        alias="AUTO_SCHEDULE_SLOT_STATE_FILE",
    )
    log_dir: Path = Field(default=Path("logs"), alias="LOG_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, value: Any) -> list[int]:
        """Parse comma-separated Telegram user IDs into a clean integer list."""
        if value in (None, ""):
            return []

        if isinstance(value, list):
            return [int(item) for item in value]

        return [int(item.strip()) for item in str(value).split(",") if item.strip()]

    @field_validator("download_dir", "session_dir", "screenshot_dir", "auto_schedule_slot_state_file", "log_dir", mode="before")
    @classmethod
    def parse_path(cls, value: Any) -> Path:
        """Normalize configured paths into Path objects."""
        if isinstance(value, Path):
            return value

        raw = str(value).strip() if value else "."
        return Path(raw).expanduser()

    @property
    def runtime_dirs(self) -> list[Path]:
        """Directories the application should ensure at startup."""
        return [self.download_dir, self.session_dir, self.screenshot_dir, self.log_dir]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for the current process."""
    return Settings()
