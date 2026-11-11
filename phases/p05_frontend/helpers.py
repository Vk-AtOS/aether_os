"""P05 Frontend — helper functions extracted from task_agent.py.

Contains:
  - _write_with_guard          file-write helper with SSE progress logging
  - _generate_file             single LLM call with timeout
  - _generate_domain_component LLM-powered domain-specific React widget
  - CUSTOMER_TO_ADMIN_MAP      mapping of customer flows → admin features
  - _derive_admin_features     derive admin features from customer flows
  - _generate_customer_portal  generate customer-facing portal pages
  - _generate_landing_page     generate public marketing/landing page (has_landing_page=True)
  - _generate_sse_hook         generate SSE/EventSource React hook (realtime_features)
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.llm import client as _llm_client
from aether_os.phases.p05_frontend.prompts import (
    DOMAIN_FALLBACK_WIDGETS,
    DOMAIN_COMPONENT_DESC,
)

logger = logging.getLogger(__name__)

# Domain-appropriate colour palette hints so the LLM picks scheme-consistent colours
DOMAIN_COLOR_HINTS: Dict[str, str] = {
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
    except Exception as exc:
        logger.warning("p05: _write_with_guard progress log failed: %s", exc)


async def _generate_file(
    filename: str,
    prompt: str,
    task_type: str = "code_generation",
    timeout: float = 90.0,
) -> Optional[str]:
    """Single LLM call with hard per-file timeout — returns None on timeout/error so callers skip gracefully."""
    client = _llm_client.get_llm_client()
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


def _build_rag_context_p05(accumulated_context: dict, domain: str) -> str:
    """Retrieve ranked KG/RAG context for p05 frontend generation.
    Returns a formatted section string (or empty string if unavailable).
    Mirrors the pattern used in p04a_backend_codegen/prompts.py.
    """
    try:
        from aether_os.core.llm.retrieval_ranker import retrieve_for_phase, format_for_prompt
        from aether_os.core.llm.context_compressor import compress_context
        compressed_ctx = compress_context("p05_frontend", accumulated_context)
        ranked = retrieve_for_phase("p05_frontend", domain, compressed_ctx)
        return format_for_prompt(ranked, max_items=4)
    except Exception as exc:
        logger.debug("p05: KG/RAG context unavailable (non-fatal): %s", exc)
        return ""


async def _generate_domain_component(
    domain: str, entities: List[dict], project_name: str, mem_hint: str = "",
    primary_hex: str = "",
    secondary_hex: str = "",
    background_hex: str = "",
    surface_hex: str = "",
    font_pairing: str = "",
    border_radius: str = "",
    density: str = "",
    accumulated_context: Optional[dict] = None,
) -> Optional[str]:
    """Generate a domain-specific React component via one LLM call with hardcoded fallback."""

    # Check fallback first to ensure we have one
    fallback = DOMAIN_FALLBACK_WIDGETS.get(domain, "export default function DomainWidget() { return <div>Domain Overview</div> }")

    component_desc = DOMAIN_COMPONENT_DESC.get(domain, DOMAIN_COMPONENT_DESC.get("saas", "a SaaS dashboard widget"))
    entity_names = [e.get("name", "") or e.get("table", "") for e in entities[:5]] if entities else []

    # Inject KG/RAG architecture context from knowledge graph
    rag_context = _build_rag_context_p05(accumulated_context, domain) if accumulated_context else ""

    # Inject golden few-shot examples for this domain
    golden_hint = ""
    try:
        from aether_os.core.learning.golden_retriever import get_golden_examples, format_golden_hint_p05
        _examples = await get_golden_examples(domain, limit=2)
        golden_hint = format_golden_hint_p05(_examples)
    except Exception as exc:
        logger.debug("p05: golden retriever unavailable: %s", exc)

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
        _color_hint = DOMAIN_COLOR_HINTS.get(domain, "white/gray neutral: bg-white, text-gray-900, cards bg-white border-gray-100")

    _rag_section = (
        f"## Architecture Context (from knowledge graph)\n{rag_context}\n\n"
        if rag_context else ""
    )
    prompt = (
        f'Generate a React functional component for a {domain} application called "{project_name}".\n\n'
        f"The component should render: {component_desc}\n\n"
        f"{_rag_section}"
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

    client = _llm_client.get_llm_client()
    try:
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
        logger.warning("p05: LLM DomainWidget generation timed out after 90s")
    except Exception as exc:
        logger.warning("p05: LLM DomainWidget generation failed: %s", exc)

    logger.info("p05: Using hardcoded DomainWidget fallback for %s", domain)
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

async def _generate_customer_portal(
    domain: str,
    design_brief: dict,
    route_map: dict,
    target_dir: Path,
    user_personas: Optional[List[dict]] = None,
    project_name: str = "",
    app_brand: Optional[Dict[str, Any]] = None,
    app_tagline: str = "",
) -> Dict[str, str]:
    """Generate rich customer-facing portal pages based on design brief and domain."""
    (target_dir / "customer").mkdir(parents=True, exist_ok=True)
    pages: Dict[str, str] = {}
    _app_brand = app_brand or {}
    _personas = user_personas or []

    # Layout and design tokens from brief
    primary_color = design_brief.get("color_scheme", {}).get("primary", "indigo-600")

    # Derive hero copy — prefer app_brand fields, fall back to domain-generic copy
    _display_name = project_name or domain.replace("_", " ").capitalize()
    hero_heading = (
        _app_brand.get("headline")
        or project_name
        or f"{domain.replace('_', ' ').capitalize()} Platform"
    )
    hero_sub = (
        _app_brand.get("tagline")
        or app_tagline
        or f"Experience the next generation of {domain.replace('_', ' ')} management. Built for scale, speed, and reliability."
    )

    # Derive persona-aware CTA label from first customer-facing persona (if provided)
    _customer_persona = next(
        (p for p in _personas if isinstance(p, dict) and p.get("role", "").lower() not in ("admin", "staff", "manager", "operator")),
        None,
    )
    _cta_label = "Get Started"
    if _customer_persona:
        _role_name = _customer_persona.get("role", "")
        _key_action = (_customer_persona.get("key_actions") or [""])[0]
        if _key_action:
            _cta_label = _key_action.replace("_", " ").title()
        elif _role_name:
            _cta_label = f"Start as {_role_name}"

    # 1. Home Page (Rich Hero + Features)
    home_code = f"""\
