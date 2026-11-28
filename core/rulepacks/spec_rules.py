"""Rule-pack prompt text for the code-writing model calls of a run (KAN-243).

    security_rules_for(context, "backend")    # SECURITY RULES for a prompt that writes backend code
    security_rules_for(context, "frontend")   # ... for a React page or component

The stack features come from the run's spec (the accumulated context), never from guessing at the output: every app
the platform generates is FastAPI + SQLAlchemy + JWT auth + React and ships Dockerfiles; file uploads and LLM agents are
added when the spec asks for them. Only the modules that apply to the surface are included, so each prompt stays small.
"""
from __future__ import annotations

import re

from aether_os.core.rulepacks.security_rules import security_prompt_rules

MAX_RULES_CHARS = 6000   # a prompt carries at most this much rule text (design + security), see tests
_UPLOAD_TYPES = {"file", "image", "upload", "attachment", "binary", "blob"}
_AGENT = re.compile(r"\b(ai agent|llm|chat ?bot|assistant|gpt|claude|openai|anthropic|rag|copilot|agentic)\b", re.I)
SURFACES = {"backend": ("fastapi", "sqlalchemy", "jwt-auth", "file-upload", "llm-agent"),
            "frontend": ("react", "file-upload"), "infra": ("docker",)}


def _field_types(context: dict) -> set[str]:
    types: set[str] = set()
    for ent in context.get("entities") or []:
        for f in (ent.get("fields") or []) if isinstance(ent, dict) else []:
            if isinstance(f, dict):
                types.add(str(f.get("type") or "").lower())
    return types


def spec_features(context: dict) -> list[str]:
    """Every security module that applies to this run's app."""
    context = context if isinstance(context, dict) else {}
    text = " ".join(str(context.get(k) or "") for k in ("raw_input", "app_tagline", "description"))
    build = " ".join(str(b) for b in (context.get("build_types") or []))
    features = ["fastapi", "sqlalchemy", "jwt-auth", "react", "docker"]
    if _field_types(context) & _UPLOAD_TYPES or re.search(r"\bupload", text, re.I):
        features.append("file-upload")
    if _AGENT.search(text) or re.search(r"agent|llm|\bai\b", build, re.I) or context.get("agent_spec"):
        features.append("llm-agent")
    return features


def security_rules_for(context: dict, surface: str) -> str:
    """SECURITY RULES text for one surface ("backend", "frontend" or "infra") of this run."""
    wanted = SURFACES[surface]
    return security_prompt_rules([f for f in spec_features(context) if f in wanted])
