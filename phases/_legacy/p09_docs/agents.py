"""AetherOS — Phase 09 Documentation Agents"""
from __future__ import annotations
import logging
from typing import Any, Dict

from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


class DocumentationAgent:
    name = "documentation_agent"

    async def run(self, code: str, context: Dict[str, Any]) -> Dict[str, Any]:
        llm = get_llm_client()
        project_name = context.get("project_name", "untitled")
        doc_type = context.get("doc_type", "readme")
        prompt = (
            f"Generate comprehensive {doc_type} documentation for project '{project_name}'.\n\n"
            f"Include: overview, installation, usage, API reference, examples, contributing guide.\n\n"
            f"Code:\n{code[:4000]}"
        )
        result = await llm.call(prompt, task_type="documentation")
        logger.info("DocumentationAgent generated %d chars", len(result))
        return {"docs": result}
