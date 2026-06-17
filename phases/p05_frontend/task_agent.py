"""P05 Frontend Task Agent — React 18 + Vite 5 + TypeScript + TanStack project generator.

Strategy:
  1. Read architecture.json from p02 to get project name, db_schema, endpoints, route_map.
  2. Generate a complete frontend/ subdirectory with a production-ready React/Vite/TanStack project.
  3. Write docker-compose.yml to the parent project directory.
  4. ONE optional LLM call generates a domain-specific React component (DomainWidget.jsx) and
     injects it into Dashboard.tsx — non-fatal if it fails.
"""
from __future__ import annotations

import json
import logging
import re
import os
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aether_os.phases.base import TaskResult
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
)
from aether_os.phases.p05_frontend.preview import (
    take_preview_screenshot,
    apply_gate2_revisions,
)

logger = logging.getLogger(__name__)

# Backward-compatible aliases (used by tests and ir_generators)
_read_architecture = read_architecture
_generate_nginx_conf = generate_nginx_conf
_generate_storefront_home = generate_storefront_home


def _write_with_guard(path: Path, content: str) -> None:
    """Write file if it doesn't already exist; logs progress for the SSE live-log stream."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    try:
        parts = path.parts
        rel = path.name
        if "frontend" in parts:
            idx = parts.index("frontend")
            rel = "/".join(parts[idx + 1:])
        logger.info("p05: wrote %s (%d bytes)", rel, len(content))
    except Exception:
        pass




async def _generate_file(
    filename: str,
    prompt: str,
    task_type: str = "code_generation",
    timeout: float = 90.0,
) -> Optional[str]:
    """Single LLM call with hard per-file timeout — returns None on timeout/error so callers skip gracefully."""
    from aether_os.core.llm.client import get_llm_client
    client = get_llm_client()
    try:
        return await asyncio.wait_for(
            client.call(prompt, task_type=task_type),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("p05: LLM call for %s timed out after %.0fs", filename, timeout)
        return None
    except Exception as exc:
        logger.warning("p05: LLM call for %s failed: %s", filename, exc)
        return None



async def _generate_domain_component(
    domain: str, entities: List[dict], project_name: str, mem_hint: str = "",
    primary_hex: str = "",
    secondary_hex: str = "",
    background_hex: str = "",
    surface_hex: str = "",
    font_pairing: str = "",
    border_radius: str = "",
    density: str = "",
) -> Optional[str]:
    """Generate a domain-specific React component via one LLM call with hardcoded fallback."""
    from aether_os.core.llm.client import get_llm_client
    
    # Check fallback first to ensure we have one
    fallback = DOMAIN_FALLBACK_WIDGETS.get(domain, "export default function DomainWidget() { return <div>Domain Overview</div> }")

    component_desc = DOMAIN_COMPONENT_DESC.get(domain, DOMAIN_COMPONENT_DESC["saas"])
    entity_names = [e.get("name", "") or e.get("table", "") for e in entities[:5]] if entities else []

    # Inject golden few-shot examples for this domain
    golden_hint = ""
    try:
        from aether_os.core.learning.golden_retriever import get_golden_examples, format_golden_hint_p05
        _examples = await get_golden_examples(domain, limit=2)
        golden_hint = format_golden_hint_p05(_examples)
    except Exception:
        pass

    # Domain-appropriate colour palette hints so the LLM picks scheme-consistent colours
    _domain_color_hints: Dict[str, str] = {
        "healthcare":   "teal palette: bg-teal-50/100, text-teal-800/900, borders teal-200, accents teal-600",
        "fintech":      "dark navy-gold: bg-slate-900, text-yellow-300, cards bg-slate-800, accents yellow-400",
        "ecommerce":    "rose-pink: bg-rose-50, text-rose-900, cards bg-white border-rose-100, accents rose-600",
        "marketplace":  "violet: bg-violet-50, text-violet-900, cards bg-white border-violet-100, accents violet-600",
        "education":    "sky-cyan: bg-sky-50, text-sky-900, cards bg-white border-sky-100, accents sky-600",
        "gym_fitness":  "red-energy: bg-red-50, text-red-900, cards bg-white border-red-100, accents red-600",
        "fitness":      "red-energy: bg-red-50, text-red-900, cards bg-white border-red-100, accents red-600",
        "real_estate":  "emerald: bg-emerald-50, text-emerald-900, cards bg-white border-emerald-100, accents emerald-600",
        "hospitality":  "amber-warm: bg-amber-50, text-amber-900, cards bg-white border-amber-100, accents amber-600",
        "restaurant":   "orange-warm: bg-orange-50, text-orange-900, cards bg-white border-orange-100, accents orange-600",
        "food":         "orange-warm: bg-orange-50, text-orange-900, cards bg-white border-orange-100, accents orange-600",
        "logistics":    "slate-blue: bg-slate-50, text-slate-900, cards bg-white border-slate-200, accents slate-600",
        "iot":          "slate-blue: bg-slate-900, text-cyan-300, cards bg-slate-800, accents cyan-400",
        "hrm":          "indigo: bg-indigo-50, text-indigo-900, cards bg-white border-indigo-100, accents indigo-600",
        "crm":          "indigo: bg-indigo-50, text-indigo-900, cards bg-white border-indigo-100, accents indigo-600",
        "analytics":    "indigo: bg-indigo-50, text-indigo-900, cards bg-white border-indigo-100, accents indigo-600",
        "saas":         "violet-purple: bg-violet-50, text-violet-900, cards bg-white border-violet-100, accents violet-600",
        "security":     "slate-red: bg-slate-900, text-red-300, cards bg-slate-800 border-slate-700, accents red-500",
        "sports":       "green-energy: bg-green-50, text-green-900, cards bg-white border-green-100, accents green-600",
        "library":      "stone: bg-stone-50, text-stone-900, cards bg-white border-stone-200, accents amber-700",
    }
    if primary_hex:
        # Use user's actual designer colors
        bg = background_hex or "#0f172a"
        surface = surface_hex or "#1e293b"
        primary = primary_hex
        secondary = secondary_hex or primary_hex
        _color_hint = (
            f"EXACT brand colors — use these hex values via Tailwind arbitrary values: "
            f"primary: {primary} (use as [background-color:{primary}] or bg-[{primary}]), "
            f"secondary: {secondary}, "
            f"background: {bg} (page bg), "
            f"surface: {surface} (card/panel bg). "
            f"Do NOT substitute generic Tailwind palette colors — use the exact hex values provided."
        )
    else:
        # Fall back to domain-based color hints
        _color_hint = _domain_color_hints.get(domain, "white/gray neutral: bg-white, text-gray-900, cards bg-white border-gray-100")

    prompt = (
        f'Generate a React functional component for a {domain} application called "{project_name}".\n\n'
        f"The component should render: {component_desc}\n\n"
        f"{mem_hint}"
        f"{golden_hint}"
        "Hard requirements:\n"
        f"- Tailwind CSS only — use the domain colour scheme: {_color_hint}\n"
        "- Use lucide-react icons (import at top: import {{ ... }} from 'lucide-react')\n"
        "- ALL data is static/mock — zero API calls, zero props, zero useState hooks for fetching\n"
        "- Export: export default function DomainWidget() {{}}\n"
        "- Maximum 250 lines — use the space for rich, domain-appropriate visuals\n"
        "- Visual polish: rounded-2xl, shadows, colour badges, proper spacing — make it look like a real product\n"
        f"- Entities available in this app (for label inspiration): {', '.join(entity_names)}\n"
        f"- Design personality: {domain} apps should feel visually distinct — avoid generic grey/white Bootstrap-style layouts\n\n"
        "- Responsive Design: Use Tailwind responsive prefixes (sm:, md:, lg:) on ALL grid/flex containers and text size declarations.\n"
        "- Accessibility: Use 'aria-label' on every icon-only button; use 'htmlFor' and 'aria-label' on all inputs.\n"
        "- Loading/Empty states: Include an 'isLoading' branch showing a skeleton/spinner and an 'isEmpty' branch with an empty-state illustration/text.\n"
        "- Glassmorphism cards: use bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-6 shadow-2xl for all card/panel elements\n"
        "- Gradient buttons: primary action buttons must use bg-gradient-to-r from the primary color to secondary color, with shadow-lg and hover:scale-105 transition\n"
        "- Skeleton loaders: every async/loading state must show animated skeleton placeholders using animate-pulse bg-white/10 rounded blocks, NOT a spinner\n"
        "- Framer Motion animations: wrap page sections in motion.div with initial={{opacity:0,y:20}} animate={{opacity:1,y:0}} transition={{type:'spring',stiffness:300,damping:30}}\n"
        "- shadcn/ui components: use shadcn/ui primitives (Button, Card, Badge, Input, Table) — import from '@/components/ui/*' — do NOT build raw HTML form elements or buttons\n"
        "- Visual depth: add at least one gradient orb or abstract shape in hero/header sections using absolute positioned divs with rounded-full blur-3xl opacity-20 bg-[primaryColor]\n"
        + (f"- Typography: use '{font_pairing.split('+')[0].strip()}' as the primary font via className='font-sans' (ensure it's loaded in index.html)\n" if font_pairing else "- Typography: use Inter as the primary font\n")
        + (f"- Border radius: apply '{border_radius}' consistently — if 'Rounded', use rounded-xl/2xl; if 'Sharp', use rounded-sm/none; if 'Pill', use rounded-full on buttons\n" if border_radius else "")
        + (f"- Density: '{density}' — if 'Compact', use p-2/p-3 and text-sm; if 'Normal', use p-4/p-6; if 'Comfortable', use p-6/p-8 and text-base\n" if density else "")
        + "\nReturn ONLY the React component code. No markdown fences, no explanation."
    )

    client = get_llm_client()
    try:
        # result = await client.call(prompt, task_type="ui_component", max_tokens=2000)
        result = await asyncio.wait_for(
            client.call(prompt, task_type="ui_component", max_tokens=2000),
            timeout=90.0
        )
        if (
            result
            and "export default" in result
            and "function" in result
            and "return" in result
            and len(result) > 200
        ):
            # Strip accidental markdown fences
            result = re.sub(r"^```[a-z]*\n?", "", result.strip())
            result = re.sub(r"\n?```$", "", result.strip())
            return result
    except asyncio.TimeoutError:
        logger.warning("p05: LLM DomainWidget generation timed out after 10s")
    except Exception as exc:
        logger.warning(f"p05: LLM DomainWidget generation failed: {exc}")

    logger.info(f"p05: Using hardcoded DomainWidget fallback for {domain}")
    # Minimal no-op fallback as requested by user
    return "// Auto-generated fallback DomainWidget\nexport default function DomainWidget() { return null; }"



# ── Admin Derivation ─────────────────────────────────────────────────────────

CUSTOMER_TO_ADMIN_MAP = {
    "browse products":           ["product catalog CRUD", "category management", "inventory tracking"],
    "place orders":              ["order management", "order status updates", "fulfillment workflow"],
    "book appointments":         ["appointment calendar", "availability management", "provider schedules"],
    "register/enroll":           ["member/student management", "enrollment approval"],
    "make payments":             ["billing dashboard", "payment history", "refund management"],
    "leave reviews":             ["review moderation queue", "response management"],
    "upload documents":          ["document review", "approval workflow"],
    "track deliveries":          ["driver management", "route tracking", "delivery status"],
    "book rooms/tables":         ["availability calendar", "booking management", "check-in/out"],
}

def _derive_admin_features(customer_flows: List[str]) -> List[str]:
    """Derive list of admin management sections based on customer actions."""
    admin_features = ["User Management", "Settings", "Analytics"]
    for flow in customer_flows:
        for action, features in CUSTOMER_TO_ADMIN_MAP.items():
            if action in flow.lower():
                admin_features.extend(features)
    return sorted(list(set(admin_features)))




# ── Customer Portal Generation ────────────────────────────────────────────────

async def _generate_customer_portal(domain: str, design_brief: dict, route_map: dict, target_dir: Path) -> Dict[str, str]:
    """Generate rich customer-facing portal pages based on design brief and domain."""
    (target_dir / "customer").mkdir(parents=True, exist_ok=True)
    pages = {}
    
    # Layout and design tokens from brief
    layout = design_brief.get("layout_patterns", {}).get("navigation", "sticky")
    primary_color = design_brief.get("color_scheme", {}).get("primary", "indigo-600")
    
    # 1. Home Page (Rich Hero + Features)
    home_code = f"""
