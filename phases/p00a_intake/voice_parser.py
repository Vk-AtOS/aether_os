"""
G7: Voice memo parser for P00a multimodal intake.

Transcribes an audio file (or reads a .txt transcript) then runs structured
extraction to produce a requirements dict.

Public API:
    parse_voice(audio_path: str, anthropic_client=None) -> dict
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Extract structured software requirements from this voice memo transcript.
Return JSON ONLY (no prose):

{
  "functional_requirements": ["FR-1: ...", "FR-2: ..."],
  "non_functional_requirements": ["NFR-1: performance ...", "NFR-2: ..."],
  "entities": ["Entity1", "Entity2"],
  "integrations": ["third_party_service_1", "third_party_service_2"],
  "domain": "healthcare|fintech|ecommerce|hrm|education|logistics|general",
  "constraints": ["constraint_1", "constraint_2"]
}

Transcript:
{transcript}
"""


def _transcribe_audio(audio_path: Path) -> Optional[str]:
    """
    Attempt to transcribe audio file using OpenAI Whisper API.

    Returns transcript string or None if unavailable.
    Falls back to reading a same-name .txt file if it exists.
    """
    # Check for companion transcript file first (.mp3 → .mp3.txt or .txt)
    for txt_candidate in (
        audio_path.with_suffix(".txt"),
        Path(str(audio_path) + ".txt"),
    ):
        if txt_candidate.exists():
            try:
                transcript = txt_candidate.read_text(encoding="utf-8").strip()
                logger.info(
                    "[p00a_intake] using companion transcript file: %s", txt_candidate
                )
                return transcript
            except Exception as exc:
                logger.warning("[p00a_intake] could not read transcript file: %s", exc)

    # OpenAI Whisper API transcription
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        logger.info("[p00a_intake] OPENAI_API_KEY not set — skipping Whisper transcription")
        return None

    try:
        import httpx
        import asyncio

        ext = audio_path.suffix.lower().lstrip(".")
        mime_map = {"mp3": "audio/mpeg", "wav": "audio/wav",
                    "m4a": "audio/mp4", "ogg": "audio/ogg", "webm": "audio/webm"}
        mime = mime_map.get(ext, "audio/mpeg")
        audio_bytes = audio_path.read_bytes()

        async def _whisper() -> str:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    files={
                        "file": (audio_path.name, audio_bytes, mime),
                        "model": (None, "whisper-1"),
                    },
                )
                if resp.status_code == 200:
                    return resp.json().get("text", "")
                logger.warning(
                    "[p00a_intake] Whisper API returned %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return ""

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(asyncio.run, _whisper())
                    result = future.result(timeout=120)
            else:
                result = loop.run_until_complete(_whisper())
        except Exception as exc:
            logger.warning("[p00a_intake] asyncio loop error during Whisper: %s", exc)
            return None

        if result:
            logger.info("[p00a_intake] Whisper transcription succeeded (%d chars)", len(result))
        return result or None

    except Exception as exc:
        logger.warning("[p00a_intake] Whisper transcription failed: %s", exc)
        return None


def parse_voice(audio_path: str, anthropic_client: Optional[Any] = None) -> dict:
    """
    Transcribe audio and extract structured requirements.

    Args:
        audio_path: Absolute path to audio file (mp3/wav/m4a/ogg) or .txt transcript.
        anthropic_client: Optional pre-built LLM client.

    Returns a dict with keys:
        functional_requirements, non_functional_requirements,
        entities, integrations, domain, constraints, raw_spec, transcript

    Never raises — logs warnings and returns best-effort output.
    """
    empty_result: dict = {
        "functional_requirements": [],
        "non_functional_requirements": [],
        "entities": [],
        "integrations": [],
        "domain": "general",
        "constraints": [],
        "raw_spec": "Voice memo could not be processed — please provide requirements as text.",
        "transcript": "",
    }

    try:
        _path = Path(audio_path)
        if not _path.exists():
            logger.warning("[p00a_intake] audio file not found: %s", audio_path)
            return empty_result

        # If it's a .txt file, treat it directly as a transcript
        if _path.suffix.lower() == ".txt":
            transcript = _path.read_text(encoding="utf-8").strip()
        else:
            transcript = _transcribe_audio(_path)

        if not transcript:
            logger.warning("[p00a_intake] no transcript available for %s", audio_path)
            return {**empty_result, "raw_spec": "Audio transcription unavailable — provide text requirements."}

        # LLM structured extraction
        if anthropic_client is None:
            try:
                from aether_os.core.llm.client import get_llm_client
                llm = get_llm_client()
            except Exception as exc:
                logger.warning("[p00a_intake] could not get LLM client for voice: %s", exc)
                return {**empty_result, "transcript": transcript, "raw_spec": transcript}
        else:
            llm = anthropic_client

        import asyncio
        import json
        import re

        extraction_prompt = _EXTRACTION_PROMPT.format(transcript=transcript[:4000])

        async def _extract() -> str:
            return await llm.call(extraction_prompt, task_type="analysis")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(asyncio.run, _extract())
                    raw_json = future.result(timeout=60)
            else:
                raw_json = loop.run_until_complete(_extract())
        except Exception as exc:
            logger.warning("[p00a_intake] voice extraction LLM call failed: %s", exc)
            return {**empty_result, "transcript": transcript, "raw_spec": transcript}

        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw_json, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except Exception as exc:
                    logger.warning("[p00a_intake] voice JSON parse failed: %s", exc)
                    return {**empty_result, "transcript": transcript, "raw_spec": transcript}
            else:
                return {**empty_result, "transcript": transcript, "raw_spec": transcript}

        frs = parsed.get("functional_requirements", [])
        nfrs = parsed.get("non_functional_requirements", [])
        raw_spec = f"Voice requirements: {'. '.join(frs[:5])}." if frs else transcript[:500]

        return {
            "functional_requirements": frs,
            "non_functional_requirements": nfrs,
            "entities": parsed.get("entities", []),
            "integrations": parsed.get("integrations", []),
            "domain": parsed.get("domain", "general"),
            "constraints": parsed.get("constraints", []),
            "raw_spec": raw_spec,
            "transcript": transcript,
        }

    except Exception as exc:
        logger.warning("[p00a_intake] parse_voice failed: %s", exc)
        return empty_result
