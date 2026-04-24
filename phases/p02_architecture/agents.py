"""
AetherOS — Phase 02 Architecture Agents
Adapted from aether2 ArchitectureAgent, uses unified LLM client.
"""
from __future__ import annotations
import logging
from typing import Any, Dict

from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


class ArchitectureAgent:
    """Proposes software architecture from requirements."""

    name = "architecture_agent"

    async def run(self, requirements_doc: str, context: Dict[str, Any]) -> Dict[str, Any]:
        llm = get_llm_client()
        language = context.get("language", "python")
        prompt = (
            f"Propose a detailed software architecture for the following {language} project.\n\n"
            f"Include:\n"
            f"- High-level component diagram (text)\n"
            f"- Data models / schemas\n"
            f"- API design (endpoints, methods)\n"
            f"- Technology choices with justification\n"
            f"- Directory structure\n"
            f"- Inter-component communication\n\n"
            f"Requirements:\n{requirements_doc}"
        )
        result = await llm.call(prompt, task_type="requirements")
        logger.info("ArchitectureAgent complete, output length=%d", len(result))
        return {"architecture_doc": result}
