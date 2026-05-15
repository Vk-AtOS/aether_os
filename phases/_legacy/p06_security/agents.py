"""AetherOS — Phase 06 Security Agents"""
from __future__ import annotations
import logging
from typing import Any, Dict, List

from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


class SecurityAgent:
    name = "security_agent"

    async def run(self, code: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if not code:
            return {"security_report": {"issues": [], "score": 100, "status": "no_code"}}

        llm = get_llm_client()
        prompt = (
            f"Perform a comprehensive security analysis. Check for:\n"
            f"- SQL injection, command injection, SSRF\n"
            f"- Hardcoded secrets, credentials, API keys\n"
            f"- Unsafe eval/exec/pickle\n"
            f"- Path traversal, directory listing\n"
            f"- Insecure deserialization\n"
            f"- Weak cryptography (MD5, SHA1, DES)\n"
            f"- OWASP Top 10\n\n"
            f"Return JSON: {{\"issues\": [{{\"severity\": \"CRITICAL|HIGH|MEDIUM|LOW\", "
            f"\"type\": \"...\", \"description\": \"...\", \"fix\": \"...\"}}], \"score\": 0-100}}\n\n"
            f"Code:\n{code[:8000]}"
        )
        result = await llm.call_json(prompt, task_type="security_scan")
        issues: List[Dict] = result.get("issues", [])
        score = result.get("score", 100)

        # Recalculate score from issues
        for issue in issues:
            sev = issue.get("severity", "LOW").upper()
            if sev == "CRITICAL":
                score -= 25
            elif sev == "HIGH":
                score -= 15
            elif sev == "MEDIUM":
                score -= 5
            elif sev == "LOW":
                score -= 1
        score = max(0, score)
        result["score"] = score

        logger.info("SecurityAgent: %d issues found, score=%d", len(issues), score)
        return {"security_report": result}
