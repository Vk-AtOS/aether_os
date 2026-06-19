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

    # ── Always write architecture.json ───────────────────────────────────────
    out_json.write_text(json.dumps(doc, indent=2))
    if cache_path:
        cache_path.write_text(json.dumps(doc, indent=2))
        logger.info("[p02] architecture.json cached to %s", cache_path)
    logger.info("[p02] architecture.json written (%d endpoints, fallback=%s)",
                len(doc.get("api_endpoints", [])), used_fallback)

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
