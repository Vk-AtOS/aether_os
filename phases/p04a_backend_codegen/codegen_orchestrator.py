"""
P04a Codegen Orchestrator — IR fast-path helpers
Extracted from task_agent.py to keep it under 400 lines.

Contains:
  run_ir_fastpath() — generate models/schemas/seed/crud from domain_ir.json
                       including workflow transition map building and disk writes.
"""
from __future__ import annotations

import json
import logging
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _build_workflow_transitions(ir: Any, domain: str) -> Dict[str, Any]:
    """Build a workflow transition map for CRUD PATCH guard injection.

    Priority: domain knowledge pack (explicit state machine) →
              IR workflow steps (linear chain derived from step order).
    Returns a dict mapping entity_name → {state: [next_states, ...]}.
    """
    _workflow_transitions: Dict[str, Any] = {}

    try:
        from aether_os.core.domain_knowledge.loader import load_pack as _load_pack
        _pack = _load_pack(domain)
        if _pack:
            for _wf in _pack.workflows:
                if _wf.transitions:
                    _workflow_transitions[_wf.entity] = _wf.transitions
    except Exception as _wf_exc:
        logger.warning("[p04a] could not load domain pack workflows: %s", _wf_exc)

    # Derive linear chains from IR workflow steps for entities not already
    # covered by the domain pack (step[i] → [step[i+1]]).
    for _ir_wf in ir.workflows:
        if _ir_wf.entity and _ir_wf.entity not in _workflow_transitions:
            _steps = [s.name for s in _ir_wf.steps]
            if len(_steps) >= 2:
                _trans: Dict[str, List[str]] = {}
                for _i, _step in enumerate(_steps[:-1]):
                    _trans[_step] = [_steps[_i + 1]]
                _trans[_steps[-1]] = []  # terminal state
                _workflow_transitions[_ir_wf.entity] = _trans

    return _workflow_transitions


def _write_workflow_transitions_json(
    workflow_transitions: Dict[str, Any],
    output_dir: Path,
) -> None:
    """Persist workflow_transitions.json into the generated project's scripts/ dir."""
    if not workflow_transitions:
        return
    import datetime as _dt
    _scripts_dir = output_dir / "scripts"
    _scripts_dir.mkdir(parents=True, exist_ok=True)
    _wf_json: Dict[str, Any] = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "entities": {},
    }
    for _ent_name, _trans_map in workflow_transitions.items():
        _terminal = [s for s, nxt in _trans_map.items() if not nxt]
        _wf_json["entities"][_ent_name] = {
            "transitions": _trans_map,
            "terminal_states": _terminal,
        }
    (_scripts_dir / "workflow_transitions.json").write_text(
        json.dumps(_wf_json, indent=2)
    )
    logger.info(
        "[p04a] wrote workflow_transitions.json for %d entities",
        len(workflow_transitions),
    )


