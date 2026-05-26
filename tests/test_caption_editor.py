import json
from urllib.error import HTTPError

import pytest

from app.config import Settings
from app.services.caption_editor import CaptionEditor


def test_caption_editor_returns_original_when_disabled() -> None:
    editor = CaptionEditor(Settings(CAPTION_EDITOR_ENABLED="false"))

    assert editor.edit("  caption goc  ") == "caption goc"


def test_caption_editor_uses_gemini_response(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        CAPTION_EDITOR_ENABLED="true",
        CAPTION_EDITOR_PROVIDER="gemini",
        GEMINI_API_KEY="gemini-key",
    )
    editor = CaptionEditor(settings)

    def fake_post_json(url, payload, headers=None):
        assert "gemini-2.5-flash" in url
        assert "Caption goc" in payload["contents"][0]["parts"][0]["text"]
        return {"candidates": [{"content": {"parts": [{"text": "Caption da hay hon."}]}}]}

    monkeypatch.setattr(editor, "_post_json", fake_post_json)

    assert editor.edit("caption goc") == "Caption da hay hon."


def test_caption_editor_uses_openai_response(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        CAPTION_EDITOR_ENABLED="true",
        CAPTION_EDITOR_PROVIDER="openai",
        CAPTION_EDITOR_MODEL="gpt-4.1-mini",
        OPENAI_API_KEY="openai-key",
    )
    editor = CaptionEditor(settings)

    def fake_post_json(url, payload, headers=None):
        assert url == "https://api.openai.com/v1/responses"
        assert headers == {"Authorization": "Bearer openai-key"}
        assert payload["model"] == "gpt-4.1-mini"
        return {"output_text": "Caption OpenAI da chinh."}

    monkeypatch.setattr(editor, "_post_json", fake_post_json)

    assert editor.edit("caption goc") == "Caption OpenAI da chinh."


def test_caption_editor_falls_back_to_original_on_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        CAPTION_EDITOR_ENABLED="true",
        CAPTION_EDITOR_PROVIDER="gemini",
        GEMINI_API_KEY="gemini-key",
    )
    editor = CaptionEditor(settings)

    def fake_post_json(url, payload, headers=None):
        raise HTTPError(url, 500, "Server error", {}, None)

    monkeypatch.setattr(editor, "_post_json", fake_post_json)

    assert editor.edit("caption goc") == "caption goc"


def test_caption_editor_parses_openai_output_items(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        CAPTION_EDITOR_ENABLED="true",
        CAPTION_EDITOR_PROVIDER="openai",
        OPENAI_API_KEY="openai-key",
    )
    editor = CaptionEditor(settings)

    def fake_post_json(url, payload, headers=None):
        return json.loads(
            """
            {
              "output": [
                {
                  "content": [
                    {"type": "output_text", "text": "Caption trong output item."}
                  ]
                }
              ]
            }
            """
        )

    monkeypatch.setattr(editor, "_post_json", fake_post_json)

    assert editor.edit("caption goc") == "Caption trong output item."
