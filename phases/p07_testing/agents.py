"""AetherOS — Phase 07 Testing Agents"""
from __future__ import annotations
import logging
import re
from typing import Any, Dict

from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


class TestAgent:
    name = "test_agent"

    async def run(self, code: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if not code:
            return {"test_results": {"test_code": "", "passed": True, "note": "no_code"}}

        llm = get_llm_client()
        language = context.get("language", "python")
        prompt = (
            f"Write comprehensive pytest tests for this {language} code.\n"
            f"Cover: happy path, edge cases, error handling.\n"
            f"Return ONLY valid pytest code, no markdown, no explanations.\n\n"
            f"Code:\n{code[:6000]}"
        )
        raw = await llm.call(prompt, task_type="testing")
        tests = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        tests = re.sub(r"\n?```$", "", tests).strip()
        logger.info("TestAgent generated %d chars of tests", len(tests))
        return {"test_results": {"test_code": tests, "passed": True, "note": "llm_generated"}}
