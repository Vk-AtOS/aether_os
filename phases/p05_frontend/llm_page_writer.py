"""P05 Frontend — LLM-first entity page writer (Q1).

Generates React/TypeScript entity CRUD pages via a single LLM call, with the
existing template generator kept as fallback in domain_assembler.py.

Public API:
  - write_entity_page_llm(...)  → str | None (cleaned code or None on failure)
  - compute_template_debt(llm_count, template_count) → float in [0.0, 1.0]
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Dict, Optional

from aether_os.phases.p05_frontend.page_concurrency import call_with_backoff

logger = logging.getLogger(__name__)

# Fallback design tokens — design_system module does not yet exist in p05_frontend.
try:
    from aether_os.phases.p05_frontend.design_system import get_design_tokens  # type: ignore
except ImportError:
    def get_design_tokens(domain: str) -> dict:  # noqa: ARG001
        return {
            "accent": "indigo-600",
            "bg_page": "bg-slate-50",
            "radius": "rounded-xl",
            "bg_card": "bg-white",
            "text_primary": "text-slate-900",
            "gradient": "from-indigo-600 to-violet-600",
        }


def compute_template_debt(llm_count: int, template_count: int) -> float:
    """Fraction of pages that fell back to the static template (0.0 = all LLM)."""
    total = llm_count + template_count
    return template_count / total if total > 0 else 1.0


def _filter_routes(route_map: Dict[str, str], table: str) -> Dict[str, str]:
    """Return only routes whose key or value mentions this entity's table name."""
    if not route_map or not table:
        return {}
    needle = table.lower()
    return {
        k: v
        for k, v in route_map.items()
        if needle in str(k).lower() or needle in str(v).lower()
    }


def _relationship_hints(entity: dict, domain_ir: Any) -> str:
    """Extract FK/relationship hints from the DomainIR entity, if available."""
    if not domain_ir or not getattr(domain_ir, "entities", None):
        return ""
    table = entity.get("table", "").lower()
    for ir_ent in domain_ir.entities:
        if getattr(ir_ent, "table", "").lower() != table:
            continue
        hints = []
        for f in getattr(ir_ent, "fields", []):
            ref = getattr(f, "ref_entity", None)
            if ref:
                hints.append(f"{f.name} → {ref}")
        return "Relationships: " + ", ".join(hints) if hints else ""
    return ""


