"""
AetherOS — Phase 04 Code Generation Agents
Adapted from aether2 CodeGenerationAgent.
"""
from __future__ import annotations
import logging
import re
from typing import Any, Dict, Optional

from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


class CodeGenAgent:
    name = "codegen_agent"

    async def run(
        self,
        requirements_doc: str,
        architecture_doc: str,
        context: Dict[str, Any],
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        llm = get_llm_client()
        language = context.get("language", "python")

        feedback_section = (
            f"\n\nPREVIOUS FEEDBACK:\n{feedback}\nPlease fix all issues."
            if feedback else ""
        )

        prompt = (
            f"Generate complete, production-quality {language} code.\n\n"
            f"Requirements:\n{requirements_doc}\n\n"
            f"Architecture:\n{architecture_doc}"
            f"{feedback_section}\n\n"
            f"Return ONLY valid {language} code. No markdown fences. No explanations."
        )

        raw = await llm.call(prompt, task_type="code_generation")

        # Strip accidental markdown fences
        code = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        code = re.sub(r"\n?```$", "", code).strip()

        logger.info("CodeGenAgent generated %d chars of code", len(code))
        return {"generated_code": code}
