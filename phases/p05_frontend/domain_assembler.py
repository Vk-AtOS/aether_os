"""
P05 Domain Assembler — Layout Mode Detection + Entity Page Assembly
Extracted from task_agent.py to keep it under 450 lines.

Functions:
  detect_layout_mode()   — resolves admin / dual / storefront from spec + domain
  assemble_domain_pages() — Phase 6: entity CRUD pages + domain-specific pages
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.domain_ir import AetherType
from aether_os.phases.p05_frontend.llm_page_writer import (
    write_entity_page_llm,
    write_dashboard_llm,
    get_design_tokens,
)
from aether_os.phases.p05_frontend.page_concurrency import page_semaphore
from aether_os.phases.p05_frontend.code_writer import (
    _generate_pagination, _generate_role_guard, _generate_skeleton,
)
from aether_os.phases.p05_frontend.approval_gates import run_gate2_preview, run_gate3_approval  # noqa: F401

logger = logging.getLogger(__name__)

# Domains that default to dual-portal (admin + customer views)
_DUAL_PORTAL_DOMAINS = frozenset({
    "ecommerce", "marketplace", "library", "healthcare",
    "hospitality", "education", "events", "real_estate",
    "fitness", "food", "saas", "gym_fitness", "sports",
    "restaurant",
})

# Domains that are internal-only (no customer-facing portal)
_INTERNAL_ONLY_DOMAINS = frozenset({
    "crm", "hrm", "analytics", "fintech", "iot",
    "security", "logistics",
})


def write_scaffold_and_components(
    *,
    frontend_dir: Path,
    src_dir: Path,
    project_name: str,
    project_slug: str,
    domain: str,
    layout_mode: str,
    entities: List[Dict[str, Any]],
    route_map: Dict[str, str],
    app_brand: Dict[str, Any],
    app_tagline: str,
    has_landing_page: bool,
    realtime_features: List[Any],
    has_websocket: bool,
    ui_theme: str,
    page_transition: str,
    animation_speed: str,
    micro_interactions: bool,
    scroll_reveal: bool,
    loading_style: str,
    hover_lift: bool,
    data: Dict[str, Any],
    # all generator callables — passed explicitly to avoid circular imports
    generate_package_json_fn: Any,
    generate_eslint_config_fn: Any,
    generate_vite_config_fn: Any,
    generate_tsconfig_fn: Any,
    generate_tailwind_config_fn: Any,
    generate_postcss_config_fn: Any,
    generate_index_html_fn: Any,
    generate_nginx_conf_fn: Any,
    generate_dockerfile_fn: Any,
    generate_env_example_fn: Any,
    generate_headers_file_fn: Any,
    generate_index_css_fn: Any,
    generate_main_tsx_fn: Any,
    generate_auth_ts_fn: Any,
    generate_api_fn: Any,
    generate_lib_utils_fn: Any,
    generate_types_fn: Any,
    generate_app_fn: Any,
    generate_login_page_fn: Any,
    generate_not_found_page_fn: Any,
    generate_customer_home_fn: Any,
    generate_landing_page_fn: Any,
    generate_sse_hook_fn: Any,
    generate_use_websocket_hook_fn: Any,
    generate_customer_layout_fn: Any,
    generate_admin_layout_fn: Any,
    generate_mobile_first_layout_fn: Any,
    generate_data_table_fn: Any,
    generate_crud_modal_fn: Any,
    generate_toaster_fn: Any,
    generate_error_boundary_fn: Any,
    generate_frontend_readme_fn: Any,
    write_ui_components_fn: Any,
    write_with_guard_fn: Any,
) -> List[str]:
    """Write Phases 1–5: scaffold files, core logic, and layout components.

    Returns the user-facing surfaces (router shell, login, layouts, ...) it wrote from templates,
    relative to src/. Shared building blocks (DataTable, ui/*) are a component library, not listed.

    Extracted to keep task_agent.py under 450 lines.  All generator functions
    are passed in as callables to avoid circular imports between this module
    and code_writer.py.
    """
    # Phase 1: Static scaffold files
    logger.info("p05: Writing static scaffold files...")
    write_with_guard_fn(frontend_dir / "package.json", generate_package_json_fn(project_slug))
    write_with_guard_fn(frontend_dir / "vite.config.ts", generate_vite_config_fn())
    write_with_guard_fn(frontend_dir / "tsconfig.json", generate_tsconfig_fn())
    write_with_guard_fn(frontend_dir / "tailwind.config.js", generate_tailwind_config_fn(ui_theme))
    write_with_guard_fn(frontend_dir / "postcss.config.js", generate_postcss_config_fn())
    write_with_guard_fn(frontend_dir / "index.html", generate_index_html_fn(project_name, domain=domain))
    write_with_guard_fn(frontend_dir / "nginx.conf", generate_nginx_conf_fn(data))
    write_with_guard_fn(frontend_dir / "Dockerfile", generate_dockerfile_fn())
    write_with_guard_fn(frontend_dir / ".env.example", generate_env_example_fn())
    write_with_guard_fn(frontend_dir / "public" / "_headers", generate_headers_file_fn())
    write_with_guard_fn(frontend_dir / ".eslintrc.cjs", generate_eslint_config_fn())
    write_with_guard_fn(frontend_dir / "README.md", generate_frontend_readme_fn(project_name))
    write_with_guard_fn(src_dir / "index.css", generate_index_css_fn(
        ui_theme=ui_theme,
        page_transition=page_transition,
        animation_speed=animation_speed,
        micro_interactions=micro_interactions,
        scroll_reveal=scroll_reveal,
        loading_style=loading_style,
        hover_lift=hover_lift,
    ))
    write_with_guard_fn(src_dir / "main.tsx", generate_main_tsx_fn())

    # Phase 2: Core logic
    write_with_guard_fn(src_dir / "lib" / "auth.ts", generate_auth_ts_fn())
    write_with_guard_fn(src_dir / "lib" / "api.ts", generate_api_fn(entities, route_map))
    write_with_guard_fn(src_dir / "lib" / "utils.ts", generate_lib_utils_fn())
    write_with_guard_fn(src_dir / "types" / "index.ts", generate_types_fn(entities))

    # Phase 2b: shadcn/ui-compatible component library
    write_ui_components_fn(src_dir)

    # Phase 3: App.tsx skeleton
    logger.info("p05: Writing App.tsx skeleton...")
    write_with_guard_fn(src_dir / "App.tsx", generate_app_fn(entities, dual_portal=(layout_mode == "dual")))
    # User-facing surfaces written from fixed templates here (no model involved). Returned so
    # template_debt_pct counts them: it used to count the entity pages and the dashboard only.
    template_surfaces = ["App.tsx", "pages/LoginPage.tsx", "pages/NotFoundPage.tsx"]

    # Phase 4: Core pages
    write_with_guard_fn(src_dir / "pages" / "LoginPage.tsx", generate_login_page_fn(project_name, layout_mode=layout_mode))
    write_with_guard_fn(src_dir / "pages" / "NotFoundPage.tsx", generate_not_found_page_fn())
    if layout_mode == "dual":
        write_with_guard_fn(
            src_dir / "pages" / "CustomerHome.tsx",
            generate_customer_home_fn(
                entities, route_map, project_name, domain,
                app_brand=app_brand, app_tagline=app_tagline,
            ),
        )
        template_surfaces.append("pages/CustomerHome.tsx")

    # Phase 4b: Landing page
    if has_landing_page:
        logger.info("p05: has_landing_page=True — generating LandingPage.tsx")
        (src_dir / "pages").mkdir(parents=True, exist_ok=True)
        _landing_code = generate_landing_page_fn(
            project_name=project_name,
            tagline=app_brand.get("tagline") or app_tagline or f"The smarter way to manage {domain.replace('_', ' ')}",
            entities=entities,
            domain=domain,
            app_brand=app_brand,
        )
        write_with_guard_fn(src_dir / "pages" / "LandingPage.tsx", _landing_code)
        template_surfaces.append("pages/LandingPage.tsx")

    # Phase 4c: SSE realtime hook
    if realtime_features:
        logger.info("p05: realtime_features=%s — generating useRealtimeStream.ts", realtime_features)
        (src_dir / "hooks").mkdir(parents=True, exist_ok=True)
        write_with_guard_fn(src_dir / "hooks" / "useRealtimeStream.ts", generate_sse_hook_fn(realtime_features, project_name))

    # Phase 4d: WebSocket hook
    if has_websocket:
        logger.info("p05: websocket pattern active — generating useWebSocket.ts")
        (src_dir / "hooks").mkdir(parents=True, exist_ok=True)
        write_with_guard_fn(src_dir / "hooks" / "useWebSocket.ts", generate_use_websocket_hook_fn())

    # Phase 5: Layout components
    if layout_mode == "dual":
        write_with_guard_fn(src_dir / "components" / "CustomerLayout.tsx", generate_customer_layout_fn(entities, project_name))
        write_with_guard_fn(src_dir / "components" / "AdminLayout.tsx", generate_admin_layout_fn(entities, project_name))
        write_with_guard_fn(src_dir / "components" / "Layout.tsx", "export { AdminLayout as Layout } from './AdminLayout'\n")
        template_surfaces += ["components/CustomerLayout.tsx", "components/AdminLayout.tsx"]
    else:
        _layout_code = generate_mobile_first_layout_fn(entities, project_name)
        write_with_guard_fn(src_dir / "components" / "Layout.tsx", _layout_code)
        template_surfaces.append("components/Layout.tsx")

    write_with_guard_fn(src_dir / "components" / "DataTable.tsx", generate_data_table_fn())
    write_with_guard_fn(src_dir / "components" / "CrudModal.tsx", generate_crud_modal_fn())
    write_with_guard_fn(src_dir / "components" / "Toaster.tsx", generate_toaster_fn())
    write_with_guard_fn(src_dir / "components" / "ErrorBoundary.tsx", generate_error_boundary_fn())
    # Every generated entity page imports these three; the generators existed but nothing wrote the files,
    # so the build failed with "cannot resolve ../components/Pagination" (KAN-168).
    write_with_guard_fn(src_dir / "components" / "Pagination.tsx", _generate_pagination())
    write_with_guard_fn(src_dir / "components" / "Skeleton.tsx", _generate_skeleton())
    write_with_guard_fn(src_dir / "components" / "RoleGuard.tsx", _generate_role_guard())
    return template_surfaces


async def generate_domain_widget(
    *,
    src_dir: Path,
    domain: str,
    entities: List[Dict[str, Any]],
    project_name: str,
    mem: str,
    primary_hex: str,
    secondary_hex: str,
    background_hex: str,
    surface_hex: str,
    font_pairing: str,
    border_radius: str,
    density: str,
    phase_start: float,
    phase_timeout: float,
    generate_domain_component_fn: Any,
    write_with_guard_fn: Any,
    accumulated_context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Phase 7: Generate optional LLM DomainWidget component.

    Returns True if the widget was generated.  Skips silently if phase timeout
    is exceeded or the LLM call fails.
    """
    if asyncio.get_event_loop().time() - phase_start >= phase_timeout:
        return False

    domain_widget_generated = False
    try:
        domain_component = await generate_domain_component_fn(
            domain, entities, project_name, mem,
            primary_hex=primary_hex, secondary_hex=secondary_hex,
            background_hex=background_hex, surface_hex=surface_hex,
            font_pairing=font_pairing, border_radius=border_radius,
            density=density,
            accumulated_context=accumulated_context,
        )
        if domain_component:
            write_with_guard_fn(src_dir / "components" / "DomainWidget.tsx", domain_component)
            dashboard_file = src_dir / "pages" / "Dashboard.tsx"
            if dashboard_file.exists():
                content = dashboard_file.read_text()
                if "DomainWidget" not in content:
                    content = content.replace(
                        "import { useQuery }",
                        "import DomainWidget from '../components/DomainWidget'\nimport { useQuery }",
                        1,
                    )
                    content = content.replace(
                        "{/* DOMAIN_WIDGET_SLOT */}",
                        '<div className="mt-8"><DomainWidget /></div>',
                        1,
                    )
                    dashboard_file.write_text(content)
            domain_widget_generated = True
    except Exception as _de:
        logger.debug("p05_frontend: domain component failed: %s", _de)
        try:
            dashboard_file = src_dir / "pages" / "Dashboard.tsx"
            if dashboard_file.exists():
                dashboard_file.write_text(
                    dashboard_file.read_text().replace("      {/* DOMAIN_WIDGET_SLOT */}\n", "")
                )
        except Exception as _clean_exc:
            logger.warning("p05: dashboard cleanup failed: %s", _clean_exc)
    return domain_widget_generated