def run_pipeline_and_seed_steps(
    *,
    src_dir: Path,
    routers_dir: Path,
    output_dir: Path,
    domain: str,
    project_name: str,
    entities: List[Dict[str, Any]],
    seed_code: str,
    seed_vocabulary: Dict[str, Any],
    realtime_features: List[Any],
    data: Dict[str, Any],
    raw_input: str,
    multi_tenancy: bool,
    fix_relative_imports_fn: Any,
    generate_sse_router_fn: Any,
    generate_audit_fn: Any,
    generate_cache_fn: Any,
    generate_permissions_fn: Any,
    fallback_seed_fn: Any,
    detect_patterns_fn: Any,
    inject_patterns_fn: Any,
) -> Dict[str, Any]:
    """Run Steps 3b–4c: pipeline generators, seed data, pattern injection,
    audit/cache/permissions infrastructure.

    Returns a dict with keys:
      _pipeline_files_written, _inject_pipeline_router, _inject_realtime_router,
      _inject_websocket_router, _inject_stripe_router, _inject_marketplace_router,
      _inject_erp_approval_router
    """
    import ast as _ast

    # Step 3a: SSE realtime router
    _inject_realtime_router = False
    if realtime_features:
        try:
            sse_router_code = generate_sse_router_fn(realtime_features, project_name)
            (routers_dir / "realtime_router.py").write_text(sse_router_code)
            _inject_realtime_router = True
            logger.info("[p04a] SSE realtime_router.py written for features: %s", realtime_features)
        except Exception as _sse_exc:
            logger.warning("[p04a] SSE router generation failed (non-fatal): %s", _sse_exc)

    # Step 3b: Business process pipeline orchestrators
    _pipeline_files_written: list = []
    try:
        from aether_os.core.domain_knowledge.loader import load_pack as _load_pack
        from aether_os.phases.p04a_backend_codegen.pipeline_generator import generate_pipeline_code
        _pack = _load_pack(domain)
        if _pack and _pack.pipelines:
            _pipeline_files_written = generate_pipeline_code(_pack.pipelines, src_dir, domain)
            logger.info(
                "[p04a] generated %d pipeline files for domain=%s: %s",
                len(_pipeline_files_written), domain, _pipeline_files_written,
            )
    except Exception as exc:
        logger.warning("[p04a] pipeline generation failed (non-blocking): %s", exc)

    _inject_pipeline_router = (routers_dir / "pipeline_events.py").exists()

    # Step 4: Seed data
    if seed_code:
        logger.info("[p04a] IR fast-path: seed.py already generated (%d chars)", len(seed_code))
    else:
        template_path = Path(__file__).parent / "seed_templates" / f"{domain}.py"
        if template_path.exists():
            logger.info("[p04a] using domain seed template: %s", domain)
            seed_code = template_path.read_text()
            if f"async def seed_{domain}" in seed_code:
                seed_code += (
                    f"\n\nasync def seed_database():\n"
                    f"    from database import AsyncSessionLocal\n"
                    f"    async with AsyncSessionLocal() as db:\n"
                    f"        await seed_{domain}(db)\n"
                )
        if not seed_code:
            seed_code = fallback_seed_fn(project_name, entities, seed_vocabulary=seed_vocabulary, domain=domain)
            try:
                _ast.parse(seed_code)
            except SyntaxError as _syn:
                logger.warning("[p04a] SyntaxError in fallback seed.py: %s — emitting empty seed", _syn)
                seed_code = "async def seed_database():\n    return None\n"
            seed_code = fix_relative_imports_fn(seed_code)
            (src_dir / "seed.py").write_text(seed_code)
            logger.info("[p04a] seed.py %d chars (deterministic)", len(seed_code))

    # Step 4a: Pattern library injection
    _active_patterns = detect_patterns_fn(data, raw_input)
    _inject_websocket_router = "websocket" in _active_patterns
    _inject_stripe_router = "stripe" in _active_patterns
    _inject_marketplace_router = "marketplace" in _active_patterns
    _inject_erp_approval_router = "erp_approval" in _active_patterns
    inject_patterns_fn(_active_patterns, src_dir, output_dir)

    # Step 4b: Audit infrastructure
    try:
        generate_audit_fn(src_dir)
    except Exception as _audit_exc:
        logger.warning("[p04a] audit infrastructure generation failed (non-fatal): %s", _audit_exc)

    try:
        generate_cache_fn(src_dir)
    except Exception as _cache_exc:
        logger.warning("[p04a] cache service generation failed (non-fatal): %s", _cache_exc)

    # Step 4c: Permissions service
    try:
        _permission_model = data.get("permission_model", {})
        if _permission_model:
            generate_permissions_fn(src_dir, _permission_model)
        else:
            logger.debug("[p04a] no permission_model in context — skipping permissions service")
    except Exception as _perm_exc:
        logger.warning("[p04a] permissions service generation failed (non-fatal): %s", _perm_exc)

    return {
        "_pipeline_files_written": _pipeline_files_written,
        "_inject_pipeline_router": _inject_pipeline_router,
        "_inject_realtime_router": _inject_realtime_router,
        "_inject_websocket_router": _inject_websocket_router,
        "_inject_stripe_router": _inject_stripe_router,
        "_inject_marketplace_router": _inject_marketplace_router,
        "_inject_erp_approval_router": _inject_erp_approval_router,
    }


def run_validation_pass(
    *,
    src_dir: Path,
    phase_input: Any,
) -> Any:
    """Collect all generated .py files and run the backend validator.

    Records every error category into the global ErrorRegistry and stores
    validation warnings onto phase_input.input_data so downstream phases
    see them.  Returns the ValidationReport object.
    """
    from aether_os.phases.p04a_backend_codegen.validator import validate_generated_backend
    from aether_os.core.error_registry import ErrorCategory, get_registry

    _validation_files: Dict[str, str] = {}
    for _vfile in src_dir.rglob("*.py"):
        try:
            _rel = str(_vfile.relative_to(src_dir))
            _validation_files[_rel] = _vfile.read_text(encoding="utf-8")
        except Exception as _vread_exc:
            logger.warning("[p04a] validator: could not read %s: %s", _vfile, _vread_exc)

    _validation_report = validate_generated_backend(_validation_files)
    _error_registry = get_registry()

    _cat_str_to_enum = {e.value: e for e in ErrorCategory}
    for _cat_str in _validation_report.categories:
        _cat_enum = _cat_str_to_enum.get(_cat_str, ErrorCategory.UNKNOWN)
        _detail_msgs = (
            [m for m in _validation_report.errors if _cat_str in m]
            or [m for m in _validation_report.warnings if _cat_str in m]
        )
        _detail = _detail_msgs[0] if _detail_msgs else _cat_str
        _error_registry.record(_cat_enum, "p04a", _detail[:300])

    if not _validation_report.passed:
        _gen_warnings: List[str] = _validation_report.errors + _validation_report.warnings
        logger.warning(
            "[p04a] validation FAILED: %d error(s): %s",
            len(_validation_report.errors), _validation_report.errors,
        )
        if hasattr(phase_input, "input_data") and isinstance(phase_input.input_data, dict):
            phase_input.input_data.setdefault("generation_warnings", []).extend(_gen_warnings)
    elif _validation_report.warnings:
        logger.info(
            "[p04a] validation passed with %d warning(s): %s",
            len(_validation_report.warnings), _validation_report.warnings[:3],
        )

    # C6: run auto-learned validators (generated by repair_learning after prior repairs)
    try:
        from aether_os.core.repair_learning import load_validators as _load_validators
        _learned = _load_validators()
        if _learned:
            for _source_name, _source in _validation_files.items():
                for _lv in _learned:
                    _lv_issues = _lv.check(_source) if hasattr(_lv, "check") else []
                    if _lv_issues:
                        logger.warning("[p04a] learned validator flagged %s: %s", _source_name, _lv_issues[:3])
                        if hasattr(phase_input, "input_data") and isinstance(phase_input.input_data, dict):
                            phase_input.input_data.setdefault("generation_warnings", []).extend(_lv_issues)
    except Exception as _lv_exc:
        logger.debug("[p04a] learned validators unavailable (non-fatal): %s", _lv_exc)

    return _validation_report


