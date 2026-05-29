"""P01 Consolidated Task Agent — intake + requirements parsing via LLM."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    raw_input: str = data.get("raw_input", "") or data.get("requirements", "") or ""
    domain: str = data.get("domain", "general")

    from aether_os.phases.utils import memory_hint
    mem = memory_hint(memory_ctx)

    # ── Step 1: Extract structured intake record ──────────────────────────────
    intake_record: dict = {}
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        intake_prompt = (
            "You are a requirements analyst. Given the following raw project description, "
            "extract a structured intake record.\n\n"
            f"Raw Input:\n{raw_input[:3000]}\n\n"
            + mem +
            "Return JSON with these fields:\n"
            '{"project_name": "short CamelCase name", '
            '"domain": "one of: saas, ecommerce, healthcare, fintech, logistics, education, general", '
            '"summary": "2-3 sentence summary", '
            '"key_features": ["feature1", "feature2", ...], '
            '"target_users": "description of end users", '
            '"estimated_complexity": "small|medium|large"}'
        )
        intake_record = await llm.call_json(intake_prompt, task_type="analysis")
        if intake_record:
            phase_input.input_data.update({
                k: v for k, v in intake_record.items()
                if k not in phase_input.input_data or not phase_input.input_data[k]
            })
        logger.info("[p01] intake extracted: %s", intake_record.get("project_name", "?"))
    except Exception as exc:
        logger.warning("[p01] intake LLM call failed: %s", exc)
        intake_record = {"project_name": "App", "domain": domain, "summary": raw_input[:200]}

    # ── Step 2: Generate structured requirements document ─────────────────────
    requirements_doc: dict = {}
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        req_prompt = (
            "You are a senior software architect. Convert the following project description "
            "into a structured requirements specification.\n\n"
            f"Project: {intake_record.get('project_name', 'App')}\n"
            f"Domain: {intake_record.get('domain', domain)}\n"
            f"Description:\n{raw_input[:4000]}\n\n"
            "Return JSON:\n"
            '{"functional_requirements": ["req1", "req2", ...], '
            '"non_functional_requirements": ["perf req", "security req", ...], '
            '"entities": [{"name": "EntityName", "table": "entity_table", "fields": ["id", "name", ...]}, ...], '
            '"user_roles": ["admin", "user", ...], '
            '"api_endpoints": [{"method": "GET", "path": "/api/resource", "description": "..."}, ...], '
            '"tech_constraints": ["Python", "PostgreSQL", ...]}'
        )
        requirements_doc = await llm.call_json(req_prompt, task_type="analysis")
        if requirements_doc:
            # Propagate entities and endpoints to downstream phases
            if requirements_doc.get("entities"):
                phase_input.input_data["entities"] = requirements_doc["entities"]
            if requirements_doc.get("api_endpoints"):
                phase_input.input_data["api_endpoints"] = requirements_doc["api_endpoints"]
            if requirements_doc.get("user_roles"):
                phase_input.input_data["user_roles"] = requirements_doc["user_roles"]
        logger.info("[p01] requirements parsed: %d entities, %d endpoints",
                    len(requirements_doc.get("entities", [])),
                    len(requirements_doc.get("api_endpoints", [])))
    except Exception as exc:
        logger.warning("[p01] requirements LLM call failed: %s", exc)
        requirements_doc = {"functional_requirements": [raw_input[:500]]}

    # ── Write outputs ─────────────────────────────────────────────────────────
    summary = {
        "intake": intake_record,
        "requirements": requirements_doc,
        "raw_input_length": len(raw_input),
    }
    summary_path = output_dir / "requirements.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    # Also write a human-readable requirements.md
    md_lines = [
        f"# Requirements: {intake_record.get('project_name', 'App')}\n",
        f"**Domain:** {intake_record.get('domain', domain)}  ",
        f"**Complexity:** {intake_record.get('estimated_complexity', 'medium')}\n",
        f"## Summary\n{intake_record.get('summary', raw_input[:300])}\n",
        "## Functional Requirements\n",
    ]
    for req in requirements_doc.get("functional_requirements", []):
        md_lines.append(f"- {req}")
    md_lines.append("\n## Non-Functional Requirements\n")
    for req in requirements_doc.get("non_functional_requirements", []):
        md_lines.append(f"- {req}")
    md_lines.append("\n## Key Entities\n")
    for ent in requirements_doc.get("entities", []):
        md_lines.append(f"- **{ent.get('name', '')}** (`{ent.get('table', '')}`)")
    (output_dir / "requirements.md").write_text("\n".join(md_lines))

    return TaskResult(
        output_path=str(summary_path),
        confidence=0.90,
        metadata=summary,
        success=True,
        issues=[],
    )