// Auto-generated by AetherOS p05_frontend — customer portal Home
import React from 'react';
import {{ Link }} from '@tanstack/react-router';
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
                {hero_heading}
              </h1>
              <p className="mt-4 text-lg text-gray-600">
                {hero_sub}
              </p>
              <div className="mt-10 flex justify-center gap-x-6">
                <Link to="/browse" className="rounded-md bg-{primary_color} px-6 py-3 text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-all flex items-center gap-2">
                  {_cta_label} <ArrowRight size={{16}} />
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
            <h2 className="text-3xl font-bold text-gray-900">Why Choose {_display_name}?</h2>
          </div>
          <div className="mt-20 grid grid-cols-1 gap-12 sm:grid-cols-2 lg:grid-cols-3">
            <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100">
              <Zap className="text-{primary_color} mb-4" size={{32}} />
              <h3 className="text-xl font-bold mb-2">Lightning Fast</h3>
              <p className="text-gray-600">Optimized performance for the best user experience in the {domain.replace('_', ' ')} industry.</p>
            </div>
            <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100">
              <Shield className="text-{primary_color} mb-4" size={{32}} />
              <h3 className="text-xl font-bold mb-2">Secure by Design</h3>
              <p className="text-gray-600">Enterprise-grade security protecting your sensitive {domain.replace('_', ' ')} data.</p>
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
    about_code = f"""\
// Auto-generated by AetherOS p05_frontend — customer portal About
export default function About() {{
  return (
    <div className="max-w-4xl mx-auto py-20 px-4">
      <h1 className="text-4xl font-bold mb-8">About {_display_name}</h1>
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


# ── Landing Page Generation ───────────────────────────────────────────────────

def _generate_landing_page(
    project_name: str,
    tagline: str,
    entities: List[dict],
    domain: str,
    app_brand: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate LandingPage.tsx — public marketing page shown at '/' when has_landing_page=True.

    The current '/' (home) route should be moved to '/home' for authenticated users; this
    page is public (no auth required) and serves as the product's marketing entry point.
    """
    _app_brand = app_brand or {}
    _display_name = project_name or domain.replace("_", " ").title()
    _tagline = tagline or _app_brand.get("tagline") or f"The smarter way to manage {domain.replace('_', ' ')}"

    # Derive 3 feature highlights from the first 3 entity names
    _feature_entities = entities[:3] if len(entities) >= 3 else (entities + [{"table": "data", "name": "Data"}, {"table": "reports", "name": "Reports"}])[:3]
    features = []
    _icons = ["LayoutDashboard", "BarChart2", "Shield"]
    for idx, ent in enumerate(_feature_entities):
        ent_label = ent.get("name") or ent.get("table", "").replace("_", " ").title()
        features.append({
            "icon": _icons[idx % len(_icons)],
            "title": f"{ent_label} Management",
            "desc": f"Full-featured {ent_label.lower()} tracking, search, and reporting — all in one place.",
        })

    feature_jsx = "\n".join(
        f"""\
            <div className="bg-white p-8 rounded-2xl shadow-sm border border-gray-100 flex flex-col gap-3">
              <{f["icon"]} className="text-brand-600 w-8 h-8" />
              <h3 className="text-xl font-bold text-gray-900">{f["title"]}</h3>
              <p className="text-gray-600 text-sm">{f["desc"]}</p>
            </div>"""
        for f in features
    )

    return f"""\
// Auto-generated by AetherOS p05_frontend — public marketing/landing page
// Route: '/'  (public, no auth required)
// Authenticated users: redirect to '/home' or '/dashboard' after login
import React from 'react'
import {{ Link }} from '@tanstack/react-router'
import {{ ArrowRight, {", ".join(set(f["icon"] for f in features))} }} from 'lucide-react'

export default function LandingPage() {{
  return (
    <div className="min-h-screen bg-white font-sans">
      {{/* Navigation */}}
      <nav className="sticky top-0 z-50 bg-white/90 backdrop-blur border-b border-gray-100 px-6 py-4 flex items-center justify-between">
        <span className="text-xl font-extrabold text-gray-900 tracking-tight">{_display_name}</span>
        <div className="flex items-center gap-4">
          <Link to="/login" className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
            Sign In
          </Link>
          <Link to="/signup" className="bg-brand-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-brand-700 transition-colors">
            Start Free Trial
          </Link>
        </div>
      </nav>

      {{/* Hero */}}
      <section className="relative overflow-hidden bg-gradient-to-br from-brand-900 via-brand-800 to-brand-600 text-white py-28 md:py-40 text-center px-4">
        <div className="absolute inset-0 opacity-[0.06]"
          style={{{{ backgroundImage: 'repeating-linear-gradient(0deg,transparent,transparent 40px,#fff 40px,#fff 41px),repeating-linear-gradient(90deg,transparent,transparent 40px,#fff 40px,#fff 41px)' }}}} />
        <div className="relative max-w-4xl mx-auto">
          <h1 className="text-5xl md:text-7xl font-extrabold leading-none tracking-tight mb-6">
            {_display_name}
          </h1>
          <p className="text-lg md:text-2xl text-gray-200 mb-10 max-w-2xl mx-auto">
            {_tagline}
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link to="/signup"
              className="inline-flex items-center gap-2 bg-white text-brand-800 font-bold px-8 py-4 rounded-xl hover:bg-brand-50 transition-all shadow-xl text-base">
              Start Free Trial <ArrowRight size={{18}} />
            </Link>
            <Link to="/login"
              className="inline-flex items-center gap-2 border border-white/30 text-white font-semibold px-8 py-4 rounded-xl hover:bg-white/10 transition-all text-base">
              Sign In
            </Link>
          </div>
        </div>
        <div className="absolute bottom-0 left-0 right-0">
          <svg viewBox="0 0 1440 40" fill="white" preserveAspectRatio="none" className="w-full h-8">
            <path d="M0,40 C360,0 1080,40 1440,10 L1440,40 Z" />
          </svg>
        </div>
      </section>

      {{/* Features */}}
      <section className="py-24 bg-gray-50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-extrabold text-gray-900">
              Everything you need
            </h2>
            <p className="mt-4 text-lg text-gray-500 max-w-xl mx-auto">
              Built for teams that want to move fast without breaking things.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
{feature_jsx}
          </div>
        </div>
      </section>

      {{/* CTA */}}
      <section className="bg-brand-700 py-20 text-center text-white px-4">
        <h2 className="text-3xl md:text-4xl font-extrabold mb-4">Ready to get started?</h2>
        <p className="text-brand-200 mb-8 max-w-xl mx-auto">
          Join thousands of teams already using {_display_name} to power their workflows.
        </p>
        <Link to="/signup"
          className="inline-flex items-center gap-2 bg-white text-brand-800 font-bold px-8 py-4 rounded-xl hover:bg-brand-50 transition-all shadow-xl text-base">
          Start Free Trial <ArrowRight size={{18}} />
        </Link>
      </section>

      {{/* Footer */}}
      <footer className="bg-gray-900 text-gray-400 py-10 text-center text-sm px-4">
        <p>© {{new Date().getFullYear()}} {_display_name}. All rights reserved.</p>
      </footer>
    </div>
  )
}}
"""


