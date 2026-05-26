"""Video download service backed by yt-dlp."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError as YtDlpDownloadError

from app.config import Settings, get_settings
from app.core.logger import get_job_logger
from app.models.job import Job, JobStatus


@dataclass(slots=True)
class DownloadResult:
    """Represents the primary output of a completed download."""

    source_url: str
    download_path: Path
    normalized_filename: str
    duration_seconds: float | None = None
    file_size_bytes: int | None = None
    extractor: str | None = None
    title: str | None = None
    caption: str | None = None


class DownloaderError(RuntimeError):
    """Raised when the downloader cannot fetch the requested media."""


class VideoDownloader:
    """Wrap yt-dlp behind a small application-friendly API."""

    MAX_LOCAL_FILENAME_LENGTH = 120

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def build_options(self) -> dict[str, Any]:
        """Build yt-dlp options from shared application settings."""
        output_template = self.settings.download_dir / "%(id)s.%(ext)s"
        return {
            "outtmpl": str(output_template),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "windowsfilenames": True,
        }

    @classmethod
    def normalize_filename(cls, title: str | None, video_id: str | None, extension: str | None) -> str:
        """Create a deterministic local filename from download metadata."""
        safe_title = re.sub(r"[^a-z0-9]+", "-", (title or "download").lower()).strip("-")
        safe_id = re.sub(r"[^a-zA-Z0-9]+", "-", (video_id or "media")).strip("-")
        safe_ext = re.sub(r"[^a-zA-Z0-9]+", "", (extension or "bin").lower()) or "bin"
        title_fragment = safe_title or "download"
        stem_prefix = f"{safe_id}-"
        max_stem_length = max(8, cls.MAX_LOCAL_FILENAME_LENGTH - len(safe_ext) - 1)
        allowed_title_length = max_stem_length - len(stem_prefix)

        if allowed_title_length <= 0:
            safe_stem = safe_id[:max_stem_length] or "media"
        else:
            trimmed_title = title_fragment[:allowed_title_length].strip("-") or "download"
            safe_stem = f"{safe_id}-{trimmed_title}"

        return f"{safe_stem}.{safe_ext}"

    @staticmethod
    def build_non_conflicting_path(target_path: Path) -> Path:
        """Return a collision-safe file path by appending a numeric suffix when needed."""
        if not target_path.exists():
            return target_path

        for suffix in range(2, 10_000):
            candidate = target_path.with_name(f"{target_path.stem}-{suffix}{target_path.suffix}")
            if not candidate.exists():
                return candidate

        raise DownloaderError(f"Could not allocate local download path for {target_path.name}")

    @staticmethod
    def extract_caption(info: dict[str, Any]) -> str:
        """Return only the source post caption from downloader metadata."""
        candidates = (
            info.get("description"),
            info.get("fulltitle"),
            info.get("title"),
        )
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue

            lines = []
            for raw_line in candidate.splitlines():
                line = raw_line.strip()
                lowered = line.lower()
                if not line:
                    continue
                if lowered.startswith(("http://", "https://", "www.")):
                    continue
                if lowered in {"facebook", "facebook video", "watch", "video"}:
                    continue
                if lowered.startswith(("uploaded by ", "provided to youtube by ", "music in this video")):
                    continue
                lines.append(line)

            caption = "\n".join(lines).strip()
            if caption:
                return caption

        return ""

    @staticmethod
    def build_logger(job: Job | None = None) -> logging.LoggerAdapter:
        """Return a job-aware logger for downloader events."""
        job_id = job.job_id if job is not None else "-"
        return get_job_logger("page_automation.downloader", job_id)

    @staticmethod
    def describe_error(error: Exception) -> str:
        """Map raw downloader failures into actionable messages."""
        message = str(error).strip()
        lowered = message.lower()

        if "unsupported url" in lowered or "invalid url" in lowered:
            return "Unsupported or invalid source URL."
        if "login" in lowered or "sign in" in lowered or "authentication" in lowered:
            return "Source video requires authentication before it can be downloaded."
        if "unavailable" in lowered or "not available" in lowered or "blocked" in lowered:
            return "Source video is unavailable or blocked."
        if "timeout" in lowered or "network" in lowered or "connection" in lowered:
            return "Network or timeout error while downloading the source video."

        return f"Video download failed: {message}"

    def download(self, source_url: str, job: Job | None = None) -> DownloadResult:
        """Download one source URL into the configured local storage."""
        self.settings.download_dir.mkdir(parents=True, exist_ok=True)
        logger = self.build_logger(job)
        if job is not None:
            job.set_status(JobStatus.DOWNLOADING)
        logger.info("starting video download", extra={"source_url": source_url})

        try:
            with YoutubeDL(self.build_options()) as downloader:
                info = downloader.extract_info(source_url, download=True)
                prepared_path = Path(downloader.prepare_filename(info))
                normalized_filename = self.normalize_filename(
                    title=info.get("title"),
                    video_id=info.get("id"),
                    extension=info.get("ext"),
                )

            normalized_path = self.settings.download_dir / normalized_filename
            if prepared_path.exists() and prepared_path != normalized_path:
                if normalized_path.exists():
                    try:
                        normalized_path.unlink()
                    except OSError:
                        normalized_path = self.build_non_conflicting_path(normalized_path)
                prepared_path.replace(normalized_path)
            elif prepared_path.exists():
                normalized_path = prepared_path
            else:
                normalized_path = self.build_non_conflicting_path(normalized_path)

            result = DownloadResult(
                source_url=source_url,
                download_path=normalized_path,
                normalized_filename=normalized_path.name,
                duration_seconds=info.get("duration"),
                file_size_bytes=info.get("filesize") or info.get("filesize_approx"),
                extractor=info.get("extractor"),
                title=info.get("title"),
                caption=self.extract_caption(info),
            )

            if job is not None:
                job.download_path = result.download_path
                job.download_filename = result.normalized_filename
                job.download_duration_seconds = result.duration_seconds
                job.download_file_size_bytes = result.file_size_bytes
                job.set_status(JobStatus.DOWNLOADED)

            logger.info(
                "video download completed",
                extra={
                    "download_path": str(result.download_path),
                    "duration_seconds": result.duration_seconds,
                    "file_size_bytes": result.file_size_bytes,
                },
            )
            return result
        except (YtDlpDownloadError, OSError) as error:
            detail = self.describe_error(error)
            if job is not None:
                job.set_status(JobStatus.FAILED, error_message=detail)
            logger.error("download failed: %s", detail)
            raise DownloaderError(detail) from error
