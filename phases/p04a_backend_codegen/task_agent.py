"""P04a Backend Codegen — template-based multi-file FastAPI backend generator.

Output structure:
  src/
  ├── __init__.py
  ├── main.py          (template — app factory, middleware, error handlers, lifespan)
  ├── database.py      (template — async SQLAlchemy engine + session factory)
  ├── auth.py          (template — JWT access+refresh tokens, bcrypt, OAuth2 deps)
  ├── config.py        (template — Pydantic Settings from env)
  ├── models.py        (LLM — SQLAlchemy ORM models for all domain entities + User)
  ├── schemas.py       (LLM — Pydantic v2 request/response schemas per entity)
  ├── seed.py          (LLM — realistic startup seed data, bcrypt-hashed passwords)
  └── routers/
      ├── __init__.py
      ├── auth.py      (template — /auth/login, /auth/register, /auth/refresh, /auth/me)
      └── crud.py      (LLM — paginated CRUD routers for all entities, exports all_routers)
"""
from __future__ import annotations
import ast
import asyncio
import json
import logging
import re
import secrets
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aether_os.phases.base import TaskResult
from aether_os.core.errors import PipelineBlockedError

# ── Sub-module imports ─────────────────────────────────────────────────────────
from aether_os.phases.p04a_backend_codegen.templates import (
    _DATABASE_PY,
    _AUTH_PY,
    _CONFIG_PY,
    _AUTH_ROUTER_PY,
    _ROUTERS_INIT_PY,
    _REQUIREMENTS_TXT,
    _DOCKERFILE,
    _ALEMBIC_INI,
    _ALEMBIC_ENV_PY,
    _ALEMBIC_SCRIPT_PY_MAKO,
    _SERVICES_INIT_PY,
    _build_main_py,
    _generate_makefile,
    _generate_backend_readme,
)
from aether_os.phases.p04a_backend_codegen.schema_builder import (
    _fallback_models,
    _fallback_schemas,
    _fix_common_issues,
)
from aether_os.phases.p04a_backend_codegen.crud_generator import (
    _llm_models_and_schemas,
    _llm_crud_routers,
    _llm_seed_data,
    _llm_service_layer,
    _fallback_crud_routers,
    _fallback_seed,
    _fallback_service_layer,
)
from aether_os.phases.p04a_backend_codegen.helpers import (
    _generate_audit_infrastructure,
    _generate_permissions_service,
    _smoke_test,
)

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

    # ── Step 1: Write fixed template files ────────────────────────────────────
    (src_dir / "__init__.py").write_text("")
    (src_dir / "database.py").write_text(_DATABASE_PY)
    (src_dir / "auth.py").write_text(_AUTH_PY)
    (src_dir / "config.py").write_text(_CONFIG_PY)
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
                seed_code = _gen_seed(_ir)
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
                crud_code = _gen_crud(_ir, workflow_transitions=_workflow_transitions or None)

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
    # The "single LLM call per phase" rule means p04a relies entirely on:
    #   1. domain_ir.json from p02b (IR fast-path, deterministic codegen) → preferred
    #   2. _fallback_* deterministic generators                          → if no IR
    # The previous chain of 3 LLM calls (models+schemas, crud, seed) introduced
    # 90s+ of latency and ~30% defect rate (syntax errors, missing imports,
    # wrong all_routers list). The IR + fallback path is faster and lossless.
    from aether_os.core.llm.client import get_llm_client
    llm = get_llm_client()  # retained for downstream code (smoke-repair, etc.)
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

        (src_dir / "models.py").write_text(models_code)
        (src_dir / "schemas.py").write_text(schemas_code)
        logger.info("[p04a] models.py %d chars (%d ORM classes), schemas.py %d chars",
                    len(models_code), len(_llm_classes), len(schemas_code))
    except Exception as exc:
        logger.warning("[p04a] LLM models/schemas failed (%s), using fallback", exc)
        models_code = _fallback_models(project_name, entities)
        schemas_code = _fallback_schemas(entities)
        (src_dir / "models.py").write_text(models_code)
        (src_dir / "schemas.py").write_text(schemas_code)
        generated_via = "templates+fallback"

    # ── Step 3: Deterministic CRUD routers ───────────────────────────────────
    if not crud_code:
        crud_code = _fallback_crud_routers(entities)
    try:
        compile(crud_code, "crud.py", "exec")
    except SyntaxError as _syn:
        logger.warning("[p04a] SyntaxError in crud.py: %s — using fallback", _syn)
        crud_code = _fallback_crud_routers(entities)
    # Ensure all_routers is always present — LLM sometimes omits it
    if "all_routers" not in crud_code:
        _router_vars = re.findall(r'^(\w+_router)\s*=\s*APIRouter', crud_code, re.MULTILINE)
        if _router_vars:
            crud_code = crud_code.rstrip() + f"\n\nall_routers = [{', '.join(_router_vars)}]\n"
            logger.info("[p04a] Auto-injected all_routers into crud.py: %s", _router_vars)
    (routers_dir / "crud.py").write_text(crud_code)
    logger.info("[p04a] routers/crud.py %d chars", len(crud_code))

    # ── Step 3b: Business process pipeline orchestrators (Gap 11) ────────────
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
            seed_code = _fallback_seed(project_name, entities)
            try:
                ast.parse(seed_code)
            except SyntaxError as _syn:
                logger.warning("[p04a] SyntaxError in fallback seed.py: %s — emitting empty seed", _syn)
                seed_code = "async def seed_database():\n    return None\n"
            (src_dir / "seed.py").write_text(seed_code)
            logger.info("[p04a] seed.py %d chars (deterministic)", len(seed_code))

    # ── Step 4b: Audit infrastructure ────────────────────────────────────────
    try:
        _generate_audit_infrastructure(src_dir)
    except Exception as _audit_exc:
        logger.warning("[p04a] audit infrastructure generation failed (non-fatal): %s", _audit_exc)

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
    # Inject AuditContextMiddleware into main.py
    main_py = main_py.replace(
        "app.include_router(auth_router, prefix=\"/api\")",
        (
            "try:\n"
            "    from services.audit_service import AuditContextMiddleware\n"
            "    app.add_middleware(AuditContextMiddleware)\n"
            "except Exception:\n"
            "    pass\n\n"
            "app.include_router(auth_router, prefix=\"/api\")"
        ),
    )
    # Inject pipeline_events router only when the file was actually written (non-blocking)
    if _inject_pipeline_router:
        _pipeline_router_snippet = (
            "\n# Pipeline event triggers (generated from domain BusinessProcessPipeline)\n"
            "try:\n"
            "    from routers.pipeline_events import router as _pipeline_events_router\n"
            "    app.include_router(_pipeline_events_router, prefix=\"/api\")\n"
            "except Exception:\n"
            "    pass\n"
        )
        # Insert before the /health endpoint so the order is logical
        main_py = main_py.replace(
            "@app.get(\"/health\"",
            _pipeline_router_snippet + "@app.get(\"/health\"",
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
    )
    # Write both .env (used by the running app) and .env.example (for documentation)
    (output_dir / ".env").write_text(_env_content)
    (output_dir / ".env.example").write_text(_env_content)
    # ── Makefile ──────────────────────────────────────────────────────────────
    (output_dir / "Makefile").write_text(_generate_makefile(project_name))
    (output_dir / "README.md").write_text(_generate_backend_readme(project_name, entities))

    # ── Step 6b: Alembic scaffold ─────────────────────────────────────────────
    alembic_dir = output_dir / "alembic"
    alembic_versions = alembic_dir / "versions"
    alembic_versions.mkdir(parents=True, exist_ok=True)
    (output_dir / "alembic.ini").write_text(_ALEMBIC_INI)
    (alembic_dir / "env.py").write_text(_ALEMBIC_ENV_PY)
    (alembic_dir / "script.py.mako").write_text(_ALEMBIC_SCRIPT_PY_MAKO)
    (alembic_dir / "README").write_text(
        "Generate a migration: alembic revision --autogenerate -m 'description'\n"
        "Apply migrations:    alembic upgrade head\n"
        "Rollback one step:   alembic downgrade -1\n"
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

    return TaskResult(
        output_path=str(output_dir),
        confidence=0.92 if generated_via == "templates+llm" else 0.7,
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
        },
        success=True,
        issues=smoke.get("errors", []) if not smoke.get("passed") else [],
    )