# ── Premium UI component scaffold ────────────────────────────────────────────

def write_ui_components(src_dir: "Path") -> None:  # type: ignore[name-defined]
    """Write the full shadcn/ui-compatible component library to src/components/ui/.

    Called from task_agent.py Phase 2b. Each component file is written only if it
    does not already exist (via _write_with_guard) so incremental runs are idempotent.
    """
    from pathlib import Path as _Path
    from aether_os.phases.p05_frontend.code_writer import (
        generate_ui_button, generate_ui_input, generate_ui_card,
        generate_ui_badge, generate_ui_skeleton, generate_ui_modal,
        generate_ui_select, generate_ui_toast, generate_ui_tooltip,
        generate_ui_table,
    )
    _ui_dir = _Path(src_dir) / "components" / "ui"
    _ui_dir.mkdir(parents=True, exist_ok=True)
    _write_with_guard(_ui_dir / "Button.tsx",  generate_ui_button())
    _write_with_guard(_ui_dir / "Input.tsx",   generate_ui_input())
    _write_with_guard(_ui_dir / "Card.tsx",    generate_ui_card())
    _write_with_guard(_ui_dir / "Badge.tsx",   generate_ui_badge())
    _write_with_guard(_ui_dir / "Skeleton.tsx",generate_ui_skeleton())
    _write_with_guard(_ui_dir / "Modal.tsx",   generate_ui_modal())
    _write_with_guard(_ui_dir / "Select.tsx",  generate_ui_select())
    _write_with_guard(_ui_dir / "Toast.tsx",   generate_ui_toast())
    _write_with_guard(_ui_dir / "Tooltip.tsx", generate_ui_tooltip())
    _write_with_guard(_ui_dir / "Table.tsx",   generate_ui_table())
    logger.info("p05: wrote 10 shadcn/ui-compatible components to %s", _ui_dir)


