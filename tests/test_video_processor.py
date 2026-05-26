import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models.job import Job
from app.services.video_processor import VideoProcessor


ROOT = Path(__file__).resolve().parents[1]


def test_video_processor_builds_fixed_10fps_1_1x_command() -> None:
    command = VideoProcessor.build_command(
        "ffmpeg",
        Path("input.mp4"),
        Path("output.mp4"),
        has_audio=True,
    )

    command_text = " ".join(command)

    assert "fps=10,setpts=PTS/1.1" in command_text
    assert "[0:a]atempo=1.1[a]" in command_text
    assert "-c:v" in command
    assert "libx264" in command
    assert "-c:a" in command
    assert "aac" in command


def test_video_processor_creates_processed_mp4_and_updates_job(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required for video processing verification")

    source = ROOT / "data" / "tmp" / "reel-upload-smoke.mp4"
    input_path = tmp_path / "clip.mp4"
    shutil.copyfile(source, input_path)
    job = Job(
        source_url="https://example.com/video",
        download_path=input_path,
        download_filename=input_path.name,
    )

    result = VideoProcessor().process(input_path, job=job)

    assert result.video_path == tmp_path / "clip-processed.mp4"
    assert result.video_path.exists()
    assert not input_path.exists()
    assert job.download_path == result.video_path
    assert job.download_filename == "clip-processed.mp4"
    assert job.download_file_size_bytes == result.video_path.stat().st_size

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(result.video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(probe.stdout)

    assert payload["streams"][0]["avg_frame_rate"] == "10/1"
    assert float(payload["format"]["duration"]) < 3.0
