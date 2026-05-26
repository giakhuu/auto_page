import asyncio

from app.models.job import Job, JobStatus
from app.services.notifier import TelegramJobNotifier


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


def test_notifier_builds_success_message_with_post_url() -> None:
    notifier = TelegramJobNotifier()
    job = Job(source_url="https://example.com/video")
    job.facebook_post_url = "https://facebook.com/example/posts/123"
    job.set_status(JobStatus.PUBLISHED)

    message = notifier.build_job_result_message(job)

    assert "Publish job completed." in message
    assert job.job_id in message
    assert "Post URL:" in message


def test_notifier_sends_failure_message_with_error_summary() -> None:
    notifier = TelegramJobNotifier()
    bot = FakeBot()
    job = Job(source_url="https://example.com/video")
    job.set_status(JobStatus.FAILED, error_message="Network timeout")

    message = asyncio.run(notifier.send_job_result(bot, 999, job))

    assert "Publish job failed." in message
    assert bot.messages == [(999, message)]
    assert "Network timeout" in message
