import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.bot.handlers import (
    VIETNAM_TZ,
    build_auto_schedule_times,
    build_next_auto_schedule_slot,
    parse_publish_request,
    parse_schedule_request,
    publish_command,
    schedule_command,
)
from app.config import Settings
from app.services.job_manager import JobManager


class FakeMessage:
    def __init__(self, text: str, chat_id: int = 555) -> None:
        self.text = text
        self.chat_id = chat_id
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


def build_update(text: str, user_id: int) -> SimpleNamespace:
    message = FakeMessage(text)
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=message.chat_id),
        effective_message=message,
    )


def build_context(
    settings: Settings,
    job_manager: JobManager | None = None,
    orchestrator: object | None = None,
) -> SimpleNamespace:
    created_tasks: list[asyncio.Task] = []

    def create_task(coro):
        task = asyncio.create_task(coro)
        created_tasks.append(task)
        return task

    return SimpleNamespace(
        application=SimpleNamespace(
            bot_data={
                "settings": settings,
                "job_manager": job_manager or JobManager(),
                "orchestrator": orchestrator,
            },
            bot=SimpleNamespace(),
            create_task=create_task,
            created_tasks=created_tasks,
        )
    )


def build_settings() -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="123456:test-token",
        TELEGRAM_ALLOWED_USER_IDS="123",
        FACEBOOK_PAGE_URL="https://facebook.example/page",
        AUTO_SCHEDULE_SLOT_STATE_FILE="data/test_auto_schedule_slot.txt",
    )


def test_parse_publish_request_supports_optional_caption() -> None:
    request = parse_publish_request("publish https://example.com/video | Hello world")

    assert request.source_url == "https://example.com/video"
    assert request.caption == "Hello world"
    assert request.clip_segments == ()


def test_parse_publish_request_supports_timestamp_segments() -> None:
    request = parse_publish_request("publish https://example.com/video | 00:00, 01:30, 03:00")

    assert request.source_url == "https://example.com/video"
    assert request.caption == ""
    assert [(segment.start_seconds, segment.end_seconds) for segment in request.clip_segments] == [
        (0, 90),
        (90, 180),
    ]


def test_parse_publish_request_supports_timestamp_segments_and_caption() -> None:
    request = parse_publish_request("publish https://example.com/video | 00:00, 01:30, 03:00 | Caption here")

    assert request.caption == "Caption here"
    assert [(segment.start_seconds, segment.end_seconds) for segment in request.clip_segments] == [
        (0, 90),
        (90, 180),
    ]


def test_parse_publish_request_rejects_invalid_timestamp_segments() -> None:
    for text in (
        "publish https://example.com/video | 00:00",
        "publish https://example.com/video | 00:30, 00:20",
        "publish https://example.com/video | 00:70, 01:30",
    ):
        try:
            parse_publish_request(text)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected timestamp parsing to reject {text}")


def test_parse_publish_request_rejects_invalid_url() -> None:
    try:
        parse_publish_request("publish not-a-url")
    except ValueError as error:
        assert "Invalid URL" in str(error)
    else:
        raise AssertionError("Expected publish parsing to reject invalid URLs")


def test_build_auto_schedule_times_uses_next_eligible_daily_slots() -> None:
    now = datetime(2026, 4, 30, 10, 30, tzinfo=VIETNAM_TZ)

    scheduled_times = build_auto_schedule_times(now)

    assert [value.strftime("%Y-%m-%d %H:%M") for value in scheduled_times] == [
        "2026-04-30 12:00",
        "2026-04-30 12:30",
        "2026-04-30 18:00",
        "2026-04-30 19:00",
        "2026-05-01 11:00",
    ]


