"""Text-file persistence for auto-schedule slot rotation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from app.config import Settings, get_settings
from app.models.job import Job, JobStatus


@dataclass(frozen=True, slots=True)
class AutoScheduleSlot:
    """One selected publishing slot."""

    index: int
    scheduled_at: datetime


class AutoScheduleSlotStore:
    """Persist auto-schedule slot history in a text file."""

    def __init__(
        self,
        settings: Settings | None = None,
        slots: tuple[tuple[int, int], ...] | None = None,
        min_delay: timedelta | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.slots = slots or ((11, 0), (12, 0), (12, 30), (18, 0), (19, 0))
        self.min_delay = min_delay or timedelta(hours=1)

    @property
    def state_file(self) -> Path:
        return self.settings.auto_schedule_slot_state_file

    def read_last_slot_index(self) -> int | None:
        """Read the last successful slot index from the text state file."""
        try:
            content = self.state_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("last_slot_index="):
                value = line.partition("=")[2].strip()
            else:
                value = line
            try:
                index = int(value)
            except ValueError:
                continue
            if 0 <= index < len(self.slots):
                return index
        return None

    @staticmethod
    def slot_key(value: datetime) -> str:
        """Return the duplicate-detection key for one scheduled datetime."""
        return value.strftime("%Y-%m-%d %H:%M")

    def read_scheduled_slot_keys(self) -> set[str]:
        """Read all previously used schedule slots from the text state file."""
        return {self.slot_key(value) for value in self.read_scheduled_slots()}

    def read_scheduled_slots(self) -> tuple[datetime, ...]:
        """Read previously used schedule datetimes from the text state file."""
        try:
            content = self.state_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ()

        values: list[datetime] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            value = ""
            if line.startswith("scheduled_slot="):
                value = line.partition("=")[2].partition("|")[0].strip()
            elif line.startswith("last_scheduled_at="):
                value = line.partition("=")[2].strip()

            if not value:
                continue

            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                try:
                    parsed = datetime.strptime(value[:16], "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
            values.append(parsed)

        return tuple(values)

    @staticmethod
    def _align_timezone(value: datetime, reference: datetime) -> datetime:
        if reference.tzinfo is None:
            return value.replace(tzinfo=None) if value.tzinfo is not None else value
        if value.tzinfo is None:
            return value.replace(tzinfo=reference.tzinfo)
        return value.astimezone(reference.tzinfo)

    def next_slot(
        self,
        now: datetime,
        reserved_slots: Iterable[datetime] | None = None,
        last_slot_index: int | None = None,
    ) -> AutoScheduleSlot:
        """Return the first future slot that is not already used or queued."""
        if now.tzinfo is None:
            current_time = now
        else:
            current_time = now.astimezone(now.tzinfo)

        earliest_allowed = current_time + self.min_delay
        used_values = [self._align_timezone(value, current_time) for value in self.read_scheduled_slots()]
        used_keys = {self.slot_key(value) for value in used_values}
        for reserved in reserved_slots or ():
            reserved = self._align_timezone(reserved, current_time)
            used_values.append(reserved)
            used_keys.add(self.slot_key(reserved))

        # Backward compatibility for old state files that only contained a cursor.
        if not used_keys:
            legacy_index = self.read_last_slot_index() if last_slot_index is None else last_slot_index
            if legacy_index is not None:
                next_index = (legacy_index + 1) % len(self.slots)
                hour, minute = self.slots[next_index]
                scheduled_at = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if scheduled_at < earliest_allowed:
                    scheduled_at += timedelta(days=1)
                return AutoScheduleSlot(index=next_index, scheduled_at=scheduled_at)

        search_after = earliest_allowed
        if used_values:
            latest_used = max(used_values)
            if latest_used >= search_after:
                search_after = latest_used + timedelta(minutes=1)

        for day_offset in range(366):
            day = current_time + timedelta(days=day_offset)
            for index, (hour, minute) in enumerate(self.slots):
                scheduled_at = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if scheduled_at < search_after:
                    continue
                if self.slot_key(scheduled_at) in used_keys:
                    continue
                return AutoScheduleSlot(index=index, scheduled_at=scheduled_at)

        raise RuntimeError("Could not find an available auto-schedule slot in the next 366 days.")

    def mark_job_complete(self, job: Job) -> Path | None:
        """Save the slot cursor after an auto-scheduled job successfully finishes."""
        if job.auto_schedule_slot_index is None:
            return None
        if job.status not in {JobStatus.PUBLISHED, JobStatus.SCHEDULED}:
            return None
        if not 0 <= job.auto_schedule_slot_index < len(self.slots):
            return None

        if job.scheduled_at is None:
            return None

        hour, minute = self.slots[job.auto_schedule_slot_index]
        scheduled_slot_key = self.slot_key(job.scheduled_at)
        existing_slot_lines = []
        try:
            existing_content = self.state_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing_content = ""
        for raw_line in existing_content.splitlines():
            line = raw_line.strip()
            if line.startswith("scheduled_slot=") and line.partition("=")[2].partition("|")[0].strip() != scheduled_slot_key:
                existing_slot_lines.append(line)

        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"last_slot_index={job.auto_schedule_slot_index}",
            f"last_slot_time={hour:02d}:{minute:02d}",
            f"last_job_id={job.job_id}",
            f"last_scheduled_at={job.scheduled_at.isoformat() if job.scheduled_at else ''}",
            f"updated_at={job.updated_at.isoformat()}",
            *existing_slot_lines,
            f"scheduled_slot={scheduled_slot_key}|slot_index={job.auto_schedule_slot_index}|job_id={job.job_id}",
        ]
        self.state_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.state_file
