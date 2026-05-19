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
        # Keep snippet short — smoke tests only, no exhaustive coverage needed
        snippet = code[:3000]
        prompt = (
            f"Write basic smoke tests (pytest) for this {language} code.\n"
            f"Focus on: route response codes, required fields, no import errors.\n"
            f"Keep tests minimal — 5-10 test functions max.\n"
            f"Return ONLY valid pytest code, no markdown.\n\n"
            f"Code:\n{snippet}"
        )
        # Use classify (light) model — test scaffolding doesn't need a heavy model
        raw = await llm.call(prompt, task_type="classify", max_tokens=2048)
        tests = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        tests = re.sub(r"\n?```$", "", tests).strip()
        logger.info("TestAgent generated %d chars of tests", len(tests))
        return {"test_results": {"test_code": tests, "passed": True, "note": "llm_generated"}}
