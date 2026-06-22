"""
G7: P00a Multimodal Intake Phase.

Pre-P00 phase that runs only when non-text inputs are provided. If no multimodal
input is detected, context passes through unchanged.

Supported input types (checked in priority order):
  1. figma_file (dict)      — Figma REST API /files/{key} export JSON
  2. diagram_image (str)    — path to PNG/JPG architecture diagram
  3. voice_memo (str)       — path to MP3/WAV audio file (or .txt transcript)

If none present, returns context unchanged — the phase is a transparent passthrough.
Never fails the pipeline — logs warnings and continues.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    P00a entry point — detect and convert multimodal inputs to text requirements.

    Context keys inspected:
        figma_file (dict)       Figma /files/{key} export JSON
        diagram_image (str)     path to architecture diagram image
        voice_memo (str)        path to audio file or .txt transcript

    On success, adds to context:
        requirements (str)      structured plain-English requirements
        intake_type (str)       "figma" | "diagram" | "voice" | "passthrough"
        intake_metadata (dict)  parsed structure (entities, screens, etc.)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    data: dict = getattr(phase_input, "input_data", {}) or {}

    figma_file: Any = data.get("figma_file") or data.get("figma_export")
    diagram_image: str = data.get("diagram_image", "")
    voice_memo: str = data.get("voice_memo", "")

    # Passthrough: no multimodal input — return unchanged
    if not figma_file and not diagram_image and not voice_memo:
        logger.info("p00a: no multimodal input detected — passthrough")
        return TaskResult(
            output_path="",
            confidence=1.0,
            metadata={"intake_type": "passthrough"},
            success=True,
        )

    intake_type = "passthrough"
    intake_metadata: dict = {}
    requirements: str = data.get("raw_input", "") or data.get("project_description", "")

    # ── Figma ────────────────────────────────────────────────────────────────────
    if figma_file and isinstance(figma_file, dict):
        try:
            from aether_os.phases.p00a_intake.figma_parser import parse_figma
            result = parse_figma(figma_file)
            intake_type = "figma"
            intake_metadata = result
            requirements = result.get("raw_spec", requirements)
            logger.info(
                "p00a: Figma parsed — %d entities, %d screens",
                len(result.get("entities", [])),
                len(result.get("screens", [])),
            )
        except Exception as exc:
            logger.warning("p00a: Figma parse failed (non-blocking): %s", exc)

    # ── Diagram ──────────────────────────────────────────────────────────────────
    elif diagram_image:
        try:
            from aether_os.phases.p00a_intake.diagram_parser import parse_diagram
            result = parse_diagram(diagram_image)
            intake_type = "diagram"
            intake_metadata = result
            requirements = result.get("raw_spec", requirements)
            logger.info(
                "p00a: diagram parsed — %d services, %d databases",
                len(result.get("services", [])),
                len(result.get("databases", [])),
            )
        except Exception as exc:
            logger.warning("p00a: diagram parse failed (non-blocking): %s", exc)

    # ── Voice ─────────────────────────────────────────────────────────────────────
    elif voice_memo:
        try:
            from aether_os.phases.p00a_intake.voice_parser import parse_voice
            result = parse_voice(voice_memo)
            intake_type = "voice"
            intake_metadata = result
            requirements = result.get("raw_spec", requirements)
            logger.info(
                "p00a: voice parsed — domain=%s, %d functional requirements",
                result.get("domain", "general"),
                len(result.get("functional_requirements", [])),
            )
        except Exception as exc:
            logger.warning("p00a: voice parse failed (non-blocking): %s", exc)

    # Write intake metadata to output artifact for downstream phases
    import json
    artifact_path = output_dir / "intake_metadata.json"
    try:
        artifact_path.write_text(
            json.dumps({"intake_type": intake_type, **intake_metadata}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("p00a: could not write intake_metadata.json: %s", exc)

    # Inject results back into phase_input.input_data for P00 to pick up
    try:
        if hasattr(phase_input, "input_data") and isinstance(phase_input.input_data, dict):
            phase_input.input_data["requirements"] = requirements
            phase_input.input_data["raw_input"] = requirements
            phase_input.input_data["intake_type"] = intake_type
            phase_input.input_data["intake_metadata"] = intake_metadata
            # Propagate inferred domain if none already set
            inferred = intake_metadata.get("inferred_domain", "")
            if inferred and inferred != "general":
                phase_input.input_data.setdefault("domain", inferred)
    except Exception as exc:
        logger.warning("p00a: could not update phase_input.input_data: %s", exc)

    return TaskResult(
        output_path=str(artifact_path),
        confidence=0.85,
        metadata={
            "intake_type": intake_type,
            "requirements_length": len(requirements),
            "entities_found": len(intake_metadata.get("entities", [])),
        },
        success=True,
    )
