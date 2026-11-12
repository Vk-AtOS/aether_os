"""P05 Frontend Task Agent — React 18 + Vite 5 + TypeScript + TanStack project generator."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.domain_ir import DomainIR
from aether_os.core.sandbox import phase_exec
from aether_os.core.sandbox.runner import SandboxUnavailable
from aether_os.orchestrator.events import ACTIVE_RUN_ID
from aether_os.phases.base import TaskResult
from aether_os.phases.p05_frontend.build_loop import run_build_loop
from aether_os.phases.p05_frontend.cloud_console_generator import (
    generate_cloud_console,
)
from aether_os.phases.p05_frontend.ir_generators import ir_to_p05_entities
from aether_os.phases.p05_frontend.llm_page_writer import compute_template_debt
from aether_os.phases.utils import memory_hint
from aether_os.phases.p05_frontend.prompts import (
    DOMAIN_FALLBACK_WIDGETS,
    DOMAIN_COMPONENT_DESC,
    DOMAIN_COLOR_HINTS,
)
from aether_os.phases.p05_frontend.scaffold import (
    detect_domain,
    read_architecture,
    extract_all_entities_from_models_py,
    normalise_entities,
    to_pascal_case,
    pluralise,
    resolve_entity_p67_fallback,
)
from aether_os.phases.p05_frontend.npm_runner import (
    get_npm_semaphore,
    pkg_hash,
    node_modules_fresh,
    stamp_node_modules,
    _NPM_SHARED_CACHE,
    run_npm_build,
)
from aether_os.phases.p05_frontend.code_writer import (
    generate_package_json,
    generate_eslint_config,
    generate_vite_config,
    generate_tsconfig,
    generate_tailwind_config,
    generate_postcss_config,
    generate_index_html,
    generate_nginx_conf,
    generate_dockerfile,
    generate_env_example,
    generate_headers_file,
    generate_index_css,
    generate_main_tsx,
    generate_auth_ts,
    generate_types,
    generate_api,
    generate_app,
    generate_admin_layout,
    generate_customer_layout,
    generate_customer_home,
    generate_layout,
    generate_data_table,
    generate_crud_modal,
    generate_toaster,
    generate_vitest_config,
    generate_test_setup,
    generate_login_test,
    generate_dashboard_test,
    generate_error_boundary,
    generate_not_found_page,
    generate_frontend_readme,
    generate_login_page,
    generate_dashboard,
    generate_storefront_home,
    generate_entity_page,
    generate_product_grid_page,
    generate_docker_compose,
    is_product_entity,
    generate_lib_utils, generate_domain_dashboard, generate_mobile_first_layout,
    generate_use_websocket_hook,
)
from aether_os.phases.p05_frontend.preview import (
    take_preview_screenshot,
    apply_gate2_revisions,
)
from aether_os.phases.p05_frontend.helpers import (
    _write_with_guard,
    _generate_file,
    _generate_domain_component,
    _derive_admin_features,
    _generate_customer_portal,
    _generate_landing_page,
    _generate_sse_hook,
    write_ui_components,
)
from aether_os.phases.p05_frontend.domain_pages import write_domain_pages
from aether_os.phases.p05_frontend.governor_integration import run_frontend_governor
from aether_os.phases.p05_frontend.domain_assembler import (
    detect_layout_mode, assemble_domain_pages,
    run_gate3_approval, run_gate2_preview,
    write_scaffold_and_components, generate_domain_widget,
)

logger = logging.getLogger(__name__)

# Backward-compatible aliases (used by tests and ir_generators)
_read_architecture = read_architecture
_generate_nginx_conf = generate_nginx_conf
_generate_storefront_home = generate_storefront_home

# Domain → UI theme mapping (module-level constant, shared by prompts.py)
_DOMAIN_THEME_MAP = {
    "healthcare": "healthcare", "fintech": "fintech", "ecommerce": "ecommerce",
    "marketplace": "marketplace", "education": "education", "fitness": "fitness",
    "gym_fitness": "gym_fitness", "real_estate": "real_estate",
    "hospitality": "hospitality", "restaurant": "restaurant", "food": "food",
    "logistics": "logistics", "iot": "iot", "hrm": "hrm", "crm": "crm",
    "analytics": "analytics", "saas": "saas",
}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    _phase_start = asyncio.get_event_loop().time()
    _PHASE_TIMEOUT = 1500.0  # 25 minutes — stop generating new files but still build what exists

    # Check build_profile — skip React generation for non-web frontend targets.
    # Mobile (react_native) and desktop (electron) generators live in future phases (Layer 2/4).
    _bp = data.get("build_profile") or {}

    # Cloud platform builds get a management console instead of a standard CRUD app.
    if _bp.get("build_type") == "cloud_platform":
        logger.info("p05: build_type=cloud_platform — routing to cloud_console_generator")
        try:
            _ir_path_str = data.get("domain_ir_path", "")
            _cc_entities: list = []
            if _ir_path_str:
                try:
                    _ir_data = json.loads(Path(_ir_path_str).read_text())
                    _cc_entities = _ir_data.get("entities", [])
                except Exception as _cc_exc:
                    logger.warning("p05: cloud console IR load failed: %s", _cc_exc)
            _cc_services = data.get("services") or []
            _cc_project_name = data.get("project_name", "Cloud Platform")
            await generate_cloud_console(_cc_entities, _cc_services, _cc_project_name, output_dir)
            return TaskResult(
                output_path=str(output_dir / "frontend"),
                confidence=0.9,
                metadata={"cloud_console": True, "entity_count": len(_cc_entities)},
                success=True,
            )
        except Exception as _cc_err:
            logger.warning("p05: cloud_console_generator failed, falling through to standard React: %s", _cc_err)

    _frontend_fw = _bp.get("frontend_framework", "react")
    if _frontend_fw == "none":
        logger.info("p05: build_profile.frontend_framework=none — skipping frontend generation")
        return TaskResult(
            output_path=str(output_dir),
            confidence=1.0,
            metadata={"skipped": True, "reason": "frontend_framework=none"},
            success=True,
        )
    if _frontend_fw not in ("react", ""):
        logger.info(
            "p05: build_profile.frontend_framework=%s — falling back to React (generator not yet implemented)",
            _frontend_fw,
        )

    # 1. Read architecture
    arch = read_architecture(data)
    project_name = data.get("project_name", arch.get("project_name", "Project Dashboard"))
    project_slug = re.sub(r"[^a-z0-9-]", "-", project_name.lower()).strip("-") or "project"
    route_map: Dict[str, str] = arch.get("api_route_map", {})

    # 2. Normalise entities — prefer Domain IR when available
    _ir_path_str = data.get("domain_ir_path", "")
    _domain_ir = None
    if _ir_path_str:
        _ir_p = Path(_ir_path_str)
        if _ir_p.exists():
            try:
                _domain_ir = DomainIR.load(_ir_p)
                if _domain_ir.entities:
                    entities = ir_to_p05_entities(_domain_ir)
                    logger.info(
                        "p05: IR fast-path — %d typed entities from domain_ir.json",
                        len(entities),
                    )
                else:
                    _domain_ir = None
            except Exception as _ir_exc:
                logger.warning("p05: domain_ir load failed (%s) — using arch fallback", _ir_exc)
                _domain_ir = None

    if _domain_ir is None:
        entities = normalise_entities(arch)
        # 2a. If we only got the generic 'items' fallback, try reading models.py directly.
        if len(entities) == 1 and entities[0]["table"] == "items":
            _models_entities = extract_all_entities_from_models_py(data)
            if _models_entities:
                logger.info(
                    "p05: replaced generic 'items' fallback with %d real entities from models.py",
                    len(_models_entities),
                )
                entities = _models_entities

        entities = resolve_entity_p67_fallback(data, entities)

    # Robust autonomous mode detection
    is_autonomous = (
        data.get("autonomous_mode") is True
        or data.get("decision_mode") == "autonomous"
        or os.environ.get("AUTONOMOUS_MODE", "").lower() == "true"
    )

    # 2b. Detect application domain
    domain = detect_domain(phase_input)
    logger.info("p05_frontend: detected domain=%s for project=%s (autonomous=%s)", domain, project_name, is_autonomous)

    design_brief = data.get("design_brief", {})

    mem = memory_hint(memory_ctx)

    # Extract designer spec settings
    designer_spec = data.get("designer_spec") or {}
    _design = designer_spec.get("design") or {}
    _dg = _design.get  # shorthand
    ui_theme: str      = _dg("ui_theme", "") or ""
    page_transition    = _dg("page_transition", "fade") or "fade"
    animation_speed    = _dg("animation_speed", "normal") or "normal"
    micro_interactions = bool(_dg("micro_interactions", True))
    scroll_reveal      = bool(_dg("scroll_reveal", True))
    loading_style      = _dg("loading_style", "shimmer") or "shimmer"
    hover_lift         = bool(_dg("hover_lift", True))
    primary_hex        = _dg("primary_hex", "") or ""
    secondary_hex      = _dg("secondary_hex", "") or ""
    background_hex     = _dg("background_hex", "") or ""
    surface_hex        = _dg("surface_hex", "") or ""
    font_pairing       = _dg("font_pairing", "") or ""
    border_radius      = _dg("border_radius", "") or ""
    density            = _dg("density", "") or ""
    if not ui_theme or ui_theme == "default":
        ui_theme = _DOMAIN_THEME_MAP.get((data.get("domain", "") or domain or "").lower(), "default")

    # ── Wire new accumulated_context fields ──────────────────────────────────
    user_personas: List[dict] = data.get("user_personas") or []
    has_customer_portal = data.get("has_customer_portal")
    has_landing_page: bool = bool(data.get("has_landing_page", False))
    app_brand: Dict[str, Any] = data.get("app_brand") or {}
    app_tagline: str = data.get("app_tagline", "")
    realtime_features: List[Any] = data.get("realtime_features") or []
    build_types: List[str] = data.get("build_types") or []
    _raw_lower = (data.get("raw_input") or "").lower()
    _has_websocket = "websocket" in build_types or "realtime" in build_types or any(
        x in _raw_lower for x in ["websocket", "real-time", "realtime", "live chat", "collaboration"]
    )

    # Detect layout mode — delegated to domain_assembler to reduce line count
    layout_mode = detect_layout_mode(
        designer_spec=designer_spec,
        design=_design,
        domain=domain,
        raw_input=data.get("raw_input", ""),
        has_customer_portal=has_customer_portal,
    )
    logger.info("p05_frontend: layout_mode=%s (has_customer_portal=%s)", layout_mode, has_customer_portal)

    # 3. Build frontend/ directory structure
    frontend_dir = output_dir / "frontend"
    src_dir = frontend_dir / "src"
    (src_dir / "lib").mkdir(parents=True, exist_ok=True)
    (src_dir / "types").mkdir(parents=True, exist_ok=True)
    (src_dir / "components").mkdir(parents=True, exist_ok=True)
    (src_dir / "components" / "ui").mkdir(parents=True, exist_ok=True)
    (src_dir / "pages").mkdir(parents=True, exist_ok=True)
    (src_dir / "hooks").mkdir(parents=True, exist_ok=True)

    # ── Phases 1–5: Scaffold, core logic, and layout components ──────────────
    # Delegated to domain_assembler.write_scaffold_and_components to keep
    # task_agent.py under 450 lines.
    write_scaffold_and_components(
        frontend_dir=frontend_dir, src_dir=src_dir,
        project_name=project_name, project_slug=project_slug,
        domain=domain, layout_mode=layout_mode, entities=entities,
        route_map=route_map, app_brand=app_brand, app_tagline=app_tagline,
        has_landing_page=has_landing_page, realtime_features=realtime_features,
        has_websocket=_has_websocket, ui_theme=ui_theme,
        page_transition=page_transition, animation_speed=animation_speed,
        micro_interactions=micro_interactions, scroll_reveal=scroll_reveal,
        loading_style=loading_style, hover_lift=hover_lift, data=data,
        generate_package_json_fn=generate_package_json,
        generate_eslint_config_fn=generate_eslint_config,
        generate_vite_config_fn=generate_vite_config,
        generate_tsconfig_fn=generate_tsconfig,
        generate_tailwind_config_fn=generate_tailwind_config,
        generate_postcss_config_fn=generate_postcss_config,
        generate_index_html_fn=generate_index_html,
        generate_nginx_conf_fn=generate_nginx_conf,
        generate_dockerfile_fn=generate_dockerfile,
        generate_env_example_fn=generate_env_example,
        generate_headers_file_fn=generate_headers_file,
        generate_index_css_fn=generate_index_css,
        generate_main_tsx_fn=generate_main_tsx,
        generate_auth_ts_fn=generate_auth_ts,
        generate_api_fn=generate_api,
        generate_lib_utils_fn=generate_lib_utils,
        generate_types_fn=generate_types,
        generate_app_fn=generate_app,
        generate_login_page_fn=generate_login_page,
        generate_not_found_page_fn=generate_not_found_page,
        generate_customer_home_fn=generate_customer_home,
        generate_landing_page_fn=_generate_landing_page,
        generate_sse_hook_fn=_generate_sse_hook,
        generate_use_websocket_hook_fn=generate_use_websocket_hook,
        generate_customer_layout_fn=generate_customer_layout,
        generate_admin_layout_fn=generate_admin_layout,
        generate_mobile_first_layout_fn=generate_mobile_first_layout,
        generate_data_table_fn=generate_data_table,
        generate_crud_modal_fn=generate_crud_modal,
        generate_toaster_fn=generate_toaster,
        generate_error_boundary_fn=generate_error_boundary,
        generate_frontend_readme_fn=generate_frontend_readme,
        write_ui_components_fn=write_ui_components,
        write_with_guard_fn=_write_with_guard,
    )

    # ── Phase 6: Entity CRUD Pages ──
    # Delegated to domain_assembler.assemble_domain_pages to keep task_agent
    # under 450 lines.
    _page_stats = await assemble_domain_pages(
        src_dir=src_dir,
        domain=domain,
        domain_ir=_domain_ir,
        entities=entities,
        build_types=build_types,
        layout_mode=layout_mode,
        route_map=route_map,
        project_name=project_name,
        data=data,
        output_dir=output_dir,
        phase_start=_phase_start,
        phase_timeout=_PHASE_TIMEOUT,
        write_with_guard_fn=_write_with_guard,
        generate_product_grid_fn=generate_product_grid_page,
        generate_entity_page_fn=generate_entity_page,
        generate_domain_dashboard_fn=generate_domain_dashboard,
        is_product_entity_fn=is_product_entity,
        to_pascal_case_fn=to_pascal_case,
        pluralise_fn=pluralise,
        run_frontend_governor_fn=run_frontend_governor,
        write_domain_pages_fn=write_domain_pages,
    )
    _llm_count = (_page_stats or {}).get("llm_count", 0)
    _template_count = (_page_stats or {}).get("template_count", 0)
    # ── Phase 7: Optional LLM Component (DomainWidget) ──
    # Delegated to domain_assembler.generate_domain_widget to reduce task_agent lines.
    domain_widget_generated = await generate_domain_widget(
        src_dir=src_dir, domain=domain, entities=entities,
        project_name=project_name, mem=mem,
        primary_hex=primary_hex, secondary_hex=secondary_hex,
        background_hex=background_hex, surface_hex=surface_hex,
        font_pairing=font_pairing, border_radius=border_radius,
        density=density, phase_start=_phase_start, phase_timeout=_PHASE_TIMEOUT,
        generate_domain_component_fn=_generate_domain_component,
        write_with_guard_fn=_write_with_guard,
        accumulated_context=data,
    )

    # ── Phase 8: Customer Portal (Home, About) ──
    if asyncio.get_event_loop().time() - _phase_start < _PHASE_TIMEOUT:
        logger.info("p05: generating customer portal for %s", domain)
        await _generate_customer_portal(
            domain, design_brief, route_map, src_dir / "pages",
            user_personas=user_personas,
            project_name=project_name,
            app_brand=app_brand,
            app_tagline=app_tagline,
        )
        # LLM-first portal home: overwrite template Home.tsx if LLM succeeds
        from aether_os.phases.p05_frontend.llm_page_writer import (
            write_portal_home_llm,
            get_design_tokens as _get_tokens,
        )
        _portal_home_llm = await write_portal_home_llm(
            domain=domain,
            project_name=project_name,
            raw_input=data.get("raw_input", ""),
            design_tokens=_get_tokens(domain),
        )
        if _portal_home_llm:
            (src_dir / "pages" / "customer" / "Home.tsx").write_text(_portal_home_llm)
            _llm_count += 1
            logger.info("p05: LLM portal home written for %s", project_name)
    else:
        logger.warning("p05: phase watchdog — skipping customer portal generation")

    # ── Phase 9: Tests ──
    tests_dir = src_dir / "__tests__"
    tests_dir.mkdir(parents=True, exist_ok=True)
    _write_with_guard(tests_dir / "setup.ts", generate_test_setup())
    _write_with_guard(tests_dir / "LoginPage.test.tsx", generate_login_test(project_name))
    _write_with_guard(tests_dir / "Dashboard.test.tsx", generate_dashboard_test())
    _write_with_guard(frontend_dir / "vitest.config.ts", generate_vitest_config())

    # Obtain run_id once for both Gate 3 and Gate 2
    run_id: Optional[str] = None
    try:
        run_id = ACTIVE_RUN_ID.get()
    except Exception as e:
        logger.debug("[p05] ACTIVE_RUN_ID.get() failed: %s", e)

    # ── Gate 3: Admin Requirements Approval ──
    # Delegated to domain_assembler.run_gate3_approval to reduce task_agent lines.
    admin_features = await run_gate3_approval(
        domain_ir=_domain_ir,
        data=data,
        is_autonomous=is_autonomous,
        derive_admin_features_fn=_derive_admin_features,
    )

    # 4. Finalise project structure
    project_dir = output_dir.parent
    _write_with_guard(project_dir / "docker-compose.yml", generate_docker_compose(project_dir))

    _canonical_frontend = project_dir / "frontend"
    if not _canonical_frontend.exists() and frontend_dir.exists():
        try:
            shutil.copytree(str(frontend_dir), str(_canonical_frontend), ignore=shutil.ignore_patterns("node_modules", ".git", "dist", "build"))
        except Exception as _copy_exc:
            logger.warning("p05: copytree to canonical frontend failed: %s", _copy_exc)

    # 5. Write metadata
    generated_files = ["frontend/package.json", "frontend/src/App.tsx", "frontend/src/pages/Dashboard.tsx"]
    # template_debt_pct: fraction of pages that fell back to static templates (0.0 = all LLM, 1.0 = all template)
    # denominator: entity pages + dashboard + customer portal (all LLM-authored files)
    _primary_llm = os.environ.get("PRIMARY_LLM", "ollama")
    # model_used: resolved provider string; degraded when not a frontier tier (anthropic/gemini)
    _model_used = _primary_llm if _primary_llm else "ollama"
    # bedrock counts as degraded — Claude on Bedrock blocked; Nova Pro is the fallback
    _degraded = _model_used not in ("anthropic", "gemini")
    meta = {
        "project_name": project_name, "project_slug": project_slug, "domain": domain,
        "entities": [e["table"] for e in entities], "used_llm": domain_widget_generated,
        "files_generated": generated_files,
        "template_debt_pct": compute_template_debt(_llm_count, _template_count),
        "model_used": _model_used,
        "degraded": _degraded,
    }
    (output_dir / "frontend_meta.json").write_text(json.dumps(meta, indent=2))

    # ── Step 6: Final Build (with compile-error feedback loop) ──
    # Runs before Gate-2 so the screenshot shows the compiled artifact.
    frontend_dir_final = project_dir / 'frontend'
    build_success = True
    tsc_errors: int = 0
    if os.environ.get("ENVIRONMENT") != "test":
        async with get_npm_semaphore():
            try:
                _hash = pkg_hash(frontend_dir_final)
                if not node_modules_fresh(frontend_dir_final, _hash):
                    # Install in the sandbox (install egress profile); build/tsc below have no network.
                    install_result = await phase_exec.run(["npm", "install"], cwd=frontend_dir_final,
                                                          timeout=300, network=True)
                    if install_result.returncode != 0:
                        logger.error("p05: npm install failed (exit %s)", install_result.returncode)
                        build_success = False
                    else:
                        stamp_node_modules(frontend_dir_final, _hash)
            except SandboxUnavailable:
                raise
            except Exception as exc:
                logger.error("p05: npm install raised: %s", exc)
                build_success = False

            if build_success:
                _loop_result = await run_build_loop(frontend_dir_final, max_rounds=3)
                build_success = _loop_result["success"]
                tsc_errors = _loop_result["tsc_errors"]
                logger.info(
                    "p05 build_loop: success=%s tsc_errors=%d rounds=%d",
                    build_success, tsc_errors, _loop_result["rounds"],
                )

    # ── Gate 2: Preview (screenshots the built artifact) ──
    # Delegated to domain_assembler.run_gate2_preview to reduce task_agent lines.
    await run_gate2_preview(
        run_id=run_id,
        frontend_dir=frontend_dir,
        output_dir=output_dir,
        domain=domain,
        project_name=project_name,
        data=data,
        is_autonomous=is_autonomous,
        take_screenshot_fn=take_preview_screenshot,
        apply_revisions_fn=apply_gate2_revisions,
    )

    # confidence: build_pass * 0.6 + (1 if tsc_errors==0 else 0) * 0.3 + (1 - template_debt_pct) * 0.1
    template_debt_pct: float = meta.get("template_debt_pct", 1.0)
    _confidence = build_success * 0.6 + (1 if tsc_errors == 0 else 0) * 0.3 + (1 - template_debt_pct) * 0.1
    _confidence = max(0.0, min(1.0, _confidence))
    return TaskResult(output_path=str(frontend_dir_final), confidence=_confidence, success=build_success, metadata=meta)
