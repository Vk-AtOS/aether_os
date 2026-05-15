"""P00 Memory Agent — retrieve and store intake memories."""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from aether_os.phases.base import PhaseBase

logger = logging.getLogger(__name__)


async def before(input_hash: str, limit: int = 5) -> List[Dict[str, Any]]:
    base = PhaseBase()
    return await base.memory_before(input_hash, "p00_intake", limit)


async def after(input_hash: str, output_path: str, confidence: float,
                domain: str = "general") -> None:
    base = PhaseBase()
    await base.memory_after("p00_intake", input_hash, output_path, confidence, domain)
