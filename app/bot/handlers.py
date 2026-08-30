"""Telegram command handlers and intake helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4

from telegram import Update
from telegram.ext import ContextTypes

from app.config import Settings
from app.models.job import JobStatus
from app.services.job_manager import JobManager
from app.services.orchestrator import JobOrchestrator
from app.services.slot_store import AutoScheduleSlot, AutoScheduleSlotStore

VIETNAM_TZ = timezone(timedelta(hours=7), name="Asia/Saigon")
AUTO_SCHEDULE_TIMES = ((11, 0), (12, 0), (12, 30), (18, 0), (19, 0))
AUTO_SCHEDULE_MIN_DELAY = timedelta(hours=1)
TIMESTAMP_LIST_CHARACTERS = set("0123456789:,. \t")


@dataclass(frozen=True, slots=True)
class ClipSegment:
    """One requested clip interval from a source video."""

    start_seconds: int
    end_seconds: int


@dataclass(slots=True)
class PublishRequest:
    """Validated publish command payload."""

    source_url: str
    caption: str = ""
    clip_segments: tuple[ClipSegment, ...] = ()


@dataclass(slots=True)
class ScheduleRequest(PublishRequest):
    """Validated schedule command payload."""

    scheduled_at: datetime | None = None


def get_bot_settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    """Return shared application settings stored in bot_data."""
    return context.application.bot_data["settings"]


def get_job_manager(context: ContextTypes.DEFAULT_TYPE) -> JobManager:
    """Return the shared job manager stored in bot_data."""
    return context.application.bot_data["job_manager"]


def get_orchestrator(context: ContextTypes.DEFAULT_TYPE) -> JobOrchestrator | None:
    """Return the shared orchestrator stored in bot_data when configured."""
    return context.application.bot_data.get("orchestrator")


def is_authorized_user(user_id: int | None, settings: Settings) -> bool:
    """Check whether the Telegram user ID is allowed to use the bot."""
    if not settings.telegram_allowed_user_ids:
        return True

    return user_id in settings.telegram_allowed_user_ids


def get_publish_usage() -> str:
    """Return the supported publish command syntax."""
    return (
        "Usage: /publish <url>, /publish <url> | optional caption, "
        "or /publish <url> | 00:00, 01:30, 03:00 | optional caption"
    )


def get_schedule_usage() -> str:
    """Return the supported schedule command syntax."""
    return "Usage: /schedule YYYY-MM-DD HH:MM | <url> | optional caption"


def parse_publish_request(text: str) -> PublishRequest:
    """Parse `/publish <url> | optional caption` into structured data."""
    payload = text.partition(" ")[2].strip()
    if not payload:
        raise ValueError(f"Missing publish payload. {get_publish_usage()}")

    parts = [part.strip() for part in payload.split("|", maxsplit=2)]
    url_part = parts[0]
    source_url = url_part.strip()

    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid URL. {get_publish_usage()}")

    if len(parts) == 1:
        return PublishRequest(source_url=source_url)

    timestamp_or_caption = parts[1]
    manual_caption = parts[2].strip() if len(parts) == 3 else ""
    if looks_like_timestamp_list(timestamp_or_caption):
        return PublishRequest(
            source_url=source_url,
            caption=manual_caption,
            clip_segments=parse_timestamp_segments(timestamp_or_caption),
        )

    return PublishRequest(source_url=source_url, caption=payload.partition("|")[2].strip())


def looks_like_timestamp_list(value: str) -> bool:
    """Return whether a publish argument should be treated as timestamps."""
    candidate = value.strip()
    return bool(candidate) and ":" in candidate and set(candidate) <= TIMESTAMP_LIST_CHARACTERS


def parse_timestamp_value(value: str) -> int:
    """Parse MM:SS or HH:MM:SS into whole seconds."""
    parts = value.strip().split(":")
    if len(parts) not in {2, 3}:
        raise ValueError(f"Invalid timestamp '{value}'. {get_publish_usage()}")
    if any(not part.isdigit() for part in parts):
        raise ValueError(f"Invalid timestamp '{value}'. {get_publish_usage()}")

    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        hours = 0
    else:
        hours, minutes, seconds = numbers

    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Invalid timestamp '{value}'. Minutes and seconds must be below 60.")

    return hours * 3600 + minutes * 60 + seconds


def parse_timestamp_segments(value: str) -> tuple[ClipSegment, ...]:
    """Parse comma-separated cut points into clip intervals."""
    raw_points = [part.strip() for part in value.split(",")]
    if any(not point for point in raw_points):
        raise ValueError(f"Invalid timestamp list. {get_publish_usage()}")

    cut_points = [parse_timestamp_value(point) for point in raw_points]
    if len(cut_points) < 2:
        raise ValueError("At least two timestamps are required to create clips.")

    for previous, current in zip(cut_points, cut_points[1:]):
        if current <= previous:
            raise ValueError("Timestamps must be strictly increasing.")

    return tuple(
        ClipSegment(start_seconds=start, end_seconds=end)
        for start, end in zip(cut_points, cut_points[1:])
    )


def build_auto_schedule_times(now: datetime | None = None) -> tuple[datetime, ...]:
    """Build the next eligible scheduled time for each configured daily slot."""
    current_time = now or datetime.now(VIETNAM_TZ)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=VIETNAM_TZ)
    else:
        current_time = current_time.astimezone(VIETNAM_TZ)

    earliest_allowed = current_time + AUTO_SCHEDULE_MIN_DELAY
    scheduled_times: list[datetime] = []

    for hour, minute in AUTO_SCHEDULE_TIMES:
        candidate = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < earliest_allowed:
            candidate += timedelta(days=1)
        scheduled_times.append(candidate)

    return tuple(sorted(scheduled_times))


def build_next_auto_schedule_slot(
    settings: Settings,
    now: datetime | None = None,
    reserved_slots: tuple[datetime, ...] = (),
    last_slot_index: int | None = None,
) -> AutoScheduleSlot:
    """Build the single next auto-schedule slot from the persisted cursor."""
    current_time = now or datetime.now(VIETNAM_TZ)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=VIETNAM_TZ)
    else:
        current_time = current_time.astimezone(VIETNAM_TZ)

    return AutoScheduleSlotStore(
        settings=settings,
        slots=AUTO_SCHEDULE_TIMES,
        min_delay=AUTO_SCHEDULE_MIN_DELAY,
    ).next_slot(current_time, reserved_slots=reserved_slots, last_slot_index=last_slot_index)


def get_reserved_auto_schedule_slots(job_manager: JobManager) -> tuple[datetime, ...]:
    """Return in-memory auto slots so rapid commands do not collide."""
    return tuple(
        job.scheduled_at
        for job in job_manager.list_jobs()
        if job.auto_schedule_slot_index is not None
        and job.scheduled_at is not None
        and job.status is not JobStatus.FAILED
    )


def parse_schedule_request(text: str) -> ScheduleRequest:
    """Parse `/schedule YYYY-MM-DD HH:MM | <url> | optional caption`."""
    payload = text.partition(" ")[2].strip()
    if not payload:
        raise ValueError(f"Missing schedule payload. {get_schedule_usage()}")

    time_part, separator, rest = payload.partition("|")
    if not separator:
        raise ValueError(f"Missing schedule URL. {get_schedule_usage()}")

    try:
        scheduled_at = datetime.strptime(time_part.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=VIETNAM_TZ)
    except ValueError as error:
        raise ValueError(f"Invalid schedule time. {get_schedule_usage()}") from error

    if scheduled_at <= datetime.now(VIETNAM_TZ):
        raise ValueError("Schedule time must be in the future.")

    url_part, caption_separator, caption_part = rest.partition("|")
    source_url = url_part.strip()
    caption = caption_part.strip() if caption_separator else ""

    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid URL. {get_schedule_usage()}")

    return ScheduleRequest(source_url=source_url, caption=caption, scheduled_at=scheduled_at)


async def reply_text(update: Update, text: str) -> None:
    """Reply to the current Telegram message when possible."""
    if update.effective_message is not None:
        await update.effective_message.reply_text(text)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond with a short operator-facing welcome message."""
    await reply_text(
        update,
        "Page Automation is ready. Use /publish <url> | optional caption to auto-schedule posts.",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain the supported Phase 2 bot commands."""
    await reply_text(
        update,
        "Commands: /start, /help, /publish <url> | optional caption, "
        "/publish <url> | 00:00, 01:30, 03:00 | optional caption. "
        "Empty captions will be copied from the source post when available.",
    )


async def publish_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Validate authorization and create auto-scheduled publish jobs."""
    settings = get_bot_settings(context)
    user_id = update.effective_user.id if update.effective_user is not None else None

    if not is_authorized_user(user_id, settings):
        await reply_text(
            update,
            "You are not authorized to create publish jobs with this bot.",
        )
        return

    message_text = update.effective_message.text if update.effective_message is not None else ""
    try:
        request = parse_publish_request(message_text)
    except ValueError as error:
        await reply_text(update, str(error))
        return

    job_manager = get_job_manager(context)

    if request.clip_segments:
        clip_group_id = uuid4().hex
        jobs = []
        for index, segment in enumerate(request.clip_segments):
            selected_slot = build_next_auto_schedule_slot(
                settings=settings,
                reserved_slots=get_reserved_auto_schedule_slots(job_manager),
            )
            jobs.append(
                job_manager.create_job(
                    source_url=request.source_url,
                    caption=request.caption,
                    publish_mode="scheduled",
                    scheduled_at=selected_slot.scheduled_at,
                    auto_schedule_slot_index=selected_slot.index,
                    clip_start_seconds=segment.start_seconds,
                    clip_end_seconds=segment.end_seconds,
                    clip_index=index,
                    clip_total=len(request.clip_segments),
                    clip_group_id=clip_group_id,
                )
            )

        lines = [
            "Queued auto-scheduled clip batch created.",
            f"URL: {request.source_url}",
            f"Clip count: {len(jobs)}",
            f"Caption: {request.caption or '(auto-copy from source post)'}",
            f"Group ID: {clip_group_id}",
        ]
        for job in jobs:
            slot_time = job.scheduled_at.strftime("%Y-%m-%d %H:%M") if job.scheduled_at else "(empty)"
            lines.append(f"{job.clip_label}: {slot_time} | Job ID: {job.job_id}")
        await reply_text(update, "\n".join(lines))

        orchestrator = get_orchestrator(context)
        if orchestrator is None:
            return

        chat = getattr(update, "effective_chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is None and update.effective_message is not None:
            chat_id = getattr(update.effective_message, "chat_id", None)

        create_task = getattr(context.application, "create_task", None)
        run_clip_batch = getattr(orchestrator, "run_clip_batch", None)
        if callable(create_task) and callable(run_clip_batch):
            create_task(run_clip_batch(jobs, bot=context.application.bot, chat_id=chat_id))
        return

    selected_slot = build_next_auto_schedule_slot(
        settings=settings,
        reserved_slots=get_reserved_auto_schedule_slots(job_manager),
    )
    job = job_manager.create_job(
        source_url=request.source_url,
        caption=request.caption,
        publish_mode="scheduled",
        scheduled_at=selected_slot.scheduled_at,
        auto_schedule_slot_index=selected_slot.index,
    )

    slot_time = job.scheduled_at.strftime("%Y-%m-%d %H:%M") if job.scheduled_at else "(empty)"
    caption_text = request.caption or "(auto-copy from source post)"
    await reply_text(
        update,
        "Queued auto-scheduled job created.\n"
        f"URL: {request.source_url}\n"
        f"Caption: {caption_text}\n"
        f"Slot: {slot_time}\n"
        f"Job ID: {job.job_id}",
    )

    orchestrator = get_orchestrator(context)
    if orchestrator is None:
        return

    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    if chat_id is None and update.effective_message is not None:
        chat_id = getattr(update.effective_message, "chat_id", None)

    create_task = getattr(context.application, "create_task", None)
    if callable(create_task):
        create_task(orchestrator.run_job(job, bot=context.application.bot, chat_id=chat_id))


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Validate authorization and schedule-request syntax before queueing work."""
    settings = get_bot_settings(context)
    user_id = update.effective_user.id if update.effective_user is not None else None

    if not is_authorized_user(user_id, settings):
        await reply_text(update, "You are not authorized to create schedule jobs with this bot.")
        return

    message_text = update.effective_message.text if update.effective_message is not None else ""
    try:
        request = parse_schedule_request(message_text)
    except ValueError as error:
        await reply_text(update, str(error))
        return

    job = get_job_manager(context).create_job(
        source_url=request.source_url,
        caption=request.caption,
        publish_mode="scheduled",
        scheduled_at=request.scheduled_at,
    )
    await reply_text(
        update,
        "Queued schedule job created.\n"
        f"Job ID: {job.job_id}\n"
        f"Status: {job.status.value}\n"
        f"URL: {job.source_url}\n"
        f"Scheduled at: {job.scheduled_at.isoformat() if job.scheduled_at else '(empty)'}\n"
        f"Caption: {job.caption or '(empty)'}",
    )

    orchestrator = get_orchestrator(context)
    if orchestrator is None:
        return

    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    if chat_id is None and update.effective_message is not None:
        chat_id = getattr(update.effective_message, "chat_id", None)

    create_task = getattr(context.application, "create_task", None)
    if callable(create_task):
        create_task(orchestrator.run_job(job, bot=context.application.bot, chat_id=chat_id))
