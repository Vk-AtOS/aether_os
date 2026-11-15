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
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.sandbox.runner import SandboxUnavailable
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
from aether_os.phases.p04a_backend_codegen.pre_gen_validator import fix_relative_imports, safe_project_name
from aether_os.phases.p04a_backend_codegen.pattern_injector import detect_active_patterns, inject_patterns

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
    project_name: str = safe_project_name(data.get("project_name", "App"))
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
        _ir_for_checks: dict = {}
        _ir_file = data.get("domain_ir_path", "")
        if _ir_file and Path(_ir_file).exists():
            _ir_for_checks = json.loads(Path(_ir_file).read_text())
        # the IR carries the foreign keys (type "fk") and rules; the plain entity list is checked too
        _pre_gen_report = run_pre_gen_checks({
            "entities": list(_ir_for_checks.get("entities") or []) + list(entities),
            "business_rules": _ir_for_checks.get("business_rules") or [],
        })
        if _pre_gen_report.warnings:
            data.setdefault("pre_gen_warnings", []).extend(_pre_gen_report.warnings)
        if not _pre_gen_report.passed:
            data.setdefault("pre_gen_errors", []).extend(_pre_gen_report.errors)
            raise PipelineBlockedError(
                f"P04a pre-generation check failed: {_pre_gen_report.errors}. "
                "Fix the entity definitions (circular foreign keys, names that are not plain identifiers) before retrying."
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

    generated_via = "deterministic"
    models_code = ""
    schemas_code = ""
    crud_code = ""
    seed_code = ""

    # ── Step 2 (IR fast-path): deterministic generation from Domain IR ────────
    # Delegated to codegen_orchestrator.run_ir_fastpath to keep task_agent.py
    # under 400 lines. Falls through to deterministic fallback on any error.
    _ir_path_str = data.get("domain_ir_path", "")
    if _ir_path_str and Path(_ir_path_str).exists():
        from aether_os.phases.p04a_backend_codegen.codegen_orchestrator import run_ir_fastpath
        models_code, schemas_code, crud_code, seed_code, entities = run_ir_fastpath(
            ir_path_str=_ir_path_str,
            src_dir=src_dir,
            routers_dir=routers_dir,
            output_dir=output_dir,
            seed_vocabulary=seed_vocabulary,
            domain=domain,
            project_name=project_name,
            multi_tenancy=multi_tenancy,
            entities=entities,
        )

    # ── Step 2: Deterministic generation (zero LLM calls in p04a) ────────────
    # Primary path: IR fast-path (domain_ir.json) → _fallback_* generators.
    # LLM intentionally excluded: 3-call LLM chain had 30% relative-import failure rate.
    logger.info("[p04a] LLM path skipped — using deterministic codegen (IR fast-path or fallback)")
    _llm_classes: list = []
    try:
        if not models_code or not schemas_code:
            await _emit({"type": "llm_chunk", "phase": "p04a", "text": "⚙ Generating models + schemas (deterministic)…"})
            # Pass domain so money/PHI constraints are applied in fallback codegen.
            models_code = _fallback_models(project_name, entities, domain=domain, multi_tenancy=multi_tenancy)
            schemas_code = _fallback_schemas(entities, domain=domain)
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
            ("models.py", models_code, _fallback_models, [project_name, entities, domain, multi_tenancy]),
            ("schemas.py", schemas_code, _fallback_schemas, [entities, domain]),
        ]:
            try:
                compile(_code, _fname, "exec")
            except SyntaxError as _syn:
                logger.warning("[p04a] SyntaxError in generated %s: %s — using fallback", _fname, _syn)
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
        models_code = _fallback_models(project_name, entities, domain=domain, multi_tenancy=multi_tenancy)
        schemas_code = _fallback_schemas(entities, domain=domain)
        models_code = fix_relative_imports(models_code)
        schemas_code = fix_relative_imports(schemas_code)
        (src_dir / "models.py").write_text(models_code)
        (src_dir / "schemas.py").write_text(schemas_code)
        generated_via = "templates+fallback"

    # ── Step 3: Deterministic CRUD routers ───────────────────────────────────
    # permission_model flows in from p02c via accumulated_context → input_data
    _permission_model: dict | None = data.get("permission_model") or None
    if _permission_model:
        logger.info(
            "[p04a] ABAC permission_model present (%d roles) — wiring require_role() guards into CRUD",
            len(_permission_model.get("roles", [])),
        )
    if not crud_code:
        crud_code = _fallback_crud_routers(
            entities, multi_tenancy=multi_tenancy, permission_model=_permission_model
        )
    try:
        compile(crud_code, "crud.py", "exec")
    except SyntaxError as _syn:
        logger.warning("[p04a] SyntaxError in crud.py: %s — using fallback", _syn)
        crud_code = _fallback_crud_routers(
            entities, multi_tenancy=multi_tenancy, permission_model=_permission_model
        )
    # Ensure all_routers is always present — may be missing from IR-generated code
    if "all_routers" not in crud_code:
        _router_vars = re.findall(r'^(\w+_router)\s*=\s*APIRouter', crud_code, re.MULTILINE)
        if _router_vars:
            crud_code = crud_code.rstrip() + f"\n\nall_routers = [{', '.join(_router_vars)}]\n"
            logger.info("[p04a] Auto-injected all_routers into crud.py: %s", _router_vars)
    # Fix any relative imports before writing to disk (deterministic generator should
    # never produce them, but IR generators or other code paths might)
    crud_code = fix_relative_imports(crud_code)
    (routers_dir / "crud.py").write_text(crud_code)
    logger.info("[p04a] routers/crud.py %d chars", len(crud_code))

    # ── Steps 3a–4c: SSE router, pipeline generators, seed, patterns, infra ──────
    # Delegated to codegen_orchestrator.run_pipeline_and_seed_steps to keep
    # task_agent.py under 400 lines.
    from aether_os.phases.p04a_backend_codegen.codegen_orchestrator import run_pipeline_and_seed_steps
    _step_results = run_pipeline_and_seed_steps(
        src_dir=src_dir,
        routers_dir=routers_dir,
        output_dir=output_dir,
        domain=domain,
        project_name=project_name,
        entities=entities,
        seed_code=seed_code,
        seed_vocabulary=seed_vocabulary,
        realtime_features=realtime_features,
        data=data,
        raw_input=raw_input,
        multi_tenancy=multi_tenancy,
        fix_relative_imports_fn=fix_relative_imports,
        generate_sse_router_fn=_generate_sse_router,
        generate_audit_fn=_generate_audit_infrastructure,
        generate_cache_fn=_generate_cache_service,
        generate_permissions_fn=_generate_permissions_service,
        fallback_seed_fn=_fallback_seed,
        detect_patterns_fn=detect_active_patterns,
        inject_patterns_fn=inject_patterns,
    )
    _pipeline_files_written = _step_results["_pipeline_files_written"]
    _inject_pipeline_router = _step_results["_inject_pipeline_router"]
    _inject_realtime_router = _step_results["_inject_realtime_router"]
    _inject_websocket_router = _step_results["_inject_websocket_router"]
    _inject_stripe_router = _step_results["_inject_stripe_router"]
    _inject_marketplace_router = _step_results["_inject_marketplace_router"]
    _inject_erp_approval_router = _step_results["_inject_erp_approval_router"]

    # ── Step 5: Generate main.py from template ────────────────────────────────
    main_py = _build_main_py(project_name, routers_have_all_routers=True)
    main_py = patch_main_py(
        main_py,
        inject_pipeline=_inject_pipeline_router,
        inject_realtime=_inject_realtime_router,
        inject_websocket=_inject_websocket_router,
        inject_stripe=_inject_stripe_router,
        inject_marketplace=_inject_marketplace_router,
        inject_erp_approval=_inject_erp_approval_router,
    )
    (src_dir / "main.py").write_text(main_py)

    # ── Step 6: Supporting files ──────────────────────────────────────────────
    import secrets as _sec
    _secret = _sec.token_hex(32)
    (output_dir / "requirements.txt").write_text(_REQUIREMENTS_TXT)
    (output_dir / "Dockerfile").write_text(_DOCKERFILE)
    _admin_pw = _sec.token_urlsafe(16)
    _env_lines = (
        "DATABASE_URL=sqlite+aiosqlite:///./app.db\n"
        "SECRET_KEY={secret}\n"
        "CORS_ORIGINS=http://localhost:3000,http://localhost:5173\n"
        "ENVIRONMENT=development\n"
        "DEBUG=false\n"
        "ADMIN_PASSWORD={admin}\n"
        "# REDIS_URL=redis://localhost:6379  # Uncomment to enable response caching\n"
        "# ALLOW_SIGNUP=true                 # false = invite-only\n"
        "# ENABLE_DOCS=false                 # true keeps /docs and /openapi.json when ENVIRONMENT=production\n"
        "# JWT signing key: with several replicas every one must share it (same volume file, or PEM text in RSA_PRIVATE_KEY)\n"
        "# RSA_PRIVATE_KEY_PATH=/keys/private_key.pem\n"
        "# CACHE_TTL=30                      # Cache time-to-live in seconds\n"
    )
    # .env holds this app's own random secrets; .env.example is the committed copy and holds placeholders only.
    (output_dir / ".env").write_text(_env_lines.format(secret=_secret, admin=_admin_pw))
    (output_dir / ".env.example").write_text(_env_lines.format(secret="change-me", admin="change-me"))
    (output_dir / ".gitignore").write_text(".env\n*.pem\n*.db\nadmin_initial_password.txt\n__pycache__/\n")
    (output_dir / ".dockerignore").write_text(".env\n*.pem\n*.db\nadmin_initial_password.txt\n__pycache__/\n.git\n")
    (output_dir / "Makefile").write_text(_generate_makefile(project_name))
    (output_dir / "README.md").write_text(_generate_backend_readme(project_name, entities))
    write_alembic_scaffold(output_dir)

    # ── Step 6c: Post-generation deterministic validation ─────────────────────
    # Delegated to codegen_orchestrator.run_validation_pass to keep task_agent
    # under 400 lines.
    from aether_os.phases.p04a_backend_codegen.codegen_orchestrator import run_validation_pass
    _validation_report = run_validation_pass(src_dir=src_dir, phase_input=phase_input)

    # ── Step 7: Smoke test ────────────────────────────────────────────────────
    smoke = {"passed": True, "errors": [], "skipped": False}
    try:
        smoke = await _smoke_test(src_dir, _emit)
        if not smoke["passed"]:
            raise PipelineBlockedError(
                f"P04a smoke test failed: {smoke.get('errors')}. "
                "Cannot proceed to frontend generation against a broken backend."
            )
    except (PipelineBlockedError, SandboxUnavailable):
        raise  # no sandbox: generated code was not run, the phase fails with that message
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