def test_build_next_auto_schedule_slot_uses_persisted_cursor(tmp_path: Path) -> None:
    settings = build_settings()
    settings.auto_schedule_slot_state_file = tmp_path / "auto_schedule_slot.txt"
    settings.auto_schedule_slot_state_file.write_text("last_slot_index=1\n", encoding="utf-8")
    now = datetime(2026, 4, 30, 10, 30, tzinfo=VIETNAM_TZ)

    selected_slot = build_next_auto_schedule_slot(settings=settings, now=now)

    assert selected_slot.index == 2
    assert selected_slot.scheduled_at.strftime("%Y-%m-%d %H:%M") == "2026-04-30 12:30"


def test_build_next_auto_schedule_slot_skips_used_history(tmp_path: Path) -> None:
    settings = build_settings()
    settings.auto_schedule_slot_state_file = tmp_path / "auto_schedule_slot.txt"
    settings.auto_schedule_slot_state_file.write_text(
        "\n".join(
            [
                "scheduled_slot=2026-04-30 12:00|slot_index=1|job_id=one",
                "scheduled_slot=2026-04-30 12:30|slot_index=2|job_id=two",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 10, 30, tzinfo=VIETNAM_TZ)

    selected_slot = build_next_auto_schedule_slot(settings=settings, now=now)

    assert selected_slot.index == 3
    assert selected_slot.scheduled_at.strftime("%Y-%m-%d %H:%M") == "2026-04-30 18:00"


def test_build_next_auto_schedule_slot_moves_to_tomorrow_after_latest_today_slot(tmp_path: Path) -> None:
    settings = build_settings()
    settings.auto_schedule_slot_state_file = tmp_path / "auto_schedule_slot.txt"
    settings.auto_schedule_slot_state_file.write_text(
        "scheduled_slot=2026-04-30 19:00|slot_index=4|job_id=latest\n",
        encoding="utf-8",
    )
    now = datetime(2026, 4, 30, 10, 30, tzinfo=VIETNAM_TZ)

    selected_slot = build_next_auto_schedule_slot(settings=settings, now=now)

    assert selected_slot.index == 0
    assert selected_slot.scheduled_at.strftime("%Y-%m-%d %H:%M") == "2026-05-01 11:00"


def test_publish_command_rejects_unauthorized_user() -> None:
    update = build_update("/publish https://example.com/video", user_id=999)
    context = build_context(build_settings())

    asyncio.run(publish_command(update, context))

    assert update.effective_message.replies == [
        "You are not authorized to create publish jobs with this bot."
    ]


def test_publish_command_rejects_missing_payload() -> None:
    update = build_update("/publish", user_id=123)
    context = build_context(build_settings())

    asyncio.run(publish_command(update, context))

    assert "Usage: /publish <url>" in update.effective_message.replies[0]


def test_publish_command_accepts_valid_url_and_caption() -> None:
    job_manager = JobManager()
    update = build_update("/publish https://example.com/video | Caption here", user_id=123)
    context = build_context(build_settings(), job_manager=job_manager)

    asyncio.run(publish_command(update, context))

    reply = update.effective_message.replies[0]
    stored_jobs = job_manager.list_jobs()
    assert len(stored_jobs) == 1
    assert all(job.source_url == "https://example.com/video" for job in stored_jobs)
    assert all(job.caption == "Caption here" for job in stored_jobs)
    assert all(job.publish_mode == "scheduled" for job in stored_jobs)
    assert all(job.scheduled_at is not None for job in stored_jobs)
    assert stored_jobs[0].auto_schedule_slot_index is not None
    assert stored_jobs[0].job_id in reply
    assert "Queued auto-scheduled job created." in reply
    assert "Caption here" in reply


def test_publish_command_advances_slot_for_rapid_in_memory_jobs() -> None:
    job_manager = JobManager()
    update_one = build_update("/publish https://example.com/video-1", user_id=123)
    update_two = build_update("/publish https://example.com/video-2", user_id=123)
    context = build_context(build_settings(), job_manager=job_manager)

    asyncio.run(publish_command(update_one, context))
    asyncio.run(publish_command(update_two, context))

    stored_jobs = job_manager.list_jobs()
    assert len(stored_jobs) == 2
    assert stored_jobs[0].auto_schedule_slot_index is not None
    assert stored_jobs[1].auto_schedule_slot_index == (stored_jobs[0].auto_schedule_slot_index + 1) % 5


def test_publish_command_hands_job_to_orchestrator_after_acknowledgement() -> None:
    class FakeOrchestrator:
        def __init__(self) -> None:
            self.calls: list[tuple[object, object, int | None]] = []

        async def run_job(self, job, bot=None, chat_id=None):
            self.calls.append((job, bot, chat_id))
            return job

    async def scenario() -> tuple[str, FakeOrchestrator]:
        job_manager = JobManager()
        orchestrator = FakeOrchestrator()
        update = build_update("/publish https://example.com/video | Caption here", user_id=123)
        context = build_context(build_settings(), job_manager=job_manager, orchestrator=orchestrator)

        await publish_command(update, context)
        await asyncio.gather(*context.application.created_tasks)
        return update.effective_message.replies[0], orchestrator

    reply, orchestrator = asyncio.run(scenario())

    assert "Queued auto-scheduled job created." in reply
    assert len(orchestrator.calls) == 1
    assert all(call[2] == 555 for call in orchestrator.calls)
    assert all(call[0].publish_mode == "scheduled" for call in orchestrator.calls)


def test_publish_command_creates_clip_batch_jobs_in_order() -> None:
    class FakeOrchestrator:
        def __init__(self) -> None:
            self.calls: list[tuple[list[object], object, int | None]] = []

        async def run_clip_batch(self, jobs, bot=None, chat_id=None):
            self.calls.append((jobs, bot, chat_id))
            return jobs

    async def scenario() -> tuple[str, list[object], FakeOrchestrator]:
        job_manager = JobManager()
        orchestrator = FakeOrchestrator()
        update = build_update(
            "/publish https://example.com/video | 00:00, 01:30, 03:00 | Caption here",
            user_id=123,
        )
        context = build_context(build_settings(), job_manager=job_manager, orchestrator=orchestrator)

        await publish_command(update, context)
        await asyncio.gather(*context.application.created_tasks)
        return update.effective_message.replies[0], job_manager.list_jobs(), orchestrator

    reply, stored_jobs, orchestrator = asyncio.run(scenario())

    assert "Queued auto-scheduled clip batch created." in reply
    assert "Clip count: 2" in reply
    assert len(stored_jobs) == 2
    assert len(orchestrator.calls) == 1
    assert orchestrator.calls[0][2] == 555
    assert {job.clip_group_id for job in stored_jobs}
    assert len({job.clip_group_id for job in stored_jobs}) == 1
    assert [(job.clip_start_seconds, job.clip_end_seconds) for job in stored_jobs] == [(0, 90), (90, 180)]
    assert [job.clip_label for job in stored_jobs] == ["Phần 1", "Phần 2"]
    assert stored_jobs[1].auto_schedule_slot_index == (stored_jobs[0].auto_schedule_slot_index + 1) % 5


def test_parse_schedule_request_supports_future_time_url_and_caption() -> None:
    future = datetime.now(VIETNAM_TZ) + timedelta(days=2)
    text = f"/schedule {future:%Y-%m-%d %H:%M} | https://example.com/video | Caption here"

    request = parse_schedule_request(text)

    assert request.source_url == "https://example.com/video"
    assert request.caption == "Caption here"
    assert request.scheduled_at is not None
    assert request.scheduled_at.tzinfo is not None


def test_schedule_command_creates_scheduled_job() -> None:
    future = datetime.now(VIETNAM_TZ) + timedelta(days=2)
    job_manager = JobManager()
    update = build_update(f"/schedule {future:%Y-%m-%d %H:%M} | https://example.com/video | Caption here", user_id=123)
    context = build_context(build_settings(), job_manager=job_manager)

    asyncio.run(schedule_command(update, context))

    stored_job = job_manager.list_jobs()[0]
    assert stored_job.publish_mode == "scheduled"
    assert stored_job.scheduled_at is not None
    assert "Queued schedule job created." in update.effective_message.replies[0]
