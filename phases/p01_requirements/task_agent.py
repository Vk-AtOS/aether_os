"""P01 Task Agent — structure requirements with structured output."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)

REQUIREMENTS_SCHEMA = {
    "functional_requirements": [
        "User can create items",
        "User can read items"
    ],
    "non_functional_requirements": [
        "Response time under 500ms"
    ],
    "constraints": [
        "Must use Python backend"
    ],
    "acceptance_criteria": [
        "All endpoints return JSON",
        "Auth required for write operations",
        "Tests cover 70% of code"
    ],
    "tech_stack_preferences": [
        "FastAPI", "PostgreSQL", "React"
    ],
    "out_of_scope": [
        "Mobile application"
    ],
    "estimated_complexity": "medium",
    "domain": "general"
}

def apply_defaults(result: dict, raw_input: str) -> dict:
    defaults = {
        "functional_requirements": [
            f"Implement: {raw_input[:100]}"],
        "non_functional_requirements": [
            "System must be reliable"],
        "constraints": [],
        "acceptance_criteria": [
            "System works as described",
            "Code has test coverage",
            "Documentation provided"
        ],
        "tech_stack_preferences": [],
        "out_of_scope": [],
        "estimated_complexity": "medium",
        "domain": "general"
    }
    for key, default in defaults.items():
        if not result.get(key):
            result[key] = default
    return result

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    raw = data.get("structured_requirements", data.get("raw_text", str(data)))
    domain = data.get("domain", "general")
    llm = get_llm_client()
    
    from aether_os.core.domain_engine import get_domain_profile
    profile = get_domain_profile(domain)

    # If short, research the domain first (optional, keeping for quality)
    research_context = ""
    if len(raw.split()) < 100:
        try:
            from gpt_researcher import GPTResearcher
            researcher = GPTResearcher(
                query=f"technical requirements for: {raw} in {domain} domain",
                report_type="research_report",
            )
            await researcher.conduct_research()
            research_context = f"\n\nDomain research:\n{await researcher.write_report()}"
        except Exception as e:
            logger.debug("GPTResearcher skipped: %s", e)

    mem_hint = ""
    if memory_ctx:
        mem_hint = f"\n\nPrevious similar requirements:\n{memory_ctx[0].get('output_text','')}"

    prompt = (
        f"Structure software requirements for: {raw}{research_context}{mem_hint}\n\n"
        f"Domain Profile ({profile.name}):\n"
        f"- Required Patterns: {', '.join(profile.required_patterns)}\n"
        f"- Security: {', '.join(profile.security_requirements)}\n"
        f"- Compliance: {', '.join(profile.compliance_notes)}"
    )
    
    # Use call_structured with the requested schema
    doc = await llm.call_structured(
        prompt=prompt,
        schema_example={**REQUIREMENTS_SCHEMA, "domain": domain},
        task_type="requirements"
    )

    # Inject mandatory domain NFRs if missing
    if domain != "general":
        nfrs = doc.get("non_functional_requirements", [])
        for pattern in profile.required_patterns:
            if pattern not in str(nfrs):
                nfrs.append(f"Mandatory Pattern: {pattern}")
        doc["non_functional_requirements"] = nfrs

    # Fill missing keys with defaults
    doc = apply_defaults(doc, raw)

    # Write markdown for human readability
    md_lines = [f"# Requirements Document\n\n**Domain:** {doc.get('domain','')}\n"
                f"**Complexity:** {doc.get('estimated_complexity','medium')}\n"]
    
    sections = [
        "functional_requirements", "non_functional_requirements", "constraints",
        "acceptance_criteria", "tech_stack_preferences", "out_of_scope"
    ]
    
    for section in sections:
        items = doc.get(section, [])
        md_lines.append(f"\n## {section.replace('_',' ').title()}\n")
        if isinstance(items, list):
            md_lines.extend(f"- {i}" for i in items)
        else:
            md_lines.append(str(items))
    md_content = "\n".join(md_lines)

    out_md = output_dir / "requirements.md"
    out_json = output_dir / "requirements.json"
    out_md.write_text(md_content)
    out_json.write_text(json.dumps(doc, indent=2))

    return TaskResult(
        output_path=str(out_json), # Gate now expects the JSON file for validation
        confidence=0.9,
        metadata={
            "json_path": str(out_json), 
            "markdown_path": str(out_md),
            "requirements_doc": doc,
            "domain": domain
        },
        issues=[],
        success=True,
    )
