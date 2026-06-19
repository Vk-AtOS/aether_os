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
    from aether_os.core.domain_knowledge.loader import build_prompt_prefix
    mem = memory_hint(memory_ctx)
    _domain_prefix = build_prompt_prefix(domain)

    # ── SINGLE LLM call: intake + contract + requirements in one shot ────────
    # The previous version made three sequential call_json calls (intake,
    # scalability contract, requirements doc). Nova / Llama handle the whole
    # thing in one prompt, so we ask for one combined JSON object and split
    # it locally. Cuts phase time from ~45s+ to ~15s on Nova Pro.
    intake_record: dict = {}
    contract_profile: dict = {}
    requirements_doc: dict = {}
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        combined_prompt = (
            f"{_domain_prefix}"
            "You are a senior requirements analyst. Convert the following raw project "
            "description into a SINGLE structured JSON document.\n\n"
            f"Raw Input:\n{raw_input[:4000]}\n\n"
            f"{mem}"
            "Return ONLY this JSON (no markdown, no commentary):\n"
            "{\n"
            '  "intake": {\n'
            '    "project_name": "short CamelCase name",\n'
            '    "domain": "one of: saas, ecommerce, healthcare, fintech, logistics, education, gym_fitness, sports, hospitality, hrm, crm, restaurant, real_estate, general",\n'
            '    "summary": "2-3 sentence summary",\n'
            '    "key_features": ["feature1", "feature2"],\n'
            '    "target_users": "description of end users",\n'
            '    "estimated_complexity": "small|medium|large"\n'
            '  },\n'
            '  "contract": {\n'
            '    "user_count_tier": "small|medium|large",\n'
            '    "data_sensitivity": "none|internal|regulated",\n'
            '    "availability_sla": "best-effort|business-hours|24x7",\n'
            '    "needs_mobile": true,\n'
            '    "handles_money": false,\n'
            '    "geographic_scope": "single-region|multi-region",\n'
            '    "multi_tenancy": false,\n'
            '    "audit_log": false\n'
            '  },\n'
            '  "requirements": {\n'
            '    "functional_requirements": ["req1", "req2"],\n'
            '    "non_functional_requirements": ["perf req", "security req"],\n'
            '    "entities": [{"name": "EntityName", "table": "entity_table", "fields": ["id", "name"]}],\n'
            '    "user_roles": ["admin", "user"],\n'
            '    "api_endpoints": [{"method": "GET", "path": "/api/resource", "description": ""}],\n'
            '    "tech_constraints": ["Python", "PostgreSQL"]\n'
            '  }\n'
            "}"
        )
        combined = await llm.call_json(combined_prompt, task_type="analysis")
        intake_record = combined.get("intake") or {}
        contract_profile = combined.get("contract") or {}
        requirements_doc = combined.get("requirements") or {}
        if intake_record:
            phase_input.input_data.update({
                k: v for k, v in intake_record.items()
                if k not in phase_input.input_data or not phase_input.input_data[k]
            })
        if requirements_doc.get("entities"):
            phase_input.input_data["entities"] = requirements_doc["entities"]
        if requirements_doc.get("api_endpoints"):
            phase_input.input_data["api_endpoints"] = requirements_doc["api_endpoints"]
        if requirements_doc.get("user_roles"):
            phase_input.input_data["user_roles"] = requirements_doc["user_roles"]
        logger.info(
            "[p01] combined extraction: project=%s entities=%d endpoints=%d",
            intake_record.get("project_name", "?"),
            len(requirements_doc.get("entities", [])),
            len(requirements_doc.get("api_endpoints", [])),
        )
    except Exception as exc:
        logger.warning("[p01] combined LLM call failed: %s — using deterministic fallback", exc)
        intake_record = {"project_name": "App", "domain": domain, "summary": raw_input[:200]}
        requirements_doc = {"functional_requirements": [raw_input[:500]]}

    # ── Build project_contract (LLM-inferred + safe defaults) ────────────────
    contract: dict = {
        "project_name": intake_record.get("project_name", "App"),
        "domain": intake_record.get("domain", domain),
        "summary": intake_record.get("summary", ""),
        "scalability": {
            "user_count_tier": "small",
            "data_sensitivity": "internal",
            "availability_sla": "best-effort",
            "needs_mobile": False,
            "handles_money": False,
            "geographic_scope": "single-region",
        },
        "commercial_defaults": {
            "multi_tenancy": False,
            "audit_log": False,
            "soft_deletes": True,
            "rate_limiting": True,
            "pagination_required": True,
        },
    }
    if contract_profile:
        contract["scalability"].update({
            k: contract_profile[k] for k in (
                "user_count_tier", "data_sensitivity", "availability_sla",
                "needs_mobile", "handles_money", "geographic_scope",
            ) if k in contract_profile
        })
        contract["commercial_defaults"].update({
            k: contract_profile[k] for k in ("multi_tenancy", "audit_log")
            if k in contract_profile
        })
        # audit_log auto-on for regulated/money
        if contract_profile.get("data_sensitivity") == "regulated" or contract_profile.get("handles_money"):
            contract["commercial_defaults"]["audit_log"] = True
            contract["commercial_defaults"]["multi_tenancy"] = True
    phase_input.input_data["project_contract"] = contract
    logger.info(
        "[p01] contract: tier=%s sensitivity=%s money=%s",
        contract["scalability"]["user_count_tier"],
        contract["scalability"]["data_sensitivity"],
        contract["scalability"]["handles_money"],
    )

    # ── Integration Flags (regex over raw input — no LLM needed) ─────────────
    integration_flags = {
        "needs_payments": any(kw in raw_input.lower() for kw in ["payment", "stripe", "billing", "checkout", "subscription"]),
        "needs_email": any(kw in raw_input.lower() for kw in ["email", "smtp", "notification", "message", "mail"]),
        "needs_file_upload": any(kw in raw_input.lower() for kw in ["upload", "file", "image", "pdf", "storage", "document"]),
        "needs_maps": any(kw in raw_input.lower() for kw in ["map", "location", "gps", "google maps", "address"]),
        "needs_sms": any(kw in raw_input.lower() for kw in ["sms", "text message", "twilio", "phone"]),
        "needs_calendar": any(kw in raw_input.lower() for kw in ["calendar", "schedule", "appointment", "booking", "reservation"]),
    }
    phase_input.input_data["integration_flags"] = integration_flags
    logger.info("[p01] integration_flags: %s", [k for k, v in integration_flags.items() if v])

    (output_dir / "project_contract.json").write_text(
        json.dumps(contract, indent=2, default=str)
    )

    # ── Write outputs ─────────────────────────────────────────────────────────
    summary = {
        "intake": intake_record,
        "requirements": requirements_doc,
        "contract": contract,
        "integration_flags": integration_flags,
        "raw_input_length": len(raw_input),
    }
    summary["artifacts"] = {
        "intake": intake_record,
        "contract": contract,
        "integration_flags": integration_flags,
        "requirements_doc": requirements_doc,
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
