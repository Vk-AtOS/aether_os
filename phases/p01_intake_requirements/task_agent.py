"""P01 Consolidated Task Agent — intake + requirements parsing via LLM."""
from __future__ import annotations
import asyncio
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
            '    "app_tagline": "one sentence describing the core value proposition",\n'
            '    "key_features": ["feature1", "feature2"],\n'
            '    "target_users": "description of end users",\n'
            '    "estimated_complexity": "small|medium|large",\n'
            '    "requires_landing_page": false,\n'
            '    "realtime_requirements": ["entity or feature name that needs live updates"]\n'
            '  },\n'
            '  "contract": {\n'
            '    "user_count_tier": "small|medium|large",\n'
            '    "data_sensitivity": "none|internal|regulated",\n'
            '    "availability_sla": "best-effort|business-hours|24x7",\n'
            '    "needs_mobile": true,\n'
            '    "handles_money": false,\n'
            '    "geographic_scope": "single-region|multi-region",\n'
            '    "multi_tenancy": false,\n'
            '    "audit_log": false,\n'
            '    "tenant_isolation_model": "none|org_id_filter|row_level_security|separate_schema"\n'
            '  },\n'
            '  "requirements": {\n'
            '    "functional_requirements": ["req1", "req2"],\n'
            '    "non_functional_requirements": ["perf req", "security req"],\n'
            '    "entities": [{"name": "EntityName", "table": "entity_table", "fields": ["id", "name"]}],\n'
            '    "user_roles": ["admin", "user"],\n'
            '    "user_personas": [\n'
            '      {\n'
            '        "name": "role name e.g. Compliance Officer",\n'
            '        "type": "customer|admin|internal",\n'
            '        "portal": "customer|admin",\n'
            '        "key_actions": ["action1", "action2", "action3"],\n'
            '        "data_scope": "own_org|all_orgs|global"\n'
            '      }\n'
            '    ],\n'
            '    "api_endpoints": [{"method": "GET", "path": "/api/resource", "description": ""}],\n'
            '    "tech_constraints": ["Python", "PostgreSQL"]\n'
            '  }\n'
            "}"
        )
        combined = await asyncio.wait_for(
            llm.call_json(combined_prompt, task_type="analysis"),
            timeout=90,
        )
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

        # user_personas — structured persona list
        user_personas: list = requirements_doc.get("user_personas") or []
        if user_personas:
            phase_input.input_data["user_personas"] = user_personas

        # user_roles — derive from personas (backward compat) or fall back to flat list
        llm_roles: list = requirements_doc.get("user_roles") or []
        if user_personas:
            derived_roles = [p["name"] for p in user_personas if isinstance(p, dict) and p.get("name")]
            phase_input.input_data["user_roles"] = derived_roles or llm_roles
        elif llm_roles:
            phase_input.input_data["user_roles"] = llm_roles

        # New intake-level fields
        if intake_record.get("app_tagline"):
            phase_input.input_data["app_tagline"] = intake_record["app_tagline"]
        if "requires_landing_page" in intake_record:
            phase_input.input_data["requires_landing_page"] = bool(intake_record["requires_landing_page"])
        if intake_record.get("realtime_requirements") is not None:
            phase_input.input_data["realtime_requirements"] = intake_record["realtime_requirements"]

        logger.info(
            "[p01] combined extraction: project=%s entities=%d endpoints=%d personas=%d",
            intake_record.get("project_name", "?"),
            len(requirements_doc.get("entities", [])),
            len(requirements_doc.get("api_endpoints", [])),
            len(user_personas),
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

    # ── multi_tenancy extended auto-detection ────────────────────────────────
    # Flip True when domain, persona types, or raw input keywords indicate B2B/SaaS.
    _raw_lower = raw_input.lower()
    _effective_domain = (
        contract.get("domain") or intake_record.get("domain", domain) or ""
    ).lower()
    _b2b_domain = _effective_domain in ("saas", "marketplace", "ecommerce")
    _has_customer_persona = any(
        isinstance(p, dict) and p.get("type") == "customer"
        for p in phase_input.input_data.get("user_personas", [])
    )
    _b2b_keywords = ("b2b", "per company", "per org", "multi-tenant",
                     "each customer", "per client", "tenant")
    _b2b_in_raw = any(kw in _raw_lower for kw in _b2b_keywords)
    if _b2b_domain or _has_customer_persona or _b2b_in_raw:
        contract["commercial_defaults"]["multi_tenancy"] = True
        logger.info(
            "[p01] multi_tenancy=True: domain=%s customer_persona=%s b2b_raw=%s",
            _b2b_domain, _has_customer_persona, _b2b_in_raw,
        )

    # ── tenant_isolation_model ────────────────────────────────────────────────
    # Use LLM suggestion when available, else derive from multi_tenancy flag.
    llm_isolation = (contract_profile or {}).get("tenant_isolation_model", "")
    valid_isolation = {"none", "org_id_filter", "row_level_security", "separate_schema"}
    if llm_isolation in valid_isolation:
        tenant_isolation = llm_isolation
    elif contract["commercial_defaults"]["multi_tenancy"]:
        tenant_isolation = "org_id_filter"  # safe default for multi-tenant
    else:
        tenant_isolation = "none"
    contract["commercial_defaults"]["tenant_isolation_model"] = tenant_isolation
    phase_input.input_data["tenant_isolation_model"] = tenant_isolation

    # ── Record architectural decisions for downstream phases ──────────────────
    # Delegated to gate_engine to keep task_agent.py under 350 lines.
    from aether_os.phases.p01_intake_requirements.gate_engine import record_architectural_decisions
    record_architectural_decisions(
        phase_input=phase_input,
        contract=contract,
        domain=domain,
        _b2b_domain=_b2b_domain,
        _has_customer_persona=_has_customer_persona,
        _b2b_in_raw=_b2b_in_raw,
        _effective_domain=_effective_domain,
        tenant_isolation=tenant_isolation,
    )

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
    # Collect new fields from phase_input.input_data so they travel downstream
    # through accumulated_context alongside the existing contract/requirements.
    _new_fields = {
        "user_personas": phase_input.input_data.get("user_personas", []),
        "app_tagline": phase_input.input_data.get("app_tagline", ""),
        "requires_landing_page": phase_input.input_data.get("requires_landing_page", False),
        "realtime_requirements": phase_input.input_data.get("realtime_requirements", []),
        "tenant_isolation_model": phase_input.input_data.get("tenant_isolation_model", "none"),
    }
    summary = {
        "intake": intake_record,
        "requirements": requirements_doc,
        "contract": contract,
        "integration_flags": integration_flags,
        "raw_input_length": len(raw_input),
        **_new_fields,
    }
    summary["artifacts"] = {
        "intake": intake_record,
        "contract": contract,
        "integration_flags": integration_flags,
        "requirements_doc": requirements_doc,
        **_new_fields,
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

    # ── Intent verification pass ──────────────────────────────────────────────
    # Delegated to gate_engine to keep task_agent.py under 350 lines.
    from aether_os.phases.p01_intake_requirements.gate_engine import run_intent_verification
    await run_intent_verification(
        data=data,
        requirements_doc=requirements_doc,
        phase_input=phase_input,
    )

    # Confidence: based on richness of extracted spec
    _entities_extracted = requirements_doc.get("entities", [])
    _entity_count = len(_entities_extracted)
    _used_fallback = not intake_record.get("project_name") or intake_record.get("project_name") == "App"
    if _used_fallback:
        _confidence = 0.4
        _confidence_reason = "LLM extraction failed — deterministic fallback used; spec may be incomplete"
    elif _entity_count >= 4:
        _confidence = 0.92
        _confidence_reason = f"Rich spec: {_entity_count} entities extracted from LLM"
    elif _entity_count >= 2:
        _confidence = 0.75
        _confidence_reason = f"Adequate spec: {_entity_count} entities; consider adding more detail"
    else:
        _confidence = 0.55
        _confidence_reason = f"Sparse spec: only {_entity_count} entities detected; downstream phases may produce minimal output"

    # ── Entity Approval Gate (low-confidence or ambiguous) ───────────────────────
    # Delegated to gate_engine.run_entity_approval_gate to keep task_agent.py
    # under 350 lines. Gate pauses pipeline until human confirms entities.
    from aether_os.phases.p01_intake_requirements.gate_engine import run_entity_approval_gate
    _confidence, _confidence_reason, _entities_extracted = await run_entity_approval_gate(
        data=data,
        confidence=_confidence,
        confidence_reason=_confidence_reason,
        entities_extracted=_entities_extracted,
        requirements_doc=requirements_doc,
        summary=summary,
    )

    return TaskResult(
        output_path=str(summary_path),
        confidence=_confidence,
        confidence_reason=_confidence_reason,
        metadata=summary,
        success=True,
        issues=[],
    )