def run_ir_fastpath(
    *,
    ir_path_str: str,
    src_dir: Path,
    routers_dir: Path,
    output_dir: Path,
    seed_vocabulary: Dict[str, Any],
    domain: str,
    project_name: str,
    multi_tenancy: bool,
    entities: List[Dict[str, Any]],
) -> Tuple[str, str, str, str, List[Dict[str, Any]]]:
    """Generate models, schemas, stats, seed, and CRUD from domain_ir.json.

    Returns (models_code, schemas_code, crud_code, seed_code, updated_entities).
    On any failure returns ("", "", "", "", entities) so the caller falls
    through to the deterministic fallback.
    """
    models_code = schemas_code = crud_code = seed_code = ""
    try:
        from aether_os.core.domain_ir import DomainIR as _DomainIR
        from aether_os.phases.p04a_backend_codegen.ir_generators import (
            ir_to_models as _ir_to_models,
            ir_to_schemas as _ir_to_schemas,
            generate_stats_router as _gen_stats,
            generate_seed_py as _gen_seed,
            generate_crud_py as _gen_crud,
        )
        _ir = _DomainIR.load(Path(ir_path_str))
        if not _ir.entities:
            return models_code, schemas_code, crud_code, seed_code, entities

        # Pass domain so money/PHI constraints flow into generated column types.
        models_code = _ir_to_models(_ir, domain=domain)
        schemas_code = _ir_to_schemas(_ir, domain=domain)
        stats_code = _gen_stats(_ir)
        seed_code = _gen_seed(
            _ir,
            seed_vocabulary=seed_vocabulary,
            domain=domain,
            project_name=project_name,
        )
        (src_dir / "models.py").write_text(models_code)
        (src_dir / "schemas.py").write_text(schemas_code)
        (routers_dir / "stats.py").write_text(stats_code)
        (src_dir / "seed.py").write_text(seed_code)

        import secrets as _sec_ir
        _secret = _sec_ir.token_hex(32)
        env_content = textwrap.dedent(f"""\
            DATABASE_URL=sqlite+aiosqlite:///./app.db
            SECRET_KEY={_secret}
            ACCESS_TOKEN_EXPIRE_MINUTES=60
            CORS_ORIGINS=http://localhost:3000,http://localhost:5173
        """)
        (src_dir / ".env").write_text(env_content)
        (src_dir / ".env.example").write_text(
            env_content.replace(_secret, "your-secret-key")
        )
        # Ensure .gitignore ignores .env
        gitignore = src_dir.parent / ".gitignore"
        if gitignore.exists() and ".env" not in gitignore.read_text():
            with open(gitignore, "a") as f:
                f.write("\n.env\n")

        # Update entities list from IR so downstream CRUD is accurate
        entities = [
            {
                "name": e.name,
                "table": e.table,
                "fields": [{"name": f.name, "type": f.type} for f in e.fields],
            }
            for e in _ir.entities
        ]

        # Build and persist workflow transition map
        _workflow_transitions = _build_workflow_transitions(_ir, domain)
        _write_workflow_transitions_json(_workflow_transitions, output_dir)

        # Generate CRUD with transition guards embedded in PATCH handlers
        crud_code = _gen_crud(
            _ir,
            workflow_transitions=_workflow_transitions or None,
            multi_tenancy=multi_tenancy,
        )

    except Exception as _ir_exc:
        logger.warning(
            "[p04a] IR fast-path failed (%s) — falling through to deterministic fallback",
            _ir_exc,
        )
        return "", "", "", "", entities

    return models_code, schemas_code, crud_code, seed_code, entities
