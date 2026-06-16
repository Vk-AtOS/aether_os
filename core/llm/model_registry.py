"""
AetherOS — LLM Model Registry

Routing tables and model-selection helpers that map task types to concrete
model IDs for each provider.  Kept separate from provider call logic so that
the registry can be imported without pulling in SDK dependencies.
"""
from __future__ import annotations

import os
from typing import Optional

# ── Task type → tier routing ──────────────────────────────────────────────────
_HEAVY_TASKS = {"code_generation", "security_scan", "testing", "architecture", "review"}
_LIGHT_TASKS = {"requirements", "documentation", "summarize", "classify", "intake", "portal"}

# ── Gemini model assignments ──────────────────────────────────────────────────
_GEMINI_HEAVY = "gemini-2.5-pro"
_GEMINI_LIGHT  = "gemini-2.0-flash"

# ── Amazon Bedrock default model IDs ─────────────────────────────────────────
# Amazon Nova (first-party AWS, no Marketplace subscription required).
# Nova works on every AWS commercial account with no extra activation step.
# Anthropic Claude on Bedrock requires a valid payment instrument AND, for
# newer Claude models, an AWS Marketplace subscription.  Defaulting to Nova
# because it works out-of-the-box.
_BEDROCK_HEAVY_DEFAULT = "us.amazon.nova-pro-v1:0"
_BEDROCK_LIGHT_DEFAULT = "us.amazon.nova-lite-v1:0"


def _select_model(task_type: str) -> str:
    """Route task type to the appropriate Anthropic/OpenRouter model.

    When routing through OpenRouter the model strings are provider/model slugs
    (e.g. 'minimax/minimax-m2.5:free').  Fall back to env vars so the .env
    overrides take effect without requiring a config file.
    """
    from core.config.loader import get_config
    cfg = get_config()
    # Env-var overrides mirror Claude Code's settings.local.json naming
    if task_type in _LIGHT_TASKS:
        return (
            os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
            or cfg.get("models.haiku", "minimax/minimax-m2.5:free")
        )
    return (
        os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
        or cfg.get("models.primary", "minimax/minimax-m2.5:free")
    )


def _select_gemini_model(task_type: str) -> str:
    """Route task type to the appropriate Gemini model."""
    if task_type in _HEAVY_TASKS:
        return _GEMINI_HEAVY
    return _GEMINI_LIGHT


def _select_bedrock_model(task_type: str) -> str:
    """Route task type to the appropriate Bedrock model.

    Read at call time so env-var changes take effect without restart.
    """
    explicit = os.environ.get("BEDROCK_MODEL", "").strip()
    if explicit:
        return explicit
    heavy = os.environ.get("BEDROCK_MODEL_HEAVY", _BEDROCK_HEAVY_DEFAULT).strip()
    light = os.environ.get("BEDROCK_MODEL_LIGHT", _BEDROCK_LIGHT_DEFAULT).strip()
    return heavy if task_type in _HEAVY_TASKS else light
