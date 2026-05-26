"""Open the project Facebook profile so an operator can refresh Meta login."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.services.publisher import BusinessSuitePublisher, PublisherError
from app.services.session_manager import SessionManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh or verify the stored Facebook/Business Suite Playwright session.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Open the stored profile, check Business Suite, then exit without waiting for operator input.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30_000,
        help="Readiness timeout for the Business Suite composer check.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    session_manager = SessionManager(settings)
    bootstrap = session_manager.build_bootstrap_config()
    publisher = BusinessSuitePublisher(
        settings=settings,
        session_manager=session_manager,
        interaction_timeout_ms=args.timeout_ms,
    )
    target_url = session_manager.build_business_suite_composer_url()

    print(f"Using profile: {bootstrap.user_data_dir}")
    print(f"Opening: {target_url}")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(bootstrap.user_data_dir),
            headless=False,
            args=list(bootstrap.launch_args),
            downloads_path=str(bootstrap.downloads_path),
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            if args.check_only:
                publisher.open_publish_surface(page, job_id="session-check")
                print("Stored Business Suite session is ready.")
                return 0

            page.goto(target_url, wait_until="domcontentloaded")
            print("\nLogin or complete Meta verification in the browser window.")
            print("After the Reels composer is visible, return here and press Enter.")
            input()

            try:
                publisher.open_publish_surface(page, job_id="session-bootstrap")
            except (PublisherError, PlaywrightTimeoutError) as error:
                print(f"Business Suite session still is not ready: {error}", file=sys.stderr)
                return 2

            print("Stored Business Suite session refreshed successfully.")
            return 0
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
