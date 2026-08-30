"""Telegram-facing final job result notifications."""

from __future__ import annotations

from typing import Any

from app.models.job import Job, JobStatus


class NotificationError(RuntimeError):
    """Raised when a final Telegram notification cannot be sent."""


class TelegramJobNotifier:
    """Format and send final job result messages to Telegram."""

    def build_job_result_message(self, job: Job) -> str:
        """Render the final operator-facing message for a completed job."""
        label_prefix = f"{job.clip_label}\n" if job.clip_label else ""
        if job.status is JobStatus.PUBLISHED:
            return "\n".join(
                [
                    f"{label_prefix}Publish job completed.",
                    f"Job ID: {job.job_id}",
                    f"Status: {job.status.value}",
                    f"Post URL: {job.facebook_post_url or '(unavailable)'}",
                ]
            )

        if job.status is JobStatus.SCHEDULED:
            return "\n".join(
                [
                    f"{label_prefix}Publish job scheduled.",
                    f"Job ID: {job.job_id}",
                    f"Status: {job.status.value}",
                    f"Scheduled at: {job.scheduled_at.isoformat() if job.scheduled_at else '(unavailable)'}",
                ]
            )

        return "\n".join(
            [
                f"{label_prefix}Publish job failed.",
                f"Job ID: {job.job_id}",
                f"Status: {job.status.value}",
                f"Error: {job.error_message or 'Unknown error'}",
            ]
        )

    async def send_job_result(self, bot: Any, chat_id: int | None, job: Job) -> str:
        """Send the final job result back to the operator chat."""
        if chat_id is None:
            raise NotificationError("Telegram chat ID is required for final job notifications.")

        send_message = getattr(bot, "send_message", None)
        if not callable(send_message):
            raise NotificationError("Telegram bot client does not support send_message().")

        text = self.build_job_result_message(job)
        await send_message(chat_id=chat_id, text=text)
        return text
