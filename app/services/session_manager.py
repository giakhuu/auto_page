"""Reusable Playwright session bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.config import Settings, get_settings
from app.core.logger import get_job_logger


@dataclass(slots=True)
class BrowserBootstrapConfig:
    """Concrete browser bootstrap settings derived from application config."""

    user_data_dir: Path
    storage_state_path: Path
    downloads_path: Path
    headless: bool
    launch_args: tuple[str, ...]


class SessionHealthStatus(StrEnum):
    """Structured outcomes for stored-session health checks."""

    READY = "ready"
    LOGIN_REQUIRED = "login_required"
    PAGE_UNAVAILABLE = "page_unavailable"
    NAVIGATION_FAILED = "navigation_failed"


@dataclass(slots=True)
class SessionDiagnostic:
    """Actionable result from checking the configured Fanpage reachability."""

    status: SessionHealthStatus
    target_url: str
    message: str
    resolved_url: str = ""
    page_title: str = ""


class SessionManager:
    """Manage project-controlled browser session storage conventions."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def session_root(self) -> Path:
        """Root folder for the Facebook browser session."""
        return self.settings.session_dir / "facebook"

    @property
    def user_data_dir(self) -> Path:
        """Persistent browser profile directory."""
        return self.session_root / "user-data"

    @property
    def storage_state_path(self) -> Path:
        """Optional storage-state snapshot path."""
        return self.session_root / "storage-state.json"

    def ensure_session_dirs(self) -> list[Path]:
        """Create the project-controlled session directories if they do not exist."""
        paths = [self.session_root, self.user_data_dir]
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)
        return paths

    def build_bootstrap_config(self) -> BrowserBootstrapConfig:
        """Build stable Playwright bootstrap configuration from shared settings."""
        self.ensure_session_dirs()
        return BrowserBootstrapConfig(
            user_data_dir=self.user_data_dir,
            storage_state_path=self.storage_state_path,
            downloads_path=self.settings.download_dir,
            headless=self.settings.playwright_headless,
            launch_args=("--disable-notifications",),
        )

    def build_business_suite_composer_url(self) -> str:
        """Return the Business Suite Reels composer URL for video publishing."""
        base_url = self.settings.facebook_business_suite_url.rstrip("/") or "https://business.facebook.com"
        asset_id = self.settings.facebook_business_asset_id.strip()
        if not asset_id:
            return f"{base_url}/latest/reels_composer/?context_ref=HOME"
        return f"{base_url}/latest/reels_composer/?asset_id={asset_id}&context_ref=HOME"

    def build_business_suite_content_url(self, table: str = "published_posts") -> str:
        """Return a Business Suite content-management URL for a content table."""
        base_url = self.settings.facebook_business_suite_url.rstrip("/") or "https://business.facebook.com"
        asset_id = self.settings.facebook_business_asset_id.strip()
        query = f"content_table={table}"
        if asset_id:
            query = f"asset_id={asset_id}&{query}"
        return f"{base_url}/latest/content_management?{query}"

    @staticmethod
    def _looks_like_login_page(resolved_url: str, title: str, content: str) -> bool:
        lowered = " ".join([resolved_url, title, content]).lower()
        return any(marker in lowered for marker in ("login", "log in", "sign in", "checkpoint"))

    @staticmethod
    def _looks_like_unavailable_page(title: str, content: str) -> bool:
        lowered = " ".join([title, content]).lower()
        return any(
            marker in lowered
            for marker in ("content isn't available", "page isn't available", "not available", "this page isn't available")
        )

    def check_fanpage_reachability(self, page: object, job_id: str = "-") -> SessionDiagnostic:
        """Check whether the configured Fanpage is reachable with the current stored session."""
        target_url = self.settings.facebook_page_url.strip()
        logger = get_job_logger("page_automation.session", job_id)

        if not target_url:
            diagnostic = SessionDiagnostic(
                status=SessionHealthStatus.NAVIGATION_FAILED,
                target_url=target_url,
                message="FACEBOOK_PAGE_URL is not configured.",
            )
            logger.error(diagnostic.message)
            return diagnostic

        logger.info("checking fanpage reachability", extra={"target_url": target_url})

        try:
            page.goto(target_url, wait_until="domcontentloaded")
            wait_for_load_state = getattr(page, "wait_for_load_state", None)
            if callable(wait_for_load_state):
                wait_for_load_state("domcontentloaded")

            resolved_url = getattr(page, "url", "") or ""
            page_title = page.title() if callable(getattr(page, "title", None)) else ""
            content = page.content() if callable(getattr(page, "content", None)) else ""
        except Exception as error:
            diagnostic = SessionDiagnostic(
                status=SessionHealthStatus.NAVIGATION_FAILED,
                target_url=target_url,
                message=f"Could not open the configured Fanpage: {error}",
            )
            logger.error(diagnostic.message)
            return diagnostic

        if self._looks_like_login_page(resolved_url, page_title, content):
            diagnostic = SessionDiagnostic(
                status=SessionHealthStatus.LOGIN_REQUIRED,
                target_url=target_url,
                resolved_url=resolved_url,
                page_title=page_title,
                message="Stored Facebook session is not authenticated. Operator re-login is required.",
            )
            logger.warning(diagnostic.message)
            return diagnostic

        if self._looks_like_unavailable_page(page_title, content):
            diagnostic = SessionDiagnostic(
                status=SessionHealthStatus.PAGE_UNAVAILABLE,
                target_url=target_url,
                resolved_url=resolved_url,
                page_title=page_title,
                message="Configured Fanpage could not be reached with the current session.",
            )
            logger.error(diagnostic.message)
            return diagnostic

        diagnostic = SessionDiagnostic(
            status=SessionHealthStatus.READY,
            target_url=target_url,
            resolved_url=resolved_url,
            page_title=page_title,
            message="Configured Fanpage is reachable with the stored session.",
        )
        logger.info(diagnostic.message)
        return diagnostic
