"""KAN-184: multimodal intake parses a Figma export and never replaces failed input with an invented spec."""
import asyncio
import base64

import pytest

from aether_os.phases.p00_research import multimodal_intake as mi

FIGMA = {"name": "Shop", "document": {"children": [
    {"type": "CANVAS", "name": "Home", "children": [
        {"type": "FRAME", "name": "Hero", "children": [
            {"name": "Buy", "interactions": [{"trigger": {"type": "ON_CLICK"}, "action": {"destinationId": "2:7"}}]}]}]},
    {"type": "CANVAS", "name": "Cart", "children": [{"type": "FRAME", "name": "Items"}]}]}}


def test_figma_export_becomes_a_spec():
    spec, kind = asyncio.run(mi.detect_and_parse_input({"figma_export": FIGMA, "raw_input": "ignored"}))
    assert kind == "figma" and "Shop" in spec and "Home, Cart" in spec and "Buy (ON_CLICK)" in spec


def test_unreadable_diagram_falls_back_to_the_users_text_not_a_made_up_spec():
    spec, kind = asyncio.run(mi.detect_and_parse_input({"diagram_image": "!!!not base64", "raw_input": "my own words"}))
    assert (spec, kind) == ("my own words", "text")


def test_failed_vision_call_does_not_invent_a_spec(monkeypatch):
    class LLM:
        async def call_vision(self, *a, **k):
            raise RuntimeError("model down")
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: LLM())
    png = base64.b64encode(b"\x89PNG").decode()
    spec, kind = asyncio.run(mi.detect_and_parse_input({"diagram_image": png, "raw_input": "typed spec"}))
    assert (spec, kind) == ("typed spec", "text")


def test_audio_without_whisper_key_falls_back_to_text(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    spec, kind = asyncio.run(mi.detect_and_parse_input({"audio_memo": "AAAA", "raw_input": "typed spec"}))
    assert (spec, kind) == ("typed spec", "text")
    with pytest.raises(ValueError, match="could not be transcribed"):
        asyncio.run(mi.parse_audio_transcript("AAAA"))


def test_audio_is_not_sent_anywhere_unless_the_operator_flag_is_on(monkeypatch):
    # KAN-184: a stray OPENAI_API_KEY alone must not make recordings leave the platform
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AETHER_AUDIO_TRANSCRIPTION", raising=False)
    with pytest.raises(ValueError, match="could not be transcribed"):
        asyncio.run(mi.parse_audio_transcript("AAAA"))