import React from 'react';
import {{ ArrowRight, Star, Shield, Zap }} from 'lucide-react';

export default function Home() {{
  return (
    <div className="min-h-screen bg-white">
      {{/* Hero Section */}}
      <div className="relative pt-16 pb-32 flex content-center items-center justify-center min-h-[75vh]">
        <div className="container relative mx-auto">
          <div className="items-center flex flex-wrap">
            <div className="w-full lg:w-6/12 px-4 ml-auto mr-auto text-center">
              <h1 className="text-5xl font-semibold text-gray-900 leading-tight">
                Premium {domain.replace('_', ' ').capitalize()} Solutions for Your Business
              </h1>
              <p className="mt-4 text-lg text-gray-600">
                Experience the next generation of {domain.replace('_', ' ')} management. 
                Built for scale, speed, and reliability.
              </p>
              <div className="mt-10 flex justify-center gap-x-6">
                <Link to="/browse" className="rounded-md bg-{{primary_color}} px-6 py-3 text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-all flex items-center gap-2">
                  Get Started <ArrowRight size={{16}} />
                </Link>

              </div>
            </div>
          </div>
        </div>
      </div>

      {{/* Features Section */}}
      <div className="py-24 bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center">
            <h2 className="text-3xl font-bold text-gray-900">Why Choose Us?</h2>
          </div>
          <div className="mt-20 grid grid-cols-1 gap-12 sm:grid-cols-2 lg:grid-cols-3">
            <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100">
              <Zap className="text-{primary_color} mb-4" size={{32}} />
              <h3 className="text-xl font-bold mb-2">Lightning Fast</h3>
              <p className="text-gray-600">Optimized performance for the best user experience in the {domain} industry.</p>
            </div>
            <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100">
              <Shield className="text-{primary_color} mb-4" size={{32}} />
              <h3 className="text-xl font-bold mb-2">Secure by Design</h3>
              <p className="text-gray-600">Enterprise-grade security protecting your sensitive {domain} data.</p>
            </div>
            <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100">
              <Star className="text-{primary_color} mb-4" size={{32}} />
              <h3 className="text-xl font-bold mb-2">Top Rated</h3>
              <p className="text-gray-600">Trusted by thousands of businesses worldwide for their daily operations.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}}
"""
    (target_dir / "customer" / "Home.tsx").write_text(home_code)
    pages["Home.tsx"] = home_code
    
    # 2. About Page
    about_code = f"""
export default function About() {{
  return (
    <div className="max-w-4xl mx-auto py-20 px-4">
      <h1 className="text-4xl font-bold mb-8">About Our {domain.capitalize()} Platform</h1>
      <p className="text-lg text-gray-600 mb-4">
        We are dedicated to providing the best {domain.replace('_', ' ')} management experience.
        Our mission is to empower business owners with the tools they need to succeed in a digital world.
      </p>
    </div>
  );
}}
"""
    (target_dir / "customer" / "AboutPage.tsx").write_text(about_code)
    pages["AboutPage.tsx"] = about_code
    
    return pages




async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    _phase_start = asyncio.get_event_loop().time()
    _PHASE_TIMEOUT = 1500.0  # 25 minutes — stop generating new files but still build what exists

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
                from aether_os.core.domain_ir import DomainIR as _DomainIR
                from aether_os.phases.p05_frontend.ir_generators import ir_to_p05_entities as _ir_to_ents
                _domain_ir = _DomainIR.load(_ir_p)
                if _domain_ir.entities:
                    entities = _ir_to_ents(_domain_ir)
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

        # Problem 67: 3rd fallback — try data["entities"] (direct pipeline propagation)
        # and data["architecture"]["entities"] if still stuck on generic "items" fallback.
        if len(entities) == 1 and entities[0]["table"] == "items":
            _data_entities = data.get("entities", [])
            if not _data_entities:
                _data_entities = data.get("architecture", {}).get("entities", [])
            if _data_entities:
                _p67_ents: List[dict] = []
                for _e in _data_entities:
                    _ename = _e.get("name", _e.get("table", "")) if isinstance(_e, dict) else str(_e)
                    if not _ename or _ename.lower() in ("user", "users"):
                        continue
                    _etable = re.sub(r'([A-Z])', lambda m: '_' + m.group(1).lower(), _ename).lstrip('_').lower()
                    _ecols = []
                    if isinstance(_e, dict):
                        for _f in _e.get("fields", _e.get("columns", _e.get("attributes", []))):
                            if isinstance(_f, dict):
                                _ecols.append(_f.get("name", _f.get("column", "")))
                            elif isinstance(_f, str):
                                _ecols.append(_f)
                    if not _ecols:
                        _ecols = ["id", "name", "status", "created_at"]
                    _p67_ents.append({"table": _etable, "name": _ename, "columns": [c for c in _ecols if c]})
                if _p67_ents:
                    logger.info(
                        "p05 [P67]: replaced 'items' fallback with %d entities from pipeline data: %s",
                        len(_p67_ents), [e["table"] for e in _p67_ents],
                    )
                    entities = _p67_ents

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

    from aether_os.phases.utils import memory_hint
    mem = memory_hint(memory_ctx)

    # Extract designer spec settings
    designer_spec = data.get("designer_spec") or {}
    _design = designer_spec.get("design") or {}
    ui_theme: str = _design.get("ui_theme", "") or ""
    page_transition: str = _design.get("page_transition", "fade") or "fade"
    animation_speed: str = _design.get("animation_speed", "normal") or "normal"
    micro_interactions: bool = bool(_design.get("micro_interactions", True))
    scroll_reveal: bool = bool(_design.get("scroll_reveal", True))
    loading_style: str = _design.get("loading_style", "shimmer") or "shimmer"
    hover_lift: bool = bool(_design.get("hover_lift", True))
    primary_hex: str = _design.get("primary_hex", "") or ""
    secondary_hex: str = _design.get("secondary_hex", "") or ""
    background_hex: str = _design.get("background_hex", "") or ""
    surface_hex: str = _design.get("surface_hex", "") or ""
    font_pairing: str = _design.get("font_pairing", "") or ""
    border_radius: str = _design.get("border_radius", "") or ""
    density: str = _design.get("density", "") or ""

    _domain_theme_map = {
        "healthcare": "healthcare", "fintech": "fintech", "ecommerce": "ecommerce",
        "marketplace": "marketplace", "education": "education", "fitness": "fitness",
        "gym_fitness": "gym_fitness", "real_estate": "real_estate",
        "hospitality": "hospitality", "restaurant": "restaurant", "food": "food",
        "logistics": "logistics", "iot": "iot", "hrm": "hrm", "crm": "crm",
        "analytics": "analytics", "saas": "saas",
    }
    if not ui_theme or ui_theme == "default":
        _detected_domain = data.get("domain", "") or domain or ""
        ui_theme = _domain_theme_map.get(_detected_domain.lower(), "default")

    # Detect layout mode
    _layout_from_spec = (_design.get("layout") or "")
    _raw = data.get("raw_input", "").lower()
    _domain_val = domain

    _dual_portal_domains = ("ecommerce", "marketplace", "library", "healthcare",
                             "hospitality", "education", "events", "real_estate",
                             "fitness", "food", "saas", "gym_fitness", "sports",
                             "restaurant")
    _internal_only_domains = ("crm", "hrm", "analytics", "fintech", "iot",
                               "security", "logistics")

    if "layout_mode" in (designer_spec or {}):
        layout_mode = designer_spec["layout_mode"]
    elif _layout_from_spec:
        layout_mode = _layout_from_spec
    elif "dual portal" in _raw or "customer portal" in _raw or "member portal" in _raw:
        layout_mode = "dual"
    elif _domain_val in _dual_portal_domains:
        layout_mode = "dual"
    elif _domain_val in _internal_only_domains:
        layout_mode = "admin"
    elif "storefront" in _raw or "customer-facing" in _raw or "landing page" in _raw:
        layout_mode = "storefront"
    elif "admin panel" in _raw or "internal tool" in _raw or "back office" in _raw or "back-office" in _raw:
        layout_mode = "admin"
    else:
        layout_mode = "dual"
    logger.info("p05_frontend: layout_mode=%s", layout_mode)

    # 3. Build frontend/ directory structure
    frontend_dir = output_dir / "frontend"
    src_dir = frontend_dir / "src"
    (src_dir / "lib").mkdir(parents=True, exist_ok=True)
    (src_dir / "types").mkdir(parents=True, exist_ok=True)
    (src_dir / "components").mkdir(parents=True, exist_ok=True)
    (src_dir / "pages").mkdir(parents=True, exist_ok=True)

    # ── Phase 1: Scaffolding (Static Files) ──
    logger.info("p05: Writing static scaffold files...")
    _write_with_guard(frontend_dir / "package.json", generate_package_json(project_slug))
    _write_with_guard(frontend_dir / "vite.config.ts", generate_vite_config())
    _write_with_guard(frontend_dir / "tsconfig.json", generate_tsconfig())
    _write_with_guard(frontend_dir / "tailwind.config.js", generate_tailwind_config(ui_theme))
    _write_with_guard(frontend_dir / "postcss.config.js", generate_postcss_config())
    _write_with_guard(frontend_dir / "index.html", generate_index_html(project_name, domain=domain))
    _write_with_guard(frontend_dir / "nginx.conf", generate_nginx_conf(data))
    _write_with_guard(frontend_dir / "Dockerfile", generate_dockerfile())
    _write_with_guard(frontend_dir / ".env.example", generate_env_example())
    _write_with_guard(frontend_dir / ".eslintrc.cjs", generate_eslint_config())
    _write_with_guard(frontend_dir / "README.md", generate_frontend_readme(project_name))
    _write_with_guard(src_dir / "index.css", generate_index_css(
        ui_theme=ui_theme,
        page_transition=page_transition,
        animation_speed=animation_speed,
        micro_interactions=micro_interactions,
        scroll_reveal=scroll_reveal,
        loading_style=loading_style,
        hover_lift=hover_lift,
    ))
    _write_with_guard(src_dir / "main.tsx", generate_main_tsx())

    # ── Phase 2: Core Logic (Library & Types) ──
    _write_with_guard(src_dir / "lib" / "auth.ts", generate_auth_ts())
    _write_with_guard(src_dir / "lib" / "api.ts", generate_api(entities, route_map))
    _write_with_guard(src_dir / "types" / "index.ts", generate_types(entities))

    # ── Phase 3: Critical Skeleton (App.tsx) ──
    logger.info("p05: Writing App.tsx skeleton...")
    _write_with_guard(src_dir / "App.tsx", generate_app(entities, dual_portal=(layout_mode == "dual")))

    # ── Phase 4: Core Pages ──
    _write_with_guard(src_dir / "pages" / "LoginPage.tsx", generate_login_page(project_name, layout_mode=layout_mode))
    _write_with_guard(src_dir / "pages" / "NotFoundPage.tsx", generate_not_found_page())
    if layout_mode == "dual":
        _write_with_guard(src_dir / "pages" / "CustomerHome.tsx", generate_customer_home(entities, route_map, project_name, domain))

    # ── Phase 5: Static Layout Components ──
    if layout_mode == "dual":
        _write_with_guard(src_dir / "components" / "CustomerLayout.tsx", generate_customer_layout(entities, project_name))
        _write_with_guard(src_dir / "components" / "AdminLayout.tsx", generate_admin_layout(entities, project_name))
        _write_with_guard(src_dir / "components" / "Layout.tsx", "export { AdminLayout as Layout } from './AdminLayout'\n")
    else:
        _write_with_guard(src_dir / "components" / "Layout.tsx", generate_layout(entities, project_name, layout_mode=layout_mode))
    
    _write_with_guard(src_dir / "components" / "DataTable.tsx", generate_data_table())
    _write_with_guard(src_dir / "components" / "CrudModal.tsx", generate_crud_modal())
    _write_with_guard(src_dir / "components" / "Toaster.tsx", generate_toaster())
    _write_with_guard(src_dir / "components" / "ErrorBoundary.tsx", generate_error_boundary())

    # ── Phase 6: Entity CRUD Pages ──
    logger.info("p05: Generating entity CRUD pages...")
    if _domain_ir and _domain_ir.entities:
        from aether_os.phases.p05_frontend.ir_generators import (
            generate_ir_dashboard_tsx as _gen_dash,
            generate_ir_entity_page as _gen_ent_page,
            generate_ir_types_ts as _gen_types,
        )
        (src_dir / "pages" / "Dashboard.tsx").write_text(_gen_dash(_domain_ir, entities, project_name, domain=domain))
        for ir_entity in _domain_ir.entities:
            pascal_name = ir_entity.name
            if layout_mode == "storefront" and is_product_entity(ir_entity.table):
                _ir_ent_dict = {
                    "table": ir_entity.table,
                    "name": ir_entity.name,
                    "columns": [f.name for f in ir_entity.fields],
                }
                _write_with_guard(src_dir / "pages" / f"{pascal_name}Page.tsx", generate_product_grid_page(_ir_ent_dict, route_map))
            else:
                _write_with_guard(src_dir / "pages" / f"{pascal_name}Page.tsx", _gen_ent_page(ir_entity))
        (src_dir / "types" / "index.ts").write_text(_gen_types(_domain_ir))
    else:
        (src_dir / "pages" / "Dashboard.tsx").write_text(generate_dashboard(entities, route_map, domain, ui_theme))
        _global_fk_refs: Dict[str, Dict[str, str]] = {}
        if _domain_ir:
            try:
                from aether_os.core.domain_ir import AetherType as _AT
                for ir_ent in (_domain_ir.entities or []):
                    for ir_field in ir_ent.fields:
                        if ir_field.type == _AT.FK and ir_field.ref_entity:
                            ref_lower = ir_field.ref_entity.lower()
                            _global_fk_refs[ir_field.name] = {
                                "endpoint": f"/api/{pluralise(ref_lower)}",
                                "label_key": getattr(ir_field, "display_field", None) or "name",
                            }
            except Exception: pass

        for ent in entities:
            if asyncio.get_event_loop().time() - _phase_start > _PHASE_TIMEOUT:
                logger.warning("p05: phase watchdog triggered (25m) — skipping remaining entity pages, proceeding to build")
                break
            pascal = ent.get("name") or to_pascal_case(ent["table"])
            if layout_mode == "storefront" and is_product_entity(ent["table"]):
                code = generate_product_grid_page(ent, route_map)
            else:
                code = generate_entity_page(ent, route_map, fk_refs=_global_fk_refs or None)
            _write_with_guard(src_dir / "pages" / f"{pascal}Page.tsx", code)
            await asyncio.sleep(0.01)

    # ── Phase 7: Optional LLM Component (DomainWidget) ──
    domain_widget_generated = False
    if asyncio.get_event_loop().time() - _phase_start < _PHASE_TIMEOUT:
      try:
        domain_component = await _generate_domain_component(
            domain, entities, project_name, mem,
            primary_hex=primary_hex, secondary_hex=secondary_hex,
            background_hex=background_hex, surface_hex=surface_hex,
            font_pairing=font_pairing, border_radius=border_radius,
            density=density,
        )
        if domain_component:
            _write_with_guard(src_dir / "components" / "DomainWidget.jsx", domain_component)
            dashboard_file = src_dir / "pages" / "Dashboard.tsx"
            if dashboard_file.exists():
                content = dashboard_file.read_text()
                if "DomainWidget" not in content:
                    content = content.replace("import { useQuery }", "import DomainWidget from '../components/DomainWidget'\nimport { useQuery }", 1)
                    content = content.replace("{/* DOMAIN_WIDGET_SLOT */}", '<div className="mt-8"><DomainWidget /></div>', 1)
                    dashboard_file.write_text(content)
            domain_widget_generated = True
      except Exception as _de:
        logger.debug("p05_frontend: domain component failed: %s", _de)
        try:
            dashboard_file = src_dir / "pages" / "Dashboard.tsx"
            if dashboard_file.exists():
                dashboard_file.write_text(dashboard_file.read_text().replace("      {/* DOMAIN_WIDGET_SLOT */}\n", ""))
        except Exception: pass

    # ── Phase 8: Customer Portal (Home, About) ──
    if asyncio.get_event_loop().time() - _phase_start < _PHASE_TIMEOUT:
        logger.info("p05: generating customer portal for %s", domain)
        await _generate_customer_portal(domain, design_brief, route_map, src_dir / "pages")
    else:
        logger.warning("p05: phase watchdog — skipping customer portal generation")

    # ── Phase 9: Tests ──
    tests_dir = src_dir / "__tests__"
    tests_dir.mkdir(parents=True, exist_ok=True)
    _write_with_guard(tests_dir / "setup.ts", generate_test_setup())
    _write_with_guard(tests_dir / "LoginPage.test.tsx", generate_login_test(project_name))
    _write_with_guard(tests_dir / "Dashboard.test.tsx", generate_dashboard_test())
    _write_with_guard(frontend_dir / "vitest.config.ts", generate_vitest_config())

    # ── Gate 3: Admin Requirements (Approval if NOT autonomous) ──
    customer_flows = [wf.trigger for wf in _domain_ir.workflows] if _domain_ir else []
    admin_features = _derive_admin_features(customer_flows)
    try:
        from aether_os.core.pipeline_state import publish_event
        from aether_os.core.decisions.decision_engine import Decision, get_decision_engine
        from aether_os.orchestrator.events import ACTIVE_RUN_ID
        run_id = ACTIVE_RUN_ID.get()

        if run_id and not is_autonomous:
            logger.info("p05: Waiting for Gate 3 (Admin Requirements) approval...")
            engine = get_decision_engine()
            decision = Decision(
                run_id=run_id, org_id=data.get("org_id", ""),
                decision_type="admin_spec_approval", title="Gate 3: Admin Portal Requirements",
                what=f"Admin panel features: {', '.join(admin_features)}",
                why="Confirm admin features before generation.", phase="p05_frontend",
            )
            await engine.request_approval(decision)
            await publish_event(run_id, {
                "type": "PhaseApprovalRequired", "phase": "p05_frontend", "gate": "gate_3",
                "decision_id": decision.id, "data": {"admin_features": admin_features}, "allow_overrides": True
            })
            resolved = await engine.await_decision(decision.id)
            if resolved.status == "approved" and resolved.human_choice:
                try:
                    if resolved.human_choice.strip().startswith("["): admin_features = json.loads(resolved.human_choice)
                    else: admin_features = [f.strip() for f in resolved.human_choice.split(",") if f.strip()]
                except Exception: pass
        else:
            logger.info("p05: Autonomous mode — bypassing Gate 3 approval.")
    except Exception as e:
        logger.warning(f"p05: Gate 3 skipped: {e}")

    # 4. Finalise project structure
    project_dir = output_dir.parent
    _write_with_guard(project_dir / "docker-compose.yml", generate_docker_compose(project_dir))

    _canonical_frontend = project_dir / "frontend"
    if not _canonical_frontend.exists() and frontend_dir.exists():
        try:
            import shutil as _shutil
            _shutil.copytree(str(frontend_dir), str(_canonical_frontend), ignore=_shutil.ignore_patterns("node_modules", ".git", "dist", "build"))
        except Exception: pass

    # 5. Write metadata
    generated_files = ["frontend/package.json", "frontend/src/App.tsx", "frontend/src/pages/Dashboard.tsx"]
    meta = {
        "project_name": project_name, "project_slug": project_slug, "domain": domain,
        "entities": [e["table"] for e in entities], "used_llm": domain_widget_generated,
        "files_generated": generated_files,
    }
    (output_dir / "frontend_meta.json").write_text(json.dumps(meta, indent=2))

    # ── Gate 2: Preview ──
    screenshot_path = ""
    preview_path = output_dir / "customer_portal_preview.png"
    if not is_autonomous and await take_preview_screenshot(frontend_dir, preview_path):
        screenshot_path = str(preview_path)

    try:
        if run_id and not is_autonomous:
            engine = get_decision_engine()
            decision = Decision(
                run_id=run_id, org_id=data.get("org_id", ""),
                decision_type="portal_preview_approval", title="Gate 2: Customer Portal Preview",
                what=f"Preview available at {screenshot_path}" if screenshot_path else "Preview unavailable.",
                why="Human confirmation of visual design.", phase="p05_frontend",
            )
            await engine.request_approval(decision)
            await publish_event(run_id, {
                "type": "PhaseApprovalRequired", "phase": "p05_frontend", "gate": "gate_2",
                "decision_id": decision.id,
                "screenshot_url": f"/api/artifacts/{{run_id}}/p05_frontend/customer_portal_preview.png" if screenshot_path else None,
            })
            resolved = await engine.await_decision(decision.id)
            if resolved.status == "approved" and resolved.human_choice:
                await apply_gate2_revisions(resolved.human_choice.strip(), frontend_dir, domain, project_name)
        elif run_id:
            logger.info("p05: Autonomous mode — bypassing Gate 2 approval.")
    except Exception: pass

    # ── Step 6: Final Build ──
    frontend_dir_final = project_dir / 'frontend'
    async with get_npm_semaphore():
        try:
            _hash = pkg_hash(frontend_dir_final)
            if not node_modules_fresh(frontend_dir_final, _hash):
                _NPM_SHARED_CACHE.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(subprocess.run, ["npm", "install", "--cache", str(_NPM_SHARED_CACHE)], cwd=str(frontend_dir_final), timeout=300)
                stamp_node_modules(frontend_dir_final, _hash)
            await asyncio.to_thread(subprocess.run, ["npm", "run", "build"], cwd=str(frontend_dir_final), timeout=600)
        except Exception as e:
            logger.error("p05: Build failed: %s", e)

    return TaskResult(output_path=str(frontend_dir_final), confidence=1.0, success=True, metadata=meta)