async def write_portal_home_llm(
    domain: str,
    project_name: str,
    raw_input: str,
    design_tokens: dict,
    timeout: float = 120.0,
) -> Optional[str]:
    """Generate a customer portal homepage via one LLM call. Returns None on failure."""
    if os.environ.get("ENVIRONMENT") == "test":
        return None

    from aether_os.core.llm.client import get_llm_client

    tokens = design_tokens or get_design_tokens(domain)

    prompt = (
        f'Generate a public-facing customer portal homepage for a "{domain}" app named "{project_name}".\n\n'
        f"User's original request: {raw_input[:400]}\n\n"
        "The page MUST include:\n"
        "- A hero section with a compelling headline, subtitle, and a primary CTA button\n"
        "- A feature highlights section with 3 cards describing key benefits\n"
        "- A CTA banner at the bottom encouraging sign-up or login\n\n"
        "Hard requirements:\n"
        "- React 18 + TypeScript + Tailwind CSS\n"
        "- Import Link from '@tanstack/react-router' for navigation\n"
        "- Use shadcn/ui Button from '@/components/ui/Button' for the CTA\n"
        "- No API calls — this is a static marketing page\n"
        "- Export: export default function Home()\n"
        f"- Design tokens: accent={tokens.get('accent')}, gradient={tokens.get('gradient')}, "
        f"radius={tokens.get('radius')}, card={tokens.get('bg_card')}\n"
        "- Max 250 lines total\n"
        "- Return ONLY the .tsx code — no markdown fences, no prose.\n"
    )

    client = get_llm_client()
    try:
        result = await asyncio.wait_for(
            client.call(prompt, task_type="code_generation"),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("p05: LLM portal home for %s timed out after %.0fs", project_name, timeout)
        return None
    except Exception as exc:
        logger.warning("p05: LLM portal home for %s failed: %s", project_name, exc)
        return None

    if not result:
        return None

    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", result.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()

    if not ("export default" in cleaned and "function" in cleaned and "return" in cleaned):
        logger.warning("p05: LLM portal home missing required tokens — falling back to template")
        return None

    return cleaned


async def write_dashboard_llm(
    domain: str,
    entities: list,
    project_name: str,
    raw_input: str,
    domain_ir: Any,
    design_tokens: dict,
    timeout: float = 120.0,
) -> Optional[str]:
    """Generate a domain-specific admin dashboard via one LLM call. Returns None on failure."""
    if os.environ.get("ENVIRONMENT") == "test":
        return None

    from aether_os.core.llm.client import get_llm_client

    tokens = design_tokens or get_design_tokens(domain)
    entity_names = [e.get("name") or e.get("table", "") for e in (entities or [])[:8]]

    prompt = (
        f'Generate a React 18 + TypeScript admin dashboard page for the "{project_name}" ({domain}) app.\n\n'
        f"User's original request: {raw_input[:400]}\n\n"
        f"Entities in this app: {', '.join(entity_names) or 'items'}\n\n"
        "The dashboard MUST include:\n"
        "- 4 summary stats cards (e.g. total counts, revenue, active users, pending items) with real entity names\n"
        "- A recent-activity table with 5 mock rows relevant to the domain\n"
        "- 3–4 quick-action buttons that link to entity pages (use TanStack Router <Link>)\n"
        "- Domain-specific KPIs as small metric chips below the stats cards\n\n"
        "Hard requirements:\n"
        "- React 18 + TypeScript + TanStack Router + Tailwind CSS\n"
        "- Import useQuery from '@tanstack/react-query' for any async data\n"
        "- Use shadcn/ui components imported from '@/components/ui/*' (Button, Card)\n"
        "- No hardcoded API calls — stats can be mock values for the dashboard\n"
        "- Include: {/* DOMAIN_WIDGET_SLOT */} comment as a placeholder inside the JSX\n"
        "- Export: export default function Dashboard()\n"
        f"- Design tokens: accent={tokens.get('accent')}, page bg={tokens.get('bg_page')}, "
        f"radius={tokens.get('radius')}, card={tokens.get('bg_card')}, "
        f"text={tokens.get('text_primary')}, gradient={tokens.get('gradient')}\n"
        "- Max 350 lines total\n"
        "- Return ONLY the .tsx code — no markdown fences, no prose.\n"
    )

    client = get_llm_client()
    try:
        result = await asyncio.wait_for(
            client.call(prompt, task_type="code_generation"),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("p05: LLM dashboard for %s timed out after %.0fs", project_name, timeout)
        return None
    except Exception as exc:
        logger.warning("p05: LLM dashboard for %s failed: %s", project_name, exc)
        return None

    if not result:
        return None

    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", result.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()

    if not ("export default" in cleaned and "function" in cleaned and "return" in cleaned):
        logger.warning("p05: LLM dashboard missing required tokens — falling back to template")
        return None

    return cleaned


async def write_entity_page_llm(
    entity: dict,
    route_map: dict,
    project_name: str,
    domain: str,
    raw_input: str,
    domain_ir: Any,
    design_tokens: dict,
    timeout: float = 120.0,
) -> Optional[str]:
    """Generate a full entity CRUD page via one LLM call. Returns None on failure."""
    # ponytail: test env skips the network round-trip; template fallback handles it.
    if os.environ.get("ENVIRONMENT") == "test":
        return None

    from aether_os.core.llm.client import get_llm_client

    table = entity.get("table", "items")
    name = entity.get("name") or table.title().replace("_", "")
    fields = entity.get("fields") or entity.get("columns") or []
    tokens = design_tokens or get_design_tokens(domain)

    # Field list — pass as "name: type" pairs for the LLM.
    field_lines = []
    for f in fields:
        if isinstance(f, dict):
            field_lines.append(f"  - {f.get('name', '?')}: {f.get('type', 'string')}")
        else:
            field_lines.append(f"  - {f}")
    fields_block = "\n".join(field_lines) or "  - id: int\n  - name: string"

    routes = _filter_routes(route_map, table)
    routes_block = "\n".join(f"  {k} → {re.sub(r'^/api(?=/)', '', str(v))}" for k, v in routes.items()) or f"  (default: /{table})"

    rel_hints = _relationship_hints(entity, domain_ir)

    prompt = (
        f'Generate a React 18 + TypeScript entity CRUD page for "{name}" in the "{project_name}" ({domain}) app.\n\n'
        f"User's original request: {raw_input[:400]}\n\n"
        f"Entity: {name} (table: {table})\n"
        f"Fields:\n{fields_block}\n\n"
        f"API routes for this entity:\n{routes_block}\n\n"
        f"{rel_hints}\n\n"
        "Hard requirements:\n"
        "- React 18 + TypeScript + TanStack Router + Tailwind CSS\n"
        "- Import from '@tanstack/react-query' (useQuery, useMutation, useQueryClient)\n"
        "- Call the API ONLY through the shared axios client: import { apiClient } from '@/lib/api' (its baseURL is already /api, "
        "it adds the Bearer token and handles 401). Use paths without /api, e.g. apiClient.get('/patients', { params: { page, page_size } }). "
        "Never use fetch(), never read localStorage, never hard-code '/api' or a token key. List params are page (>=1) and page_size (<=200)\n"
        "- Full CRUD: list table, Create button opening modal, Edit row → modal, Delete with confirm\n"
        "- Use shadcn/ui components imported from '@/components/ui/*' (Button, Card, Input, Table, Modal)\n"
        "- No hardcoded data — all rows come from the API\n"
        "- Export: export default function {name}Page()\n"
        f"- Design tokens: accent={tokens.get('accent')}, page bg={tokens.get('bg_page')}, "
        f"radius={tokens.get('radius')}, card={tokens.get('bg_card')}, "
        f"text={tokens.get('text_primary')}, gradient={tokens.get('gradient')}\n"
        "- Max 350 lines total\n"
        "- Return ONLY the .tsx code — no markdown fences, no prose.\n"
    ).replace("{name}", name)

    client = get_llm_client()
    try:
        result = await asyncio.wait_for(
            call_with_backoff(lambda: client.call(prompt, task_type="code_generation"), f"entity page {name}"),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("p05: LLM entity page for %s timed out after %.0fs", name, timeout)
        return None
    except Exception as exc:
        logger.warning("p05: LLM entity page for %s failed: %s", name, exc)
        return None

    if not result:
        return None

    # Strip markdown fences
    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", result.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()

    if not ("export default" in cleaned and "function" in cleaned and "return" in cleaned):
        logger.warning("p05: LLM entity page for %s missing required tokens — falling back", name)
        return None

    return cleaned
