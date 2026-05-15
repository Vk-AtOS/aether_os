"""
AetherOS — Phase 01 Requirements Agents
Adapted from aether2/aether/agents/specialists.py (RequirementsAgent, RepoReasoningAgent).
Uses unified LLM client instead of Ollama engine.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


class RequirementsAgent:
    """Parses natural language requirements into structured goals."""

    name = "requirements_agent"

    async def run(self, requirement: str, context: Dict[str, Any]) -> Dict[str, Any]:
        llm = get_llm_client()
        prompt = (
            f"Parse these requirements into structured format with:\n"
            f"- Goals (numbered list)\n"
            f"- Constraints\n"
            f"- Technical stack\n"
            f"- User stories\n"
            f"- Acceptance criteria\n\n"
            f"Requirements:\n{requirement}"
        )
        result = await llm.call(prompt, task_type="requirements")
        logger.info("RequirementsAgent complete, output length=%d", len(result))
        return {"requirements_doc": result, "raw_input": requirement}


class RepoReasoningAgent:
    """Analyses an existing repository to extract context for requirements."""

    name = "repo_reasoning_agent"

    async def run(self, repo_path: str, context: Dict[str, Any]) -> Dict[str, Any]:
        root = Path(repo_path)
        if not root.exists():
            return {"repo_analysis": {"error": f"Path not found: {repo_path}"}}

        dirs: List[str] = []
        files: List[str] = []
        py_files: List[str] = []

        for item in root.rglob("*"):
            if item.is_dir():
                dirs.append(item.name)
            else:
                files.append(item.name)
                if item.suffix == ".py":
                    py_files.append(str(item.relative_to(root)))

        analysis = {
            "root": str(root),
            "directories": dirs[:50],
            "files": files[:100],
            "python_files": py_files[:50],
            "summary": f"{len(dirs)} dirs, {len(files)} files, {len(py_files)} Python files",
        }
        logger.info("RepoReasoningAgent analysed %s: %s", repo_path, analysis["summary"])
        return {"repo_analysis": analysis}
