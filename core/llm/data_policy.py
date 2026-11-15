"""Which model pools may see which data (KAN-15, same rules as Velaris velaris/intel/policy.py, D6).

Levels: public, internal, restricted. No level, or one that is not a level -> restricted (fail closed). A prompt the
pattern screen (core/llm/sensitivity.py) flags is restricted whatever the caller says.

  * restricted: never a free or third-party pool: no OpenRouter at all, no ":free" model on any provider.
  * public / internal: the community pools (OpenRouter, any ":free" model) only when the operator opted in with
    ALLOW_COMMUNITY_LLM=1, because they may log or train on what they receive.

One function decides; the router applies it as the LAST step of building a chain (an org's stored key can no longer
re-inject a pool) and call_openrouter applies it again, so callers that bypass the router (council, compressor) are
covered too.
"""
from __future__ import annotations

import os
from typing import Iterable, List, Optional

from aether_os.core.llm.sensitivity import classify

LEVELS = ("public", "internal", "restricted")
DEFAULT_LEVEL = "internal"      # AetherOS callers carry no label; the pattern screen raises it to restricted


def effective_level(level: Optional[str], *texts: str) -> str:
    if level is not None and level not in LEVELS:
        return "restricted"
    if classify(*texts):
        return "restricted"
    return level or DEFAULT_LEVEL


def community_allowed() -> bool:
    return os.environ.get("ALLOW_COMMUNITY_LLM", "").strip().lower() in ("1", "true", "yes")


def is_community(provider: str, model: str) -> bool:
    return provider == "openrouter" or model.endswith(":free")


def permits(provider: str, model: str, level: str) -> bool:
    if not is_community(provider, model):
        return True
    return level != "restricted" and community_allowed()


def filter_chain(chain: Iterable, level: str) -> List:
    """The specs (anything with .provider and .model) the level allows, in order."""
    return [s for s in chain if permits(s.provider, s.model, level)]
