"""Shared phase utilities — memory context injection, prompt helpers."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def memory_hint(memory_ctx: List[Dict[str, Any]], max_chars: int = 1200) -> str:
    """
    Convert memory_ctx records into a concise LLM-injectable section.

    Returns an empty string when there's nothing useful to inject.
    The output is intended to be prepended to any phase prompt under the
    heading "Lessons from past successful runs".
    """
    if not memory_ctx:
        return ""

    sections: list[str] = []
    for rec in memory_ctx[:5]:
        if not isinstance(rec, dict):
            continue

        # Gate-failure context injected by PhaseBase on retry
        if "failure" in rec:
            sections.append(f"⚠ Previous attempt failed: {rec['failure'][:300]}")
            continue

        text = rec.get("output_text", "") or rec.get("summary", "")
        if not text or len(text) < 30:
            continue

        confidence = rec.get("confidence", 0.0)
        count = rec.get("success_count", 1)
        label = f"[confidence={confidence:.2f}, used {count}x]"
        sections.append(f"• {text[:400]} {label}")

    if not sections:
        return ""

    body = "\n".join(sections)
    if len(body) > max_chars:
        body = body[:max_chars] + "…"

    return (
        "\n\n--- LESSONS FROM PAST SUCCESSFUL RUNS ---\n"
        f"{body}\n"
        "Apply patterns above where relevant. Override if current context differs.\n"
        "--- END LESSONS ---\n"
    )


def phase_input_data(phase_input: Any) -> Dict[str, Any]:
    """Safe accessor for phase_input.input_data."""
    return phase_input.input_data if hasattr(phase_input, "input_data") else {}


def get_domain_ir(data: Dict[str, Any]) -> Dict[str, Any]:
    """The domain IR as a dict, from whichever form the context carries it.

    s02 stores only domain_ir_path (the JSON file p02b wrote); generators for Go,
    Node, mobile, desktop, CLI, serverless and the platform phases used to read
    data["domain_ir"], which nothing set, and silently built a placeholder "item"
    entity. {} when there is no IR.
    """
    ir = data.get("domain_ir")
    if isinstance(ir, dict) and ir:
        return ir
    path = data.get("domain_ir_path")
    if path:
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except (OSError, ValueError) as exc:
            logger.warning("get_domain_ir: cannot read %s: %s", path, exc)
    return {}