# ── SSE / Realtime Hook Generation ───────────────────────────────────────────

def _generate_sse_hook(features: List[Any], project_name: str) -> str:
    """Generate src/hooks/useRealtimeStream.ts — EventSource hook for SSE realtime features.

    Generated when realtime_features is non-empty in accumulated_context.
    Consumers: import {{ useRealtimeStream }} from '../hooks/useRealtimeStream'
    """
    _display_name = project_name or "AetherOS App"
    _feature_names = [
        (f if isinstance(f, str) else f.get("name", str(f)))
        for f in (features or [])
    ]
    _feature_comment = ", ".join(_feature_names) if _feature_names else "realtime updates"

    return f"""\
// useRealtimeStream.ts — generated by AetherOS for {_display_name}
// Realtime features wired: {_feature_comment}
//
// Usage:
//   import {{ useRealtimeStream }} from '../hooks/useRealtimeStream'
//   useRealtimeStream((data) => {{ console.log('event', data) }})
//
// The hook opens an SSE connection to /api/realtime/stream with the JWT token
// as a query param (standard for EventSource which cannot set headers).
// On unmount or error the connection is cleanly closed.

import {{ useEffect, useRef }} from 'react'

export function useRealtimeStream(onEvent: (data: unknown) => void): void {{
  // Keep a stable ref to the latest callback so the effect closure never goes stale.
  const callbackRef = useRef<(data: unknown) => void>(onEvent)
  useEffect(() => {{
    callbackRef.current = onEvent
  }})

  useEffect(() => {{
    const token = localStorage.getItem('token') ?? ''
    const url = `/api/realtime/stream${{token ? `?token=${{encodeURIComponent(token)}}` : ''}}`
    const es = new EventSource(url)

    es.onmessage = (e: MessageEvent) => {{
      try {{
        callbackRef.current(JSON.parse(e.data as string))
      }} catch (parseErr) {{
        // Non-JSON frames (e.g. keepalives) are intentionally ignored.
        // Cast to unknown to surface in debug logs if needed.
        void parseErr
      }}
    }}

    es.onerror = () => {{
      // EventSource will attempt to reconnect automatically; close to prevent
      // runaway reconnect loops if the server signals a permanent failure.
      es.close()
    }}

    return () => {{
      es.close()
    }}
  }}, []) // stable — callback ref pattern means no deps needed
}}
"""
