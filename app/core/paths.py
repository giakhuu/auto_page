"""Helpers for normalizing and creating runtime directories."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings


def get_runtime_dirs(settings: Settings) -> list[Path]:
    """Collect the runtime directories owned by the application."""
    return [
        settings.download_dir,
        settings.session_dir,
        settings.screenshot_dir,
        settings.log_dir,
    ]


def ensure_runtime_dirs(settings: Settings) -> list[Path]:
    """Create all runtime directories if they do not already exist."""
    runtime_dirs = get_runtime_dirs(settings)
    for path in runtime_dirs:
        path.mkdir(parents=True, exist_ok=True)
    return runtime_dirs
