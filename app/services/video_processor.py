"""Post-download video normalization backed by FFmpeg."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.logger import get_job_logger
from app.models.job import Job


@dataclass(slots=True)
class VideoProcessingResult:
    """Represents the local video file after FFmpeg normalization."""

    video_path: Path
    filename: str
    duration_seconds: float | None = None
    file_size_bytes: int | None = None


class VideoProcessingError(RuntimeError):
    """Raised when FFmpeg cannot prepare the downloaded video."""


class VideoProcessor:
    """Normalize downloaded videos before they are uploaded."""

    TARGET_FPS = 10
    SPEED_FACTOR = 1.1

    def __init__(self, ffmpeg_binary: str = "ffmpeg", ffprobe_binary: str = "ffprobe") -> None:
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary

    @staticmethod
    def build_logger(job: Job | None = None) -> logging.LoggerAdapter:
        """Return a job-aware logger for FFmpeg events."""
        job_id = job.job_id if job is not None else "-"
        return get_job_logger("page_automation.video_processor", job_id)

    @classmethod
    def build_output_path(cls, input_path: Path) -> Path:
        """Return the deterministic MP4 output path for a processed download."""
        return input_path.with_name(f"{input_path.stem}-processed.mp4")

    @staticmethod
    def build_clip_output_path(input_path: Path, clip_index: int) -> Path:
        """Return the deterministic MP4 path for one trimmed clip."""
        return input_path.with_name(f"{input_path.stem}-clip-{clip_index + 1:03d}.mp4")

    def has_audio_stream(self, input_path: Path) -> bool:
        """Return whether FFprobe can see at least one audio stream."""
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(input_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return result.returncode == 0 and bool(result.stdout.strip())

    @classmethod
    def build_command(cls, ffmpeg_binary: str, input_path: Path, output_path: Path, has_audio: bool) -> list[str]:
        """Build the FFmpeg command that enforces 10fps and 1.1x speed."""
        video_filter = f"fps={cls.TARGET_FPS},setpts=PTS/{cls.SPEED_FACTOR}"
        base_command = [ffmpeg_binary, "-y", "-i", str(input_path)]

        if has_audio:
            return [
                *base_command,
                "-filter_complex",
                f"[0:v]{video_filter}[v];[0:a]atempo={cls.SPEED_FACTOR}[a]",
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output_path),
            ]

        return [
            *base_command,
            "-vf",
            video_filter,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    @staticmethod
    def build_trim_command(
        ffmpeg_binary: str,
        input_path: Path,
        output_path: Path,
        start_seconds: int,
        end_seconds: int,
    ) -> list[str]:
        """Build the FFmpeg command that cuts one clip interval."""
        return [
            ffmpeg_binary,
            "-y",
            "-ss",
            str(start_seconds),
            "-to",
            str(end_seconds),
            "-i",
            str(input_path),
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(output_path),
        ]

    def probe_metadata(self, video_path: Path) -> tuple[float | None, int | None]:
        """Read duration and file size from the processed MP4."""
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(video_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None, video_path.stat().st_size if video_path.exists() else None

        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return None, video_path.stat().st_size if video_path.exists() else None

        data = payload.get("format", {})
        duration = data.get("duration")
        size = data.get("size")
        fallback_size = video_path.stat().st_size if video_path.exists() else None
        return (
            float(duration) if duration is not None else None,
            int(size) if size is not None else fallback_size,
        )

    def process(self, input_path: Path, job: Job | None = None) -> VideoProcessingResult:
        """Create a 10fps, 1.1x-speed MP4 and point the job at that file."""
        logger = self.build_logger(job)
        input_path = Path(input_path)
        if not input_path.exists():
            raise VideoProcessingError(f"Downloaded video does not exist: {input_path}")

        output_path = self.build_output_path(input_path)
        if output_path.exists():
            output_path.unlink()

        logger.info(
            "starting video processing",
            extra={
                "input_path": str(input_path),
                "target_fps": self.TARGET_FPS,
                "speed_factor": self.SPEED_FACTOR,
            },
        )

        has_audio = self.has_audio_stream(input_path)
        command = self.build_command(self.ffmpeg_binary, input_path, output_path, has_audio=has_audio)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not output_path.exists():
            if output_path.exists():
                output_path.unlink()
            detail = (result.stderr or result.stdout or "FFmpeg did not produce a processed video.").strip()
            raise VideoProcessingError(f"Video processing failed: {detail}")

        if input_path != output_path and input_path.exists():
            input_path.unlink()

        duration_seconds, file_size_bytes = self.probe_metadata(output_path)
        processed = VideoProcessingResult(
            video_path=output_path,
            filename=output_path.name,
            duration_seconds=duration_seconds,
            file_size_bytes=file_size_bytes,
        )

        if job is not None:
            job.download_path = processed.video_path
            job.download_filename = processed.filename
            job.download_duration_seconds = processed.duration_seconds
            job.download_file_size_bytes = processed.file_size_bytes

        logger.info(
            "video processing completed",
            extra={
                "output_path": str(processed.video_path),
                "duration_seconds": processed.duration_seconds,
                "file_size_bytes": processed.file_size_bytes,
            },
        )
        return processed

    def trim(
        self,
        input_path: Path,
        start_seconds: int,
        end_seconds: int,
        clip_index: int,
        job: Job | None = None,
    ) -> VideoProcessingResult:
        """Create one MP4 clip from the requested source interval."""
        logger = self.build_logger(job)
        input_path = Path(input_path)
        if not input_path.exists():
            raise VideoProcessingError(f"Downloaded video does not exist: {input_path}")
        if end_seconds <= start_seconds:
            raise VideoProcessingError("Clip end time must be greater than start time.")

        output_path = self.build_clip_output_path(input_path, clip_index)
        if output_path.exists():
            output_path.unlink()

        logger.info(
            "starting video trim",
            extra={
                "input_path": str(input_path),
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "clip_index": clip_index,
            },
        )

        command = self.build_trim_command(
            self.ffmpeg_binary,
            input_path,
            output_path,
            start_seconds,
            end_seconds,
        )
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not output_path.exists():
            if output_path.exists():
                output_path.unlink()
            detail = (result.stderr or result.stdout or "FFmpeg did not produce a trimmed video.").strip()
            raise VideoProcessingError(f"Video trim failed: {detail}")

        duration_seconds, file_size_bytes = self.probe_metadata(output_path)
        trimmed = VideoProcessingResult(
            video_path=output_path,
            filename=output_path.name,
            duration_seconds=duration_seconds,
            file_size_bytes=file_size_bytes,
        )

        if job is not None:
            job.download_path = trimmed.video_path
            job.download_filename = trimmed.filename
            job.download_duration_seconds = trimmed.duration_seconds
            job.download_file_size_bytes = trimmed.file_size_bytes

        logger.info(
            "video trim completed",
            extra={
                "output_path": str(trimmed.video_path),
                "duration_seconds": trimmed.duration_seconds,
                "file_size_bytes": trimmed.file_size_bytes,
            },
        )
        return trimmed
