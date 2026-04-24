"""AetherOS — Phase 03 Scaffolding Agents"""
from __future__ import annotations
import logging
from typing import Any, Dict

from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


class ScaffoldingAgent:
    name = "scaffolding_agent"

    async def run(self, architecture_doc: str, context: Dict[str, Any]) -> Dict[str, Any]:
        llm = get_llm_client()
        language = context.get("language", "python")
        project_name = context.get("project_name", "untitled")
        prompt = (
            f"Generate the complete file/directory scaffold for a {language} project '{project_name}'.\n"
            f"Return JSON: {{\"files\": [\"path/to/file.py\", ...], \"description\": \"...\"}}\n\n"
            f"Architecture:\n{architecture_doc}"
        )
        result = await llm.call_json(prompt, task_type="requirements")
        logger.info("ScaffoldingAgent generated %d files", len(result.get("files", [])))
        return {"scaffold_manifest": result}