def detect_layout_mode(
    *,
    designer_spec: Dict[str, Any],
    design: Dict[str, Any],
    domain: str,
    raw_input: str,
    has_customer_portal: Optional[bool],
) -> str:
    """Resolve the layout mode from spec + domain signals.

    Returns one of: "dual" | "admin" | "storefront".
    Priority: explicit designer_spec.layout_mode → design.layout →
              has_customer_portal flag → domain bucket → keyword scan → "dual".
    """
    if "layout_mode" in (designer_spec or {}):
        return designer_spec["layout_mode"]

    _layout_from_spec = (design.get("layout") or "")
    if _layout_from_spec:
        return _layout_from_spec

    if has_customer_portal is True:
        return "dual"
    if has_customer_portal is False:
        return "admin"

    # Fallback: domain bucket + keyword scan
    _raw = raw_input.lower()
    if "dual portal" in _raw or "customer portal" in _raw or "member portal" in _raw:
        return "dual"
    if domain in _DUAL_PORTAL_DOMAINS:
        return "dual"
    if domain in _INTERNAL_ONLY_DOMAINS:
        return "admin"
    if "storefront" in _raw or "customer-facing" in _raw or "landing page" in _raw:
        return "storefront"
    if "admin panel" in _raw or "internal tool" in _raw or "back office" in _raw or "back-office" in _raw:
        return "admin"
    return "dual"


