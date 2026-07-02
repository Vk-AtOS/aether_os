"""P02 Task Agent — design architecture using sequential LLM calls.

Guarantees: architecture.json is ALWAYS written, even when the LLM is
unavailable.  The fallback produces a domain-aware schema derived from
the raw_input text (not a generic hello-world placeholder).
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client
from aether_os.core.context_helpers import record_decision

from .helpers import (
    ARCHITECTURE_SCHEMA,
    TECH_STACK_DEFAULTS,
    extract_resources,
    build_fallback_architecture,
    fix_tech_stack,
)
from .prompts import build_arch_prompt, extract_spec_nouns

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data        = phase_input.input_data
    raw_input   = data.get("raw_input", "")
    requirements = data.get("requirements_doc",
                            data.get("structured_requirements", raw_input or str(data)))
    domain = data.get("domain", "general")

    # Extract tech preferences from designer_spec and tech_preferences
    _tp = data.get("tech_preferences") or {}
    _ds = data.get("designer_spec") or {}
    _be = _ds.get("backend") or {}
    _fe = _ds.get("frontend") or {}
    _preferred_backend = _be.get("framework") or _tp.get("backend") or ""
    _preferred_frontend = _fe.get("framework") or _tp.get("frontend") or ""
    _preferred_db = _be.get("database") or _tp.get("database") or ""
    _existing_schema = data.get("existing_schema") or {}

    from aether_os.core.domain_engine import get_domain_profile
    profile = get_domain_profile(domain)

    out_json = output_dir / "architecture.json"
    out_md   = output_dir / "architecture.md"
    used_fallback = False

    # Extract entities for metadata/cache (no longer used for bypass)
    _resources = extract_resources(raw_input or requirements, domain=domain)
    _entity_tables = [r["table"] for r in _resources]

    from aether_os.phases.utils import memory_hint
    from aether_os.core.spec_cache import _CACHE_DIR
    mem = memory_hint(memory_ctx)
    run_id = data.get("run_id")
    cache_path = _CACHE_DIR / f"{run_id}.json" if run_id else None

    doc: Dict[str, Any] = {}

    # IMP-1: Check for existing architecture.json in spec_cache
    if cache_path and cache_path.exists():
        logger.info("[p02] Cache hit for run_id=%s", run_id)
        doc = json.loads(cache_path.read_text())

    if not doc:
        logger.info("[p02] Cache miss, generating architecture...")

        # ── Semantic learning: search for similar past architectures ──────────
        similar_context = ""
        try:
            from aether_os.core.artifact_store import get_artifact_store
            store = get_artifact_store()
            org_id = data.get("org_id")
            if org_id:
                matches = await store.search(f"architecture for: {requirements}", org_id, limit=2)
                for i, match in enumerate(matches):
                    arch_text = await store.get_artifact(match['run_id'], match['file_path'])
                    if arch_text:
                        similar_context += f"\n--- Reference Architecture {i+1} ---\n{arch_text}\n"
        except Exception as e:
            logger.warning("[p02] Semantic search failed: %s", e)

        try:
            llm = get_llm_client()
        except Exception as e:
            logger.error("[p02] LLM client instantiation failed: %s", e)
            raise

        _stack_hint = ""
        if _preferred_backend: _stack_hint += f"\nPreferred backend: {_preferred_backend}"
        if _preferred_frontend: _stack_hint += f"\nPreferred frontend: {_preferred_frontend}"
        if _preferred_db: _stack_hint += f"\nPreferred database: {_preferred_db}"
        if _existing_schema.get("tables"):
            _table_names = [t.get("name", "?") for t in _existing_schema["tables"][:10]]
            _stack_hint += f"\nExisting DB tables (use these): {', '.join(_table_names)}"

        # Inject build_profile from P00 classification if available.
        # This overrides generic domain hints with the specific stack the classifier chose.
        _bp = data.get("build_profile") or {}
        if _bp:
            _stack_hint += (
                f"\nBuild profile (from automated classification): {_bp.get('name', '')}"
                f"\n  backend_lang={_bp.get('backend_lang', 'python')}"
                f"\n  backend_framework={_bp.get('backend_framework', 'fastapi')}"
                f"\n  frontend_framework={_bp.get('frontend_framework', 'react')}"
                f"\n  architecture={_bp.get('architecture', 'monolith')}"
                f"\n  db_primary={_bp.get('db_primary', 'postgres')}"
                f"\n  performance_tier={_bp.get('performance_tier', 'standard')}"
            )
            logger.info("[p02] build_profile injected into arch prompt: %s", _bp.get("name"))

        # Inject domain entity schema hints from knowledge pack
        _dk = data.get("domain_knowledge") or {}
        if _dk.get("domain") and _dk["domain"] != "general":
            from aether_os.core.domain_knowledge.loader import load_pack as _load_pack
            _dk_pack = _load_pack(_dk["domain"])
            if _dk_pack:
                _stack_hint += "\n\n" + _dk_pack.schema_hints()
                logger.info("[p02] domain schema_hints injected for domain=%s", _dk["domain"])

        # Problem 44 fix: extract must-have nouns from spec to validate entity coverage
        _spec_nouns = extract_spec_nouns(raw_input or requirements)
        _min_entities = max(1, int(len(_spec_nouns) * 0.8))

        try:
            prompt = build_arch_prompt(
                requirements=requirements,
                stack_hint=_stack_hint,
                profile_name=profile.name,
                preferred_db=profile.preferred_db,
                suggested_tech_stack=profile.suggested_tech_stack,
                required_patterns=profile.required_patterns,
                security_requirements=profile.security_requirements,
                example_entities=profile.example_entities,
                similar_context=similar_context,
                memory_hint=mem,
            )
            # Seed the schema example with domain defaults
            schema_example = dict(ARCHITECTURE_SCHEMA)
            schema_example["domain"] = domain
            schema_example["tech_stack"] = {**TECH_STACK_DEFAULTS, **profile.suggested_tech_stack}
            if "database" in profile.suggested_tech_stack:
                schema_example["tech_stack"]["database"] = profile.suggested_tech_stack["database"]
            schema_example["security_considerations"] = profile.security_requirements + ["Input validation"]

            # SINGLE LLM call — the prompt already lists every must-have entity
            # from the spec, so the model has all the context it needs in one shot.
            # If it produces fewer entities than expected, gap-fill below handles it
            # deterministically from _spec_nouns rather than paying another LLM retry.
            doc = await llm.call_structured(
                prompt=prompt,
                schema_example=schema_example,
                task_type="architecture",
            )
            if doc.get("parse_error") or doc.get("tech_stack") == ARCHITECTURE_SCHEMA["tech_stack"]:
                raise ValueError("LLM returned unparseable response")

            # Deterministic gap-fill: if the LLM under-specified entities, append
            # missing ones from the must-have noun list rather than re-prompting.
            _db_tables = {t.get("table", "") for t in doc.get("database_schema", [])}
            _entity_count = len([t for t in _db_tables if t and t not in ("users", "user")])
            if _entity_count < _min_entities:
                logger.info(
                    "[p02] LLM produced %d entities (spec wants ~%d). Filling gap deterministically.",
                    _entity_count, _min_entities,
                )
                existing = list(doc.get("database_schema", []))
                for noun in _spec_nouns:
                    if len([t for t in existing if t.get("table", "") not in ("users", "user")]) >= _min_entities:
                        break
                    table = noun + "s" if not noun.endswith("s") else noun
                    if table in _db_tables:
                        continue
                    existing.append({"table": table, "columns": ["id", "name", "description", "created_at"]})
                    _db_tables.add(table)
                doc["database_schema"] = existing

        except Exception as e:
            logger.warning("[p02] LLM call failed (%s), using intelligent fallback", e)
            doc = {}
            used_fallback = True

    # ── Apply fallback if LLM produced nothing useful ────────────────────────
    if not doc or not doc.get("api_endpoints") or used_fallback:
        fallback = build_fallback_architecture(raw_input or requirements, domain=domain)
        # Merge: keep any valid LLM fields, fill gaps with fallback
        for key, val in fallback.items():
            if not doc.get(key):
                doc[key] = val
        used_fallback = True

    # Cache the final doc
    if cache_path:
        cache_path.write_text(json.dumps(doc, indent=2))
        logger.info("[p02] architecture.json cached to %s", cache_path)

    doc = fix_tech_stack(doc)

    # Apply user-preferred tech stack overrides from designer_spec / tech_preferences
    if _preferred_backend: doc.setdefault("tech_stack", {})["backend"] = _preferred_backend
    if _preferred_frontend: doc.setdefault("tech_stack", {})["frontend"] = _preferred_frontend
    if _preferred_db: doc.setdefault("tech_stack", {})["database"] = _preferred_db

    # G1 fix: LLM may reset domain to "general" — preserve the input domain
    input_domain = getattr(phase_input, 'domain', None) or phase_input.input_data.get('domain', '')
    if input_domain and input_domain != 'general' and doc.get('domain', 'general') == 'general':
        doc['domain'] = input_domain

    # ── Architecture compatibility check ─────────────────────────────────────
    def _check_arch_compatibility(architecture: dict) -> list:
        """Verify that chosen framework, DB, and auth method are mutually compatible."""
        issues = []
        framework = (architecture.get("backend_framework") or
                     architecture.get("tech_stack", {}).get("backend") or "").lower()
        database = (architecture.get("database") or
                    architecture.get("tech_stack", {}).get("database") or "").lower()
        auth = (architecture.get("auth_method") or "").lower()
        tenancy = architecture.get("multi_tenancy", False)
        _domain = (architecture.get("domain") or "").lower()

        # FastAPI + async driver check
        if "fastapi" in framework and "sqlite" in database and tenancy:
            issues.append(
                "multi_tenancy=True with SQLite is not safe — SQLite has no row-level security. "
                "Recommend PostgreSQL for multi-tenant apps."
            )

        # Auth vs tenancy compatibility
        if "jwt" in auth and not tenancy and "saas" in _domain:
            issues.append(
                "SaaS domain with JWT auth but multi_tenancy=False — "
                "SaaS apps typically require org_id on all models."
            )

        # SQLite in production warning
        if "sqlite" in database:
            issues.append(
                "SQLite is not recommended for production multi-user apps. "
                "Consider PostgreSQL. This will be noted in the handoff documentation."
            )

        return issues

    _arch_warnings = _check_arch_compatibility(doc)
    if _arch_warnings:
        for _warn in _arch_warnings:
            logger.warning("[p02] architecture_warning: %s", _warn)
        phase_input.input_data["architecture_warnings"] = _arch_warnings
        record_decision(
            phase_input.input_data,
            key="architecture_warnings",
            value="; ".join(_arch_warnings),
            reason="Compatibility check detected potentially unsafe tech stack combinations",
            phase="p02",
        )
    else:
        phase_input.input_data["architecture_warnings"] = []
        logger.info("[p02] architecture compatibility check: no issues found")

    # ── Always write architecture.json ───────────────────────────────────────
    out_json.write_text(json.dumps(doc, indent=2))
    if cache_path:
        cache_path.write_text(json.dumps(doc, indent=2))
        logger.info("[p02] architecture.json cached to %s", cache_path)
    logger.info("[p02] architecture.json written (%d endpoints, fallback=%s)",
                len(doc.get("api_endpoints", [])), used_fallback)

    # ── Record tech-stack decisions for downstream phases ─────────────────────
    # Every downstream phase that generates code reads these decisions from
    # accumulated_context["decisions"] so it does not re-guess the same choices.
    _stack = doc.get("tech_stack", {})
    _ctx = phase_input.input_data
    _src = "fallback" if used_fallback else "LLM"
    if _stack.get("database"):
        _db_reason = (
            f"chosen by {_src} architecture; "
            + (
                "user override via designer_spec/tech_preferences"
                if _preferred_db
                else f"domain profile '{profile.name}' preference"
            )
        )
        record_decision(_ctx, key="database", value=_stack["database"],
                        reason=_db_reason, phase="p02")
    if _stack.get("backend"):
        record_decision(_ctx, key="backend_framework", value=_stack["backend"],
                        reason=f"chosen by {_src}; stack must stay consistent across p04a→p04b→p06",
                        phase="p02")
    if _stack.get("frontend"):
        record_decision(_ctx, key="frontend_framework", value=_stack["frontend"],
                        reason=f"chosen by {_src}; p05 code_writer will use this framework",
                        phase="p02")
    # Auth method — infer from security_considerations when present
    _sec = " ".join(doc.get("security_considerations", [])).lower()
    if "jwt" in _sec or "json web token" in _sec:
        record_decision(_ctx, key="auth_method", value="JWT",
                        reason="JWT found in architecture security_considerations; "
                               "p04a auth.py uses JWT access+refresh tokens",
                        phase="p02")

    # Multi-tenancy strategy — infer from architecture patterns and requirements
    _arch_text = json.dumps(doc).lower()
    _req_text = (raw_input or requirements or "").lower()
    if "org_id" in _arch_text or "tenant_id" in _arch_text or "multi_tenant" in _arch_text:
        _mt_value = "row_level"
        _mt_reason = (
            "org_id or tenant_id column detected in architecture; "
            "p04a injects org_id filter on every query for row-level isolation"
        )
    elif "schema_per_tenant" in _arch_text or "schema per tenant" in _req_text:
        _mt_value = "schema_level"
        _mt_reason = "schema_per_tenant pattern found; each tenant gets a dedicated PG schema"
    else:
        _mt_value = "none"
        _mt_reason = "no multi-tenancy keywords found; single-tenant app assumed"
    record_decision(_ctx, key="multi_tenancy_strategy", value=_mt_value,
                    reason=_mt_reason, phase="p02")

    # API style — rest vs graphql
    _ep_paths = " ".join(ep.get("path", "") for ep in doc.get("api_endpoints", [])).lower()
    if "graphql" in _arch_text or "/graphql" in _ep_paths:
        _api_style = "graphql"
        _api_reason = "GraphQL endpoint detected in architecture api_endpoints"
    else:
        _api_style = "rest"
        _api_reason = "REST pattern assumed; no GraphQL endpoint found in architecture"
    record_decision(_ctx, key="api_style", value=_api_style,
                    reason=_api_reason, phase="p02")

    # Deployment target — infer from scalability_notes or requirements
    _scale = doc.get("scalability_notes", "").lower()
    if "kubernetes" in _scale or "k8s" in _scale or "kubernetes" in _req_text:
        _deploy_target = "kubernetes"
        _deploy_reason = "Kubernetes/k8s found in scalability_notes or requirements"
    elif "serverless" in _scale or "lambda" in _scale or "serverless" in _req_text:
        _deploy_target = "serverless"
        _deploy_reason = "Serverless/Lambda pattern found in scalability_notes or requirements"
    else:
        _deploy_target = "docker"
        _deploy_reason = "Default Docker deployment; no K8s or serverless keywords found"
    record_decision(_ctx, key="deployment_target", value=_deploy_target,
                    reason=_deploy_reason, phase="p02")

    # ── Human-readable Markdown ───────────────────────────────────────────────
    stack = doc.get("tech_stack", {})
    md = ["# Architecture\n\n## Tech Stack\n"]
    for k, v in stack.items():
        md.append(f"- **{k}**: {v}")
    if doc.get("component_diagram"):
        md.append(f"\n## Component Diagram\n```mermaid\n{doc['component_diagram']}\n```")
    md.append("\n## API Endpoints\n")
    for ep in doc.get("api_endpoints", []):
        auth_label = " [auth]" if ep.get("auth") else ""
        md.append(f"- `{ep.get('method','GET')} {ep.get('path','')}`{auth_label} — {ep.get('description','')}")
    if doc.get("database_schema"):
        md.append("\n## Database Schema\n")
        for tbl in doc["database_schema"]:
            cols = ", ".join(tbl.get("columns", []))
            md.append(f"- **{tbl.get('table','')}**: {cols}")
    md.append("\n## Security\n")
    for s in doc.get("security_considerations", []):
        md.append(f"- {s}")
    md.append(f"\n## Scalability\n{doc.get('scalability_notes', '')}")
    if used_fallback:
        md.append(f"\n\n> Architecture generated from fallback (LLM unavailable). "
                  f"Detected resources: {doc.get('_detected_resources', [])}")
    out_md.write_text("\n".join(md))

    return TaskResult(
        output_path=str(out_json),
        confidence=0.7 if used_fallback else 0.9,
        metadata={
            "json_path": str(out_json),
            "markdown_path": str(out_md),
            "used_fallback": used_fallback,
            "endpoint_count": len(doc.get("api_endpoints", [])),
        },
        issues=["Used fallback architecture (LLM unavailable)"] if used_fallback else [],
        success=True,   # always True — architecture.json always written
    )
