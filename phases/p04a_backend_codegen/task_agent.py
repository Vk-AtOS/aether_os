"""P04a Backend Codegen — deterministic multi-file FastAPI backend generator.

All structural files are generated deterministically (no LLM calls in this phase).
LLM is intentionally excluded to eliminate the 30% relative-import failure rate.

Output structure:
  src/
  ├── __init__.py
  ├── main.py          (template — app factory, middleware, error handlers, lifespan)
  ├── database.py      (template — async SQLAlchemy engine + session factory)
  ├── auth.py          (template — JWT access+refresh tokens, bcrypt, OAuth2 deps)
  ├── config.py        (template — Pydantic Settings from env)
  ├── models.py        (deterministic — IR fast-path or _fallback_models)
  ├── schemas.py       (deterministic — IR fast-path or _fallback_schemas)
  ├── seed.py          (deterministic — IR fast-path or _fallback_seed with unique enforcement)
  └── routers/
      ├── __init__.py
      ├── auth.py      (template — /auth/login, /auth/register, /auth/refresh, /auth/me)
      └── crud.py      (deterministic — _fallback_crud_routers, absolute imports guaranteed)
"""
from __future__ import annotations
import ast
import json
import logging
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.phases.base import TaskResult
from aether_os.core.errors import PipelineBlockedError

# ── Sub-module imports ─────────────────────────────────────────────────────────
from aether_os.phases.p04a_backend_codegen.templates import (
    _DATABASE_PY,
    _AUTH_PY,
    _CONFIG_PY,
    _AUTH_ROUTER_PY,
    _RATE_LIMITER_PY,
    _ROUTERS_INIT_PY,
    _REQUIREMENTS_TXT,
    _DOCKERFILE,
    _build_main_py,
    _generate_makefile,
    _generate_backend_readme,
    write_alembic_scaffold,
    patch_main_py,
)
from aether_os.phases.p04a_backend_codegen.schema_builder import (
    _fallback_models,
    _fallback_schemas,
)
from aether_os.phases.p04a_backend_codegen.crud_generator import (
    _fallback_crud_routers,
    _fallback_seed,
)
from aether_os.phases.p04a_backend_codegen.helpers import (
    _generate_audit_infrastructure,
    _generate_permissions_service,
    _generate_sse_router,
    _smoke_test,
)
from aether_os.phases.p04a_backend_codegen.helpers_cache import _generate_cache_service
from aether_os.phases.p04a_backend_codegen.validator import validate_generated_backend
from aether_os.phases.p04a_backend_codegen.pre_gen_validator import fix_relative_imports
from aether_os.phases.p04a_backend_codegen.pattern_injector import detect_active_patterns, inject_patterns
from aether_os.core.error_registry import ErrorCategory, get_registry

logger = logging.getLogger(__name__)


