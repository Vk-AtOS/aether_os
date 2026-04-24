"""Memory Agent for p01_requirements."""
from __future__ import annotations
from typing import Any, Dict, List
from aether_os.phases.base import PhaseBase

async def before(input_hash: str, limit: int = 5) -> List[Dict[str, Any]]:
    return await PhaseBase().memory_before(input_hash, "p01_requirements", limit)

async def after(input_hash: str, output_path: str, confidence: float,
                domain: str = "general") -> None:
    await PhaseBase().memory_after("p01_requirements", input_hash, output_path, confidence, domain)
