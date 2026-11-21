"""
AetherOS Multimodal Intake — converts Figma exports, diagrams, and audio to requirements specs.

Called from P00 task_agent.run() when the input contains file paths or base64 content
rather than plain text. Falls back gracefully — if a handler fails, the original
input is returned unchanged.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


async def parse_figma_export(figma_json: dict) -> str:
    """
    Convert a Figma /files/{key} REST API response to a plain English requirements string.

    Uses pure dict traversal — no LLM needed because Figma exports are structured JSON.
    Extracts pages (screens), components (UI elements), and prototype interactions.
    """
    # Figma top-level: document.children = list of pages
    document = figma_json.get("document", {})
    pages = document.get("children", [])

    page_names = [p.get("name", "Unnamed") for p in pages if p.get("type") == "CANVAS"]

    # Collect component names and frame names across all pages
    component_summary_parts: list[str] = []
    interaction_summary_parts: list[str] = []

    for page in pages:
        if page.get("type") != "CANVAS":
            continue
        page_name = page.get("name", "Unnamed")
        frames = [c for c in page.get("children", []) if c.get("type") in ("FRAME", "COMPONENT_SET")]
        frame_names = [f.get("name", "") for f in frames if f.get("name")]
        if frame_names:
            component_summary_parts.append(f"{page_name}: {', '.join(frame_names[:10])}")

        # Prototype interactions live under nodes with "interactions" keys
        # Figma exports interactions as {"trigger": {...}, "action": {...}}
        for frame in frames:
            for child in frame.get("children", []):
                interactions = child.get("interactions", [])
                for interaction in interactions:
                    action = interaction.get("action", {})
                    dest = action.get("destinationId", "")
                    trigger_type = interaction.get("trigger", {}).get("type", "")
                    if dest and trigger_type:
                        src_name = child.get("name", "element")
                        interaction_summary_parts.append(
                            f"{src_name} ({trigger_type}) → node {dest}"
                        )

    page_str = ", ".join(page_names) if page_names else "unknown screens"
    components_str = "; ".join(component_summary_parts[:8]) if component_summary_parts else "unspecified"
    interactions_str = (
        ", ".join(interaction_summary_parts[:6]) if interaction_summary_parts else "none specified"
    )

    project_name = figma_json.get("name", "the application")
    return (
        f"Application named '{project_name}' with screens: {page_str}. "
        f"Components per screen: {components_str}. "
        f"Navigation flow: {interactions_str}."
    )


async def parse_diagram_image(image_base64: str, image_mime: str = "image/png") -> str:
    """
    Use Claude Vision to extract architecture requirements from a base64-encoded diagram image.

    Converts base64 to bytes and uses the LLMClient.call_vision() method.
    Raises ValueError when the image cannot be read: a made-up "Build a system with the components in
    the diagram" spec would have the pipeline build something the user never described.
    """
    vision_prompt = (
        "This is a software architecture diagram. Extract: "
        "(1) service names, (2) database types, (3) message queues, "
        "(4) external APIs, (5) data flow directions. "
        "Output as a plain English requirements spec starting with 'Build a system with...'."
    )

    try:
        image_bytes = base64.b64decode(image_base64)
    except Exception as exc:
        raise ValueError(f"diagram image is not valid base64: {exc}") from exc

    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        result = await llm.call_vision(vision_prompt, image_bytes, task_type="analysis")
    except Exception as exc:
        raise ValueError(f"diagram analysis failed: {exc}") from exc
    if not result or not result.strip():
        raise ValueError("diagram analysis returned nothing")
    return result.strip()


async def parse_audio_transcript(audio_base64: str, audio_format: str = "mp3") -> str:
    """
    Transcribe a base64-encoded audio memo and structure it as a requirements spec.

    Whisper (OpenAI, needs OPENAI_API_KEY: the audio leaves the platform, so it is opt-in per operator).
    Without a transcript this raises ValueError and the caller falls back to the text input.
    After transcription, an LLM call structures the text into a spec.
    """
    # Privacy: the recording is sent to a third party, so it needs an explicit operator flag on top of the key
    # (an OPENAI_API_KEY may be set for other reasons). The audio itself is never written to disk or the database.
    audio_enabled = os.environ.get("AETHER_AUDIO_TRANSCRIPTION", "").strip().lower() in ("1", "true", "yes")
    openai_key = os.environ.get("OPENAI_API_KEY", "") if audio_enabled else ""
    transcript: Optional[str] = None

    # ── Primary path: Whisper transcription ─────────────────────────────────────
    if openai_key:
        try:
            import httpx

            audio_bytes = base64.b64decode(audio_base64)
            async with httpx.AsyncClient(timeout=60.0) as client:
                files = {
                    "file": (f"audio.{audio_format}", audio_bytes, f"audio/{audio_format}"),
                    "model": (None, "whisper-1"),
                }
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    files=files,
                )
                if resp.status_code == 200:
                    transcript = resp.json().get("text", "")
                    logger.info(
                        "multimodal_intake: Whisper transcription succeeded (%d chars)", len(transcript or "")
                    )
                else:
                    logger.warning(
                        "multimodal_intake: Whisper API returned %s: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
        except Exception as exc:
            logger.warning("multimodal_intake: Whisper transcription failed: %s", exc)

    if not transcript:
        # No placeholder spec: the pipeline must not build from a sentence saying "could not be transcribed".
        raise ValueError("audio memo could not be transcribed (audio transcription is off unless the operator sets AETHER_AUDIO_TRANSCRIPTION=1 and OPENAI_API_KEY); send the requirements as text")

    # ── Second pass: structure the transcript into a spec ────────────────────────
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        structure_prompt = (
            f"Convert this voice memo transcript into a structured software requirements spec:\n\n"
            f"{transcript}\n\n"
            "Output a clear, plain English requirements spec that describes what the software "
            "should do, its key features, and any technical constraints mentioned. "
            "Start with a one-sentence summary of the application."
        )
        structured = await llm.call(structure_prompt, task_type="analysis", max_tokens=1024)
        return structured.strip() if structured else transcript
    except Exception as exc:
        logger.warning("multimodal_intake: transcript structuring LLM call failed: %s", exc)
        # Return raw transcript if structuring fails — still better than nothing
        return transcript


async def detect_and_parse_input(data: dict) -> Tuple[str, str]:
    """
    Inspect `data` for multimodal keys and route to the appropriate parser.

    Checks (in priority order):
      1. figma_export (dict)  → parse_figma_export
      2. diagram_image (str)  → parse_diagram_image
      3. audio_memo (str)     → parse_audio_transcript

    Returns: (parsed_spec: str, intake_type: str)
      where intake_type is "figma" | "diagram" | "audio" | "text"

    If no multimodal keys are present, returns the raw text input unchanged
    with intake_type="text".
    """
    figma_export: Optional[Dict[str, Any]] = data.get("figma_export")
    diagram_image: Optional[str] = data.get("diagram_image")
    audio_memo: Optional[str] = data.get("audio_memo")

    if figma_export and isinstance(figma_export, dict):
        logger.info("multimodal_intake: detected figma_export input")
        try:
            spec = await parse_figma_export(figma_export)
            return spec, "figma"
        except Exception as exc:
            logger.warning("multimodal_intake: figma parse failed, falling back to text: %s", exc)

    if diagram_image and isinstance(diagram_image, str):
        logger.info("multimodal_intake: detected diagram_image input")
        image_mime = data.get("diagram_image_mime", "image/png")
        try:
            spec = await parse_diagram_image(diagram_image, image_mime)
            return spec, "diagram"
        except Exception as exc:
            logger.warning("multimodal_intake: diagram parse failed, falling back to text: %s", exc)

    if audio_memo and isinstance(audio_memo, str):
        logger.info("multimodal_intake: detected audio_memo input")
        audio_format = data.get("audio_format", "mp3")
        try:
            spec = await parse_audio_transcript(audio_memo, audio_format)
            return spec, "audio"
        except Exception as exc:
            logger.warning("multimodal_intake: audio parse failed, falling back to text: %s", exc)

    # No multimodal content — return text as-is
    raw_text = data.get("raw_input", "") or data.get("project_description", "")
    return raw_text, "text"
