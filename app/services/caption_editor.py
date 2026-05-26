"""AI-backed caption editing service."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from logging import Logger
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.config import Settings, get_settings


class CaptionEditorError(RuntimeError):
    """Raised when a caption provider cannot return usable edited text."""


@dataclass
class CaptionEditor:
    """Rewrite source captions before they are sent to the publisher."""

    settings: Settings
    logger: Logger

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = logging.getLogger("page_automation.caption_editor")

    def edit(self, caption: str) -> str:
        """Return an edited caption, or the original caption when editing is disabled/fails."""
        original = caption.strip()
        if not original or not self.settings.caption_editor_enabled:
            return original

        provider = self.settings.caption_editor_provider.strip().lower()
        try:
            if provider == "gemini":
                edited = self._edit_with_gemini(original)
            elif provider == "openai":
                edited = self._edit_with_openai(original)
            else:
                raise CaptionEditorError(f"Unsupported caption editor provider: {provider}")
        except Exception as error:
            self.logger.warning("caption editing failed, using original caption: %s", error)
            return original

        cleaned = self._clean_response_text(edited)
        if not cleaned:
            self.logger.warning("caption editing returned empty text, using original caption")
            return original
        return cleaned

    def _build_prompt(self, caption: str) -> str:
        return (
            f"{self.settings.caption_editor_instruction.strip()}\n\n"
            "Caption goc:\n"
            f"{caption}\n\n"
            "Caption da chinh sua:"
        )

    def _provider_api_key(self, provider: str) -> str:
        explicit_key = self.settings.caption_editor_api_key.strip()
        if explicit_key:
            return explicit_key
        if provider == "gemini":
            return self.settings.gemini_api_key.strip()
        if provider == "openai":
            return self.settings.openai_api_key.strip()
        return ""

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.caption_editor_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise CaptionEditorError(f"HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError) as error:
            raise CaptionEditorError(str(error)) from error

    def _edit_with_gemini(self, caption: str) -> str:
        api_key = self._provider_api_key("gemini")
        if not api_key:
            raise CaptionEditorError("Missing GEMINI_API_KEY or CAPTION_EDITOR_API_KEY")

        model = quote(self.settings.caption_editor_model.strip() or "gemini-2.5-flash", safe="")
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": self._build_prompt(caption)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.9,
            },
        }
        response = self._post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            payload,
        )
        try:
            parts = response["candidates"][0]["content"]["parts"]
            return "\n".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
        except (KeyError, IndexError, TypeError) as error:
            raise CaptionEditorError("Gemini response did not contain edited text") from error

    def _edit_with_openai(self, caption: str) -> str:
        api_key = self._provider_api_key("openai")
        if not api_key:
            raise CaptionEditorError("Missing OPENAI_API_KEY or CAPTION_EDITOR_API_KEY")

        model = self.settings.caption_editor_model.strip() or "gpt-4.1-mini"
        payload = {
            "model": model,
            "input": self._build_prompt(caption),
            "temperature": 0.7,
        }
        response = self._post_json(
            "https://api.openai.com/v1/responses",
            payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        direct_text = response.get("output_text")
        if isinstance(direct_text, str) and direct_text.strip():
            return direct_text.strip()

        try:
            output = response["output"]
            texts: list[str] = []
            for item in output:
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"}:
                        texts.append(content.get("text", ""))
            return "\n".join(texts).strip()
        except (KeyError, TypeError) as error:
            raise CaptionEditorError("OpenAI response did not contain edited text") from error

    @staticmethod
    def _clean_response_text(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()
        return cleaned