async def assemble_domain_pages(
    *,
    src_dir: Path,
    domain: str,
    domain_ir: Any,
    entities: List[Dict[str, Any]],
    build_types: List[str],
    layout_mode: str,
    route_map: Dict[str, str],
    project_name: str,
    data: Dict[str, Any],
    output_dir: Path,
    phase_start: float,
    phase_timeout: float,
    write_with_guard_fn: Any,
    generate_product_grid_fn: Any,
    generate_entity_page_fn: Any,
    generate_domain_dashboard_fn: Any,
    is_product_entity_fn: Any,
    to_pascal_case_fn: Any,
    pluralise_fn: Any,
    run_frontend_governor_fn: Any,
    write_domain_pages_fn: Any,
) -> dict:
    """Generate Phase 6 entity CRUD pages and domain-specific pages.

    When domain_ir is present, uses IR-typed generators for Dashboard and
    entity pages.  Falls back to the generic domain-dashboard + entity-page
    generators otherwise.  Also calls write_domain_pages for IoT/ERP/Social/etc.
    pages and run_frontend_governor for completeness checking.

    Returns {"llm_count": N, "template_count": M} for template_debt_pct.
    """

    logger.info("p05: Generating entity CRUD pages...")
    llm_count = 0
    template_count = 0
    _tokens = get_design_tokens(domain)
    _raw_input = (data or {}).get("raw_input", "")

    if domain_ir and domain_ir.entities:
        from aether_os.phases.p05_frontend.ir_generators import (
            generate_ir_dashboard_tsx as _gen_dash,
            generate_ir_entity_page as _gen_ent_page,
            generate_ir_types_ts as _gen_types,
        )
        _dash_llm = await write_dashboard_llm(
            domain=domain, entities=entities, project_name=project_name,
            raw_input=_raw_input, domain_ir=domain_ir, design_tokens=_tokens,
        )
        if _dash_llm:
            (src_dir / "pages" / "Dashboard.tsx").write_text(_dash_llm)
            llm_count += 1
        else:
            (src_dir / "pages" / "Dashboard.tsx").write_text(
                _gen_dash(domain_ir, entities, project_name, domain=domain)
            )
            template_count += 1
        _ir_sem = page_semaphore()

        async def _write_ir_entity(ir_entity):
            pascal_name = ir_entity.name
            _ir_ent_dict = {
                "table": ir_entity.table,
                "name": ir_entity.name,
                "fields": [{"name": f.name, "type": str(getattr(f, "type", "string"))} for f in ir_entity.fields],
                "columns": [f.name for f in ir_entity.fields],
            }
            if layout_mode == "storefront" and is_product_entity_fn(ir_entity.table):
                write_with_guard_fn(
                    src_dir / "pages" / f"{pascal_name}Page.tsx",
                    generate_product_grid_fn(_ir_ent_dict, route_map),
                )
                return 0, 1
            async with _ir_sem:
                _llm_code = await write_entity_page_llm(
                    entity=_ir_ent_dict, route_map=route_map,
                    project_name=project_name, domain=domain,
                    raw_input=_raw_input, domain_ir=domain_ir,
                    design_tokens=_tokens,
                )
            if _llm_code:
                write_with_guard_fn(src_dir / "pages" / f"{pascal_name}Page.tsx", _llm_code)
                return 1, 0
            write_with_guard_fn(src_dir / "pages" / f"{pascal_name}Page.tsx", _gen_ent_page(ir_entity))
            return 0, 1

        _ir_results = await asyncio.gather(*[_write_ir_entity(e) for e in domain_ir.entities])
        for _ld, _td in _ir_results:
            llm_count += _ld
            template_count += _td
        (src_dir / "types" / "index.ts").write_text(_gen_types(domain_ir))
    else:
        # Non-IR path: LLM dashboard first, template fallback
        _dash_llm = await write_dashboard_llm(
            domain=domain, entities=entities, project_name=project_name,
            raw_input=_raw_input, domain_ir=domain_ir, design_tokens=_tokens,
        )
        if _dash_llm:
            (src_dir / "pages" / "Dashboard.tsx").write_text(_dash_llm)
            llm_count += 1
        else:
            _dash_code = generate_domain_dashboard_fn(domain, entities)
            (src_dir / "pages" / "Dashboard.tsx").write_text(_dash_code)
            template_count += 1

        _global_fk_refs: Dict[str, Dict[str, str]] = {}
        if domain_ir:
            try:

                # the referenced entity's real table, not a guess: MembershipPlan is `membership_plans`, not `membershipplans`
                _table_of = {e.name.lower(): e.table for e in (domain_ir.entities or []) if getattr(e, "table", "")}
                for ir_ent in (domain_ir.entities or []):
                    for ir_field in ir_ent.fields:
                        if ir_field.type == AetherType.FK and ir_field.ref_entity:
                            ref_lower = ir_field.ref_entity.lower()
                            _global_fk_refs[ir_field.name] = {
                                "endpoint": f"/api/{_table_of.get(ref_lower) or pluralise_fn(ref_lower)}",
                                "label_key": getattr(ir_field, "display_field", None) or "name",
                            }
            except Exception as _fk_exc:
                logger.warning("p05: FK refs extraction failed: %s", _fk_exc)

        _ent_sem = page_semaphore()

        async def _write_non_ir_entity(ent):
            if asyncio.get_event_loop().time() - phase_start > phase_timeout:
                logger.warning("p05: phase watchdog triggered (25m) — skipping entity page")
                return 0, 0
            pascal = ent.get("name") or to_pascal_case_fn(ent["table"])
            if layout_mode == "storefront" and is_product_entity_fn(ent["table"]):
                write_with_guard_fn(src_dir / "pages" / f"{pascal}Page.tsx", generate_product_grid_fn(ent, route_map))
                return 0, 1
            async with _ent_sem:
                _llm_code = await write_entity_page_llm(
                    entity=ent, route_map=route_map,
                    project_name=project_name, domain=domain,
                    raw_input=_raw_input, domain_ir=domain_ir,
                    design_tokens=_tokens,
                )
            code = _llm_code if _llm_code else generate_entity_page_fn(ent, route_map, fk_refs=_global_fk_refs or None)
            write_with_guard_fn(src_dir / "pages" / f"{pascal}Page.tsx", code)
            return (1, 0) if _llm_code else (0, 1)

        _ent_results = await asyncio.gather(*[_write_non_ir_entity(e) for e in entities])
        for _ld, _td in _ent_results:
            llm_count += _ld
            template_count += _td

    run_frontend_governor_fn(
        data,
        [e.get("name", e["table"]) + "Page" for e in entities],
        output_dir,
    )
    write_domain_pages_fn(src_dir, domain, build_types)
    return {"llm_count": llm_count, "template_count": template_count}
