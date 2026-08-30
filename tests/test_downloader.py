import logging
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError as YtDlpDownloadError

from app.core.logger import configure_logging
from app.config import Settings
from app.services.downloader import DownloaderError, VideoDownloader


class FakeYoutubeDL:
    instances: list["FakeYoutubeDL"] = []

    def __init__(self, options: dict[str, str]) -> None:
        self.options = options
        self.calls: list[tuple[str, bool]] = []
        self.info = {
            "id": "video123",
            "title": "Demo Title",
            "extractor": "generic",
            "ext": "mp4",
            "duration": 42.5,
            "filesize": 4096,
        }
        type(self).instances.append(self)

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def extract_info(self, source_url: str, download: bool) -> dict[str, str]:
        self.calls.append((source_url, download))
        return dict(self.info)

    def prepare_filename(self, info: dict[str, str]) -> str:
        output_dir = Path(self.options["outtmpl"]).parent
        return str(output_dir / f"{info['id']}-{info['title']}.{info['ext']}")


class ExistingTargetYoutubeDL(FakeYoutubeDL):
    def prepare_filename(self, info: dict[str, str]) -> str:
        output_dir = Path(self.options["outtmpl"]).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        prepared_path = output_dir / f"{info['id']}-{info['title']}.{info['ext']}"
        normalized_path = output_dir / "video123-demo-title.mp4"
        prepared_path.write_text("new download", encoding="utf-8")
        normalized_path.write_text("old download", encoding="utf-8")
        return str(prepared_path)


class FailingYoutubeDL(FakeYoutubeDL):
    def extract_info(self, source_url: str, download: bool) -> dict[str, str]:
        raise YtDlpDownloadError("This video is unavailable")


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="123456:test-token",
        TELEGRAM_ALLOWED_USER_IDS="123",
        FACEBOOK_PAGE_URL="https://facebook.example/page",
        DOWNLOAD_DIR=tmp_path / "downloads",
        SESSION_DIR=tmp_path / "sessions",
        SCREENSHOT_DIR=tmp_path / "screenshots",
        LOG_DIR=tmp_path / "logs",
    )


def test_build_options_targets_download_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.services.downloader.YoutubeDL", FakeYoutubeDL)
    downloader = VideoDownloader(build_settings(tmp_path))

    options = downloader.build_options()

    assert str(tmp_path / "downloads") in options["outtmpl"]
    assert options["noplaylist"] is True
    assert options["retries"] == 5
    assert options["extractor_args"]["youtube"]["player_client"] == ["android", "ios", "mweb", "web"]


def test_build_options_resolves_cookiefile(monkeypatch, tmp_path: Path) -> None:
    cookie_path = tmp_path / "custom_cookies.txt"
    cookie_path.write_text("fake cookies", encoding="utf-8")
    settings = build_settings(tmp_path)
    settings.ytdlp_cookiefile = cookie_path
    downloader = VideoDownloader(settings)

    options = downloader.build_options()
    assert options.get("cookiefile") == str(cookie_path)


def test_build_options_resolves_cookies_from_browser(monkeypatch, tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings.ytdlp_cookies_from_browser = "chrome"
    downloader = VideoDownloader(settings)

    options = downloader.build_options()
    assert options.get("cookiesfrombrowser") == ("chrome",)


def test_build_options_auto_detects_session_cookies_txt(monkeypatch, tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_cookie = session_dir / "cookies.txt"
    session_cookie.write_text("session cookies", encoding="utf-8")

    settings = build_settings(tmp_path)
    downloader = VideoDownloader(settings)

    options = downloader.build_options()
    assert options.get("cookiefile") == str(session_cookie)



def test_download_returns_local_path_from_prepared_filename(monkeypatch, tmp_path: Path) -> None:
    FakeYoutubeDL.instances.clear()
    monkeypatch.setattr("app.services.downloader.YoutubeDL", FakeYoutubeDL)
    downloader = VideoDownloader(build_settings(tmp_path))

    result = downloader.download("https://example.com/video")

    instance = FakeYoutubeDL.instances[0]
    assert instance.calls == [("https://example.com/video", True)]
    assert result.download_path == tmp_path / "downloads" / "video123-demo-title.mp4"
    assert result.normalized_filename == "video123-demo-title.mp4"
    assert result.duration_seconds == 42.5
    assert result.file_size_bytes == 4096
    assert result.extractor == "generic"
    assert result.title == "Demo Title"
    assert result.caption == "Demo Title"


def test_extract_caption_prefers_clean_description_over_metadata() -> None:
    info = {
        "description": "\nCaption goc cua bai viet\nhttps://facebook.com/example\nFacebook\n",
        "title": "Fallback title",
    }

    assert VideoDownloader.extract_caption(info) == "Caption goc cua bai viet"


def test_extract_caption_prefers_youtube_title_over_description() -> None:
    info = {
        "extractor": "youtube",
        "title": "Kết Hôn Giả Với Tổng Tài",
        "description": (
            "💕Subscribe kênh tại đây để theo dõi những bộ phim mới nhất\n\n"
            "#phimngắn #phimhay #shortdrama #chinesedrama"
        ),
    }

    assert VideoDownloader.extract_caption(info) == "Kết Hôn Giả Với Tổng Tài"


def test_download_replaces_existing_normalized_file(monkeypatch, tmp_path: Path) -> None:
    FakeYoutubeDL.instances.clear()
    monkeypatch.setattr("app.services.downloader.YoutubeDL", ExistingTargetYoutubeDL)
    downloader = VideoDownloader(build_settings(tmp_path))

    result = downloader.download("https://example.com/video")

    assert result.download_path == tmp_path / "downloads" / "video123-demo-title.mp4"
    assert result.download_path.read_text(encoding="utf-8") == "new download"
    assert not (tmp_path / "downloads" / "video123-Demo Title.mp4").exists()


def test_download_updates_job_with_download_metadata(monkeypatch, tmp_path: Path) -> None:
    from app.models.job import Job, JobStatus

    FakeYoutubeDL.instances.clear()
    monkeypatch.setattr("app.services.downloader.YoutubeDL", FakeYoutubeDL)
    downloader = VideoDownloader(build_settings(tmp_path))
    job = Job(source_url="https://example.com/video")

    result = downloader.download("https://example.com/video", job=job)

    assert job.status is JobStatus.DOWNLOADED
    assert job.download_path == result.download_path
    assert job.download_filename == "video123-demo-title.mp4"
    assert job.download_duration_seconds == 42.5
    assert job.download_file_size_bytes == 4096


def test_download_maps_failures_and_logs_with_job_id(monkeypatch, tmp_path: Path, caplog) -> None:
    from app.models.job import Job, JobStatus

    monkeypatch.setattr("app.services.downloader.YoutubeDL", FailingYoutubeDL)
    configure_logging("INFO", tmp_path / "logs")
    caplog.set_level(logging.INFO)
    downloader = VideoDownloader(build_settings(tmp_path))
    job = Job(source_url="https://example.com/video")

    with pytest.raises(DownloaderError, match="Source video is unavailable or blocked."):
        downloader.download("https://example.com/video", job=job)

    assert job.status is JobStatus.FAILED
    assert job.error_message == "Source video is unavailable or blocked."
    assert any(record.job_id == job.job_id for record in caplog.records)
    assert any("download failed" in record.getMessage() for record in caplog.records)