# ── Main entry point ───────────────────────────────────────────────────────────

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    src_dir = output_dir / "src"
    routers_dir = src_dir / "routers"
    routers_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    async def _noop_emit(_e): pass
    _emit = getattr(phase_input, "emit", _noop_emit)

    raw_input: str = data.get("raw_input", "") or data.get("requirements", "") or ""
    project_name: str = data.get("project_name", "App")
    domain: str = data.get("domain", "general")
    entities: list = data.get("entities", [])
    api_endpoints: list = data.get("api_endpoints", [])

    # ── Accumulated context fields wired from upstream phases ────────────────
    multi_tenancy: bool = bool(
        data.get("multi_tenancy")
        or (data.get("project_contract") or {}).get("multi_tenancy", False)
    )
    tenant_isolation_model: str = data.get("tenant_isolation_model", "org_id_filter")
    realtime_features: list = data.get("realtime_features") or []
    seed_vocabulary: dict = data.get("seed_vocabulary") or {}
    user_personas: list = data.get("user_personas") or []
    has_customer_portal: Optional[bool] = data.get("has_customer_portal")

    if multi_tenancy:
        logger.info("[p04a] multi-tenancy enabled (model=%s) — org_id will be injected into models/CRUD", tenant_isolation_model)
    if realtime_features:
        logger.info("[p04a] realtime features detected: %s — SSE router will be generated", realtime_features)
    if seed_vocabulary:
        logger.info("[p04a] seed_vocabulary provided (%d keys) — domain-aware seed data enabled", len(seed_vocabulary))

    from aether_os.phases.utils import memory_hint
    mem = memory_hint(memory_ctx)
    # Load architecture doc
    arch_doc: dict = {}
    arch_path = data.get("architecture_path", "") or data.get("json_path", "")
    if arch_path:
        try:
            arch_doc = json.loads(Path(arch_path).read_text())
            if not entities:
                entities = arch_doc.get("entities", [])
            if not api_endpoints:
                api_endpoints = arch_doc.get("api_endpoints", [])
        except Exception as exc:
            logger.warning("[p04a] could not load arch doc: %s", exc)

    # ── Pre-generation architecture checks (before ANY file is written) ────────
    # Catches circular FK refs, implicit unique fields, and reserved names early
    # so we fail fast before spending time on file writes or LLM calls.
    try:
        from aether_os.phases.p04a_backend_codegen.pre_gen_validator import run_pre_gen_checks
        _pre_gen_report = run_pre_gen_checks({"entities": entities})
        if _pre_gen_report.warnings:
            data.setdefault("pre_gen_warnings", []).extend(_pre_gen_report.warnings)
        if not _pre_gen_report.passed:
            data.setdefault("pre_gen_errors", []).extend(_pre_gen_report.errors)
            raise PipelineBlockedError(
                f"P04a pre-generation check failed: {_pre_gen_report.errors}. "
                "Fix circular foreign-key references in entity definitions before retrying."
            )
    except PipelineBlockedError:
        raise
    except Exception as _pgv_exc:
        logger.warning("[p04a] pre-gen validator import/run failed (non-fatal): %s", _pgv_exc)

    # ── Step 1: Write fixed template files ────────────────────────────────────
    (src_dir / "__init__.py").write_text("")
    (src_dir / "database.py").write_text(_DATABASE_PY)
    (src_dir / "auth.py").write_text(_AUTH_PY)
    (src_dir / "config.py").write_text(_CONFIG_PY)
    (src_dir / "rate_limiter.py").write_text(_RATE_LIMITER_PY)
    (routers_dir / "__init__.py").write_text(_ROUTERS_INIT_PY)
    (routers_dir / "auth.py").write_text(_AUTH_ROUTER_PY)

    generated_via = "templates+llm"
    models_code = ""
    schemas_code = ""
    crud_code = ""
    seed_code = ""

    # ── Step 2 (IR fast-path): deterministic generation from Domain IR ────────
    # If p02b produced a domain_ir.json, skip the LLM for structural files.
    # Seed data still uses LLM (it needs invention, not structure).
    _ir_path_str = data.get("domain_ir_path", "")
    if _ir_path_str and Path(_ir_path_str).exists():
        try:
            from aether_os.core.domain_ir import DomainIR as _DomainIR
            from aether_os.phases.p04a_backend_codegen.ir_generators import (
                ir_to_models as _ir_to_models,
                ir_to_schemas as _ir_to_schemas,
                generate_stats_router as _gen_stats,
                generate_seed_py as _gen_seed,
                generate_crud_py as _gen_crud,
            )
            _ir = _DomainIR.load(Path(_ir_path_str))
            if _ir.entities:
                models_code = _ir_to_models(_ir)
                schemas_code = _ir_to_schemas(_ir)
                stats_code = _gen_stats(_ir)
                seed_code = _gen_seed(_ir, seed_vocabulary=seed_vocabulary, domain=domain, project_name=project_name)
                (src_dir / "models.py").write_text(models_code)
                (src_dir / "schemas.py").write_text(schemas_code)
                (routers_dir / "stats.py").write_text(stats_code)
                (src_dir / "seed.py").write_text(seed_code)
                import secrets as _sec_ir
                env_content = textwrap.dedent(f"""\
                    DATABASE_URL=sqlite+aiosqlite:///./app.db
                    SECRET_KEY={_sec_ir.token_hex(32)}
                    ACCESS_TOKEN_EXPIRE_MINUTES=60
                    CORS_ORIGINS=http://localhost:3000,http://localhost:5173
                """)
                (src_dir / ".env").write_text(env_content)
                (src_dir / ".env.example").write_text(env_content.replace(_sec_ir.token_hex(32), "your-secret-key"))
                # Ensure .gitignore ignores .env
                gitignore = src_dir.parent / ".gitignore"
                if gitignore.exists() and ".env" not in gitignore.read_text():
                    with open(gitignore, "a") as f:
                        f.write("\n.env\n")
                # Update entities list from IR so LLM CRUD is accurate
                entities = [{"name": e.name, "table": e.table,
                             "fields": [{"name": f.name, "type": f.type} for f in e.fields]}
                            for e in _ir.entities]

                # ── Build workflow transition map for PATCH guard injection ───
                # Priority: domain knowledge pack (explicit state machine) →
                #           IR workflow steps (linear chain derived from step order).
                _workflow_transitions: dict = {}
                try:
                    # Circular import guard: loader is always safe to import here
                    from aether_os.core.domain_knowledge.loader import load_pack as _load_pack
                    _pack = _load_pack(domain)
                    if _pack:
                        for _wf in _pack.workflows:
                            if _wf.transitions:
                                _workflow_transitions[_wf.entity] = _wf.transitions
                except Exception as _wf_exc:
                    logger.warning("[p04a] could not load domain pack workflows: %s", _wf_exc)

                # Derive linear chains from IR workflow steps for entities not
                # already covered by the domain pack (step[i] → [step[i+1]]).
                for _ir_wf in _ir.workflows:
                    if _ir_wf.entity and _ir_wf.entity not in _workflow_transitions:
                        _steps = [s.name for s in _ir_wf.steps]
                        if len(_steps) >= 2:
                            _trans: dict = {}
                            for _i, _step in enumerate(_steps[:-1]):
                                _trans[_step] = [_steps[_i + 1]]
                            _trans[_steps[-1]] = []  # terminal state
                            _workflow_transitions[_ir_wf.entity] = _trans

                # Generate CRUD with transition guards embedded in PATCH handlers
                crud_code = _gen_crud(_ir, workflow_transitions=_workflow_transitions or None, multi_tenancy=multi_tenancy)

                # Write workflow_transitions.json into the generated project scripts/
                if _workflow_transitions:
                    import datetime as _dt
                    _scripts_dir = output_dir / "scripts"
                    _scripts_dir.mkdir(parents=True, exist_ok=True)
                    _wf_json: dict = {
                        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                        "entities": {},
                    }
                    for _ent_name, _trans_map in _workflow_transitions.items():
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
                        len(_workflow_transitions),
                    )

        except Exception as _ir_exc:
            logger.warning("[p04a] IR fast-path failed (%s) — falling through to LLM", _ir_exc)
            models_code = ""
            schemas_code = ""
            crud_code = ""
            seed_code = ""

    # ── Step 2: Deterministic generation (zero LLM calls in p04a) ────────────
    # Primary path: IR fast-path (domain_ir.json) → _fallback_* generators.
    # LLM intentionally excluded: 3-call LLM chain had 30% relative-import failure rate.
    logger.info("[p04a] LLM path skipped — using deterministic codegen (IR fast-path or fallback)")
    _llm_classes: list = []
    try:
        if not models_code or not schemas_code:
            await _emit({"type": "llm_chunk", "phase": "p04a", "text": "⚙ Generating models + schemas (deterministic)…"})
            models_code = _fallback_models(project_name, entities)
            schemas_code = _fallback_schemas(entities)
            generated_via = "deterministic_fallback"

            _llm_classes = re.findall(r'^class \w+\(Base\)', models_code, re.MULTILINE)
        else:
            _llm_classes = re.findall(r'^class \w+\(Base\)', models_code, re.MULTILINE)
            logger.info("[p04a] IR fast-path: using deterministic models/schemas (%d classes)", len(_llm_classes))

        # P26: syntax validation before writing to disk
        # Use compile() not ast.parse() — compile() catches duplicate keyword
        # arguments (e.g. Column(default=True, ..., default=False)) which
        # ast.parse() silently accepts on Python 3.10.
        for _fname, _code, _fallback_fn, _fallback_args in [
            ("models.py", models_code, _fallback_models, [project_name, entities]),
            ("schemas.py", schemas_code, _fallback_schemas, [entities]),
        ]:
            try:
                compile(_code, _fname, "exec")
            except SyntaxError as _syn:
                logger.warning("[p04a] SyntaxError in LLM-generated %s: %s — using fallback", _fname, _syn)
                if _fname == "models.py":
                    models_code = _fallback_fn(*_fallback_args)
                else:
                    schemas_code = _fallback_fn(*_fallback_args)

        # Fix any residual relative imports before writing to disk
        models_code = fix_relative_imports(models_code)
        schemas_code = fix_relative_imports(schemas_code)
        (src_dir / "models.py").write_text(models_code)
        (src_dir / "schemas.py").write_text(schemas_code)
        logger.info("[p04a] models.py %d chars (%d ORM classes), schemas.py %d chars",
                    len(models_code), len(_llm_classes), len(schemas_code))
    except Exception as exc:
        logger.warning("[p04a] models/schemas generation failed (%s), using fallback", exc)
        models_code = _fallback_models(project_name, entities)
        schemas_code = _fallback_schemas(entities)
        models_code = fix_relative_imports(models_code)
        schemas_code = fix_relative_imports(schemas_code)
        (src_dir / "models.py").write_text(models_code)
        (src_dir / "schemas.py").write_text(schemas_code)
        generated_via = "templates+fallback"

    # ── Step 3: Deterministic CRUD routers ───────────────────────────────────
    if not crud_code:
        crud_code = _fallback_crud_routers(entities, multi_tenancy=multi_tenancy)
    try:
        compile(crud_code, "crud.py", "exec")
    except SyntaxError as _syn:
        logger.warning("[p04a] SyntaxError in crud.py: %s — using fallback", _syn)
        crud_code = _fallback_crud_routers(entities, multi_tenancy=multi_tenancy)
    # Ensure all_routers is always present — LLM sometimes omits it
    if "all_routers" not in crud_code:
        _router_vars = re.findall(r'^(\w+_router)\s*=\s*APIRouter', crud_code, re.MULTILINE)
        if _router_vars:
            crud_code = crud_code.rstrip() + f"\n\nall_routers = [{', '.join(_router_vars)}]\n"
            logger.info("[p04a] Auto-injected all_routers into crud.py: %s", _router_vars)
    # Fix any relative imports before writing to disk (deterministic generator should
    # never produce them, but IR generators or future LLM fallbacks might)
    crud_code = fix_relative_imports(crud_code)
    (routers_dir / "crud.py").write_text(crud_code)
    logger.info("[p04a] routers/crud.py %d chars", len(crud_code))

    # ── Step 3a: SSE realtime router (generated when spec declares realtime_features) ──
    _inject_realtime_router = False
    if realtime_features:
        try:
            sse_router_code = _generate_sse_router(realtime_features, project_name)
            (routers_dir / "realtime_router.py").write_text(sse_router_code)
            _inject_realtime_router = True
            logger.info("[p04a] SSE realtime_router.py written for features: %s", realtime_features)
        except Exception as _sse_exc:
            logger.warning("[p04a] SSE router generation failed (non-fatal): %s", _sse_exc)

    # ── Step 3b: Business process pipeline orchestrators ─────────────────────
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

    # Inject pipeline_events router into main.py when the router was generated
    _pipeline_events_path = routers_dir / "pipeline_events.py"
    if _pipeline_events_path.exists():
        # main.py hasn't been written yet at this step — flag for later injection
        _inject_pipeline_router = True
    else:
        _inject_pipeline_router = False

    # ── Step 4: Seed data — Template, IR-generated, or LLM ──────────────────
    if seed_code:
        # IR fast-path already wrote seed.py; just log it
        logger.info("[p04a] IR fast-path: seed.py already generated (%d chars)", len(seed_code))
    else:
        # Try domain-specific template first
        template_path = Path(__file__).parent / "seed_templates" / f"{domain}.py"
        if template_path.exists():
            logger.info("[p04a] using domain seed template: %s", domain)
            seed_code = template_path.read_text()
            # Wrap template into a full seed.py with imports and seed_database wrapper
            # (assuming templates provide the seed_{domain} function)
            if f"async def seed_{domain}" in seed_code:
                seed_code += f"\n\nasync def seed_database():\n    from database import AsyncSessionLocal\n    async with AsyncSessionLocal() as db:\n        await seed_{domain}(db)\n"

        if not seed_code:
            # Deterministic fallback — no LLM call (single-call-per-phase rule)
            seed_code = _fallback_seed(project_name, entities, seed_vocabulary=seed_vocabulary, domain=domain)
            try:
                ast.parse(seed_code)
            except SyntaxError as _syn:
                logger.warning("[p04a] SyntaxError in fallback seed.py: %s — emitting empty seed", _syn)
                seed_code = "async def seed_database():\n    return None\n"
            seed_code = fix_relative_imports(seed_code)
            (src_dir / "seed.py").write_text(seed_code)
            logger.info("[p04a] seed.py %d chars (deterministic)", len(seed_code))

    # ── Step 4a: Pattern library injection ───────────────────────────────────
    _active_patterns = detect_active_patterns(data, raw_input)
    _inject_websocket_router = "websocket" in _active_patterns
    _inject_stripe_router = "stripe" in _active_patterns
    _inject_marketplace_router = "marketplace" in _active_patterns
    inject_patterns(_active_patterns, src_dir, output_dir)

    # ── Step 4b: Audit infrastructure ────────────────────────────────────────
    try:
        _generate_audit_infrastructure(src_dir)
    except Exception as _audit_exc:
        logger.warning("[p04a] audit infrastructure generation failed (non-fatal): %s", _audit_exc)

    try:  # Step 4b2: Redis cache service
        _generate_cache_service(src_dir)
    except Exception as _cache_exc:
        logger.warning("[p04a] cache service generation failed (non-fatal): %s", _cache_exc)

    # ── Step 4c: Permissions service (from p02c permission model) ─────────────
    try:
        _permission_model = data.get("permission_model", {})
        if _permission_model:
            _generate_permissions_service(src_dir, _permission_model)
        else:
            logger.debug("[p04a] no permission_model in context — skipping permissions service")
    except Exception as _perm_exc:
        logger.warning("[p04a] permissions service generation failed (non-fatal): %s", _perm_exc)

    # ── Step 5: Generate main.py from template ────────────────────────────────
    main_py = _build_main_py(project_name, routers_have_all_routers=True)
    main_py = patch_main_py(
        main_py,
        inject_pipeline=_inject_pipeline_router,
        inject_realtime=_inject_realtime_router,
        inject_websocket=_inject_websocket_router,
        inject_stripe=_inject_stripe_router,
        inject_marketplace=_inject_marketplace_router,
    )
    (src_dir / "main.py").write_text(main_py)

    # ── Step 6: Supporting files ──────────────────────────────────────────────
    import secrets as _sec
    _secret = _sec.token_hex(32)
    (output_dir / "requirements.txt").write_text(_REQUIREMENTS_TXT)
    (output_dir / "Dockerfile").write_text(_DOCKERFILE)
    _env_content = (
        f"DATABASE_URL=sqlite+aiosqlite:///./app.db\n"
        f"SECRET_KEY={_secret}\n"
        f"CORS_ORIGINS=http://localhost:3000,http://localhost:5173\n"
        f"ENVIRONMENT=development\n"
        f"DEBUG=false\n"
        f"ADMIN_PASSWORD=Admin1234!\n"
        f"# REDIS_URL=redis://localhost:6379  # Uncomment to enable response caching\n"
        f"# CACHE_TTL=30                      # Cache time-to-live in seconds\n"
    )
    # Write both .env (used by the running app) and .env.example (for documentation)
    (output_dir / ".env").write_text(_env_content)
    (output_dir / ".env.example").write_text(_env_content)
    (output_dir / "Makefile").write_text(_generate_makefile(project_name))
    (output_dir / "README.md").write_text(_generate_backend_readme(project_name, entities))
    write_alembic_scaffold(output_dir)

    # ── Step 6c: Post-generation deterministic validation ─────────────────────
    # Collect all generated source files into a flat dict for the validator.
    # Keys are relative paths within src/ (e.g. "models.py", "routers/crud.py").
    _validation_files: Dict[str, str] = {}
    for _vfile in src_dir.rglob("*.py"):
        try:
            _rel = str(_vfile.relative_to(src_dir))
            _validation_files[_rel] = _vfile.read_text(encoding="utf-8")
        except Exception as _vread_exc:
            logger.warning("[p04a] validator: could not read %s: %s", _vfile, _vread_exc)

    _validation_report = validate_generated_backend(_validation_files)
    _error_registry = get_registry()

    # Record every category seen in this run into the error registry
    _cat_str_to_enum = {e.value: e for e in ErrorCategory}
    for _cat_str in _validation_report.categories:
        _cat_enum = _cat_str_to_enum.get(_cat_str, ErrorCategory.UNKNOWN)
        # Grab first matching detail message for the registry entry
        _detail_msgs = (
            [m for m in _validation_report.errors if _cat_str in m]
            or [m for m in _validation_report.warnings if _cat_str in m]
        )
        _detail = _detail_msgs[0] if _detail_msgs else _cat_str
        _error_registry.record(_cat_enum, "p04a", _detail[:300])

    if not _validation_report.passed:
        # Hard errors (AST parse failure or missing all_routers) — log and record
        # in accumulated_context so downstream phases and the UI can surface them.
        _gen_warnings: List[str] = _validation_report.errors + _validation_report.warnings
        logger.warning(
            "[p04a] validation FAILED: %d error(s): %s",
            len(_validation_report.errors), _validation_report.errors,
        )
        # Store into phase_input so downstream phases see the warnings
        if hasattr(phase_input, "input_data") and isinstance(phase_input.input_data, dict):
            phase_input.input_data.setdefault("generation_warnings", []).extend(_gen_warnings)
    elif _validation_report.warnings:
        logger.info(
            "[p04a] validation passed with %d warning(s): %s",
            len(_validation_report.warnings), _validation_report.warnings[:3],
        )

    # ── Step 7: Smoke test ────────────────────────────────────────────────────
    smoke = {"passed": True, "errors": [], "skipped": False}
    try:
        smoke = await _smoke_test(src_dir, _emit)
        if not smoke["passed"]:
            raise PipelineBlockedError(
                f"P04a smoke test failed: {smoke.get('errors')}. "
                "Cannot proceed to frontend generation against a broken backend."
            )
    except PipelineBlockedError:
        raise
    except Exception as exc:
        logger.debug("[p04a] smoke test error (non-fatal): %s", exc)

    code_size = sum(f.stat().st_size for f in src_dir.rglob("*.py") if f.exists())
    logger.info("[p04a] backend complete: %d bytes total, %s", code_size, generated_via)

    # Confidence tiers: IR fast-path > deterministic_fallback > templates+fallback
    if generated_via == "deterministic_fallback":
        _confidence = 0.82
        _confidence_reason = "Deterministic fallback generator — absolute imports guaranteed, no entity-specific fields"
    elif generated_via == "templates+fallback":
        _confidence = 0.7
        _confidence_reason = "Template + fallback: generation exception caught, minimal entity output"
    else:
        _confidence = 0.9
        _confidence_reason = f"Generated via {generated_via} — IR-driven, fully deterministic"
    if smoke.get("passed"):
        _confidence = min(1.0, _confidence + 0.05)
        _confidence_reason += "; smoke test passed"
    elif not smoke.get("skipped"):
        _confidence = max(0.0, _confidence - 0.2)
        _confidence_reason += "; smoke test failed"
    if not _validation_report.passed:
        _confidence = max(0.0, _confidence - 0.1)
        _confidence_reason += f"; validation errors: {len(_validation_report.errors)}"

    return TaskResult(
        output_path=str(output_dir),
        confidence=_confidence,
        confidence_reason=_confidence_reason,
        metadata={
            "backend_src_dir": str(src_dir),
            "main_py": str(src_dir / "main.py"),
            "models_py": str(src_dir / "models.py"),
            "schemas_py": str(src_dir / "schemas.py"),
            "seed_py": str(src_dir / "seed.py"),
            "crud_router": str(routers_dir / "crud.py"),
            "alembic_ini": str(output_dir / "alembic.ini"),
            "generated_via": generated_via,
            "code_size_bytes": code_size,
            "entities_count": len(entities),
            "pipeline_files": _pipeline_files_written,
            "smoke_test": smoke,
            "project_name": project_name,
            "multi_tenancy": multi_tenancy,
            "realtime_features": realtime_features,
            "realtime_router_py": str(routers_dir / "realtime_router.py") if _inject_realtime_router else None,
            "user_personas_count": len(user_personas),
            "has_customer_portal": has_customer_portal,
            "validation_passed": _validation_report.passed,
            "validation_errors": _validation_report.errors,
            "validation_warnings": _validation_report.warnings[:10],
        },
        success=True,
        issues=smoke.get("errors", []) if not smoke.get("passed") else [],
    )
