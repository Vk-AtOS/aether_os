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

from aether_os.phases.p05_frontend.api_contract import enforce_list_contract
from aether_os.phases.p05_frontend.page_concurrency import call_with_backoff
from aether_os.phases.p05_frontend.ui_catalog import ui_catalog

logger = logging.getLogger(__name__)

from aether_os.phases.p05_frontend.design_system import get_design_tokens
from aether_os.phases.p05_frontend.theme_tokens import page_rules_block

# Every page prompt says this instead of a palette (KAN-243): colors are the run's CSS-variable tokens.
_COLORS = ("- Colors ONLY through the theme's semantic classes: bg-background, bg-card, text-foreground, "
           "text-muted-foreground, bg-primary with text-primary-foreground, bg-accent, border-border, ring-ring, "
           "bg-destructive. No hex values, no palette classes such as bg-blue-500, no gradients\n")


def _rules(tokens: dict) -> str:
    """The run's DESIGN + SECURITY RULES (theme_tokens.py), placed at the end of every page prompt."""
    return "\n" + ((tokens or {}).get("rules") or page_rules_block()) + "\n\n"


async def _recorded(checked: Any, key: str, args: tuple, kwargs: dict) -> Optional[str]:
    """Run a *_checked writer; when it refuses, store its reason under `key` in the caller's `fallbacks` dict (the
    per-page fallback reasons that frontend_meta.json records, KAN-252)."""
    fallbacks = kwargs.pop("fallbacks", None)
    code, reason = await checked(*args, **kwargs)
    if code is None and fallbacks is not None:
        fallbacks[key] = reason
    return code


def compute_template_debt(llm_count: int, template_count: int) -> float:
    """Fraction of pages that fell back to the static template (0.0 = all LLM)."""
    total = llm_count + template_count
    return template_count / total if total > 0 else 1.0


def _camel(table: str) -> str:
    """lib/api.ts helper prefix for a table: lead_contacts -> leadContacts (the *Api object is `<this>Api`)."""
    head, *rest = table.split("_")
    return head[:1].lower() + head[1:] + "".join(w[:1].upper() + w[1:] for w in rest)


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


async def write_portal_home_checked(
    domain: str,
    project_name: str,
    raw_input: str,
    design_tokens: dict,
    timeout: float = 120.0,
) -> tuple[Optional[str], str]:
    """Generate a customer portal homepage via one LLM call. (code, "") when usable, (None, reason) otherwise (the reason goes to frontend_meta.json)."""
    if os.environ.get("ENVIRONMENT") == "test":
        return None, "test_env"

    from aether_os.core.llm.client import get_llm_client

    tokens = design_tokens or get_design_tokens(domain)

    prompt = (
        f'Generate a public-facing customer portal homepage for a "{domain}" app named "{project_name}".\n\n'
        f"User's original request: {raw_input[:400]}\n\n"
        "The page MUST include:\n"
        "- A hero section with a compelling headline, subtitle, and a primary CTA button\n"
        "- A section on what this product does for its users, in its own words and records (not a generic 3-card grid)\n"
        "- A CTA banner at the bottom encouraging sign-up or login\n\n"
        "Hard requirements:\n"
        "- React 18 + TypeScript + Tailwind CSS\n"
        "- Import Link from '@tanstack/react-router' for navigation\n"
        "- Use shadcn/ui Button from '@/components/ui/Button' for the CTA\n"
        "- No API calls — this is a static marketing page\n"
        "- Export: export default function Home()\n"
        + _COLORS
        + "- Max 250 lines total\n"
        "- Return ONLY the .tsx code — no markdown fences, no prose.\n"
        + _rules(tokens)
    )

    client = get_llm_client()
    try:
        result = await asyncio.wait_for(
            client.call(prompt, task_type="code_generation"),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("p05: LLM portal home for %s timed out after %.0fs", project_name, timeout)
        return None, f"timeout_{timeout:.0f}s"
    except Exception as exc:
        logger.warning("p05: LLM portal home for %s failed: %s", project_name, exc)
        return None, f"llm_error: {str(exc)[:120]}"

    if not result:
        return None, "empty_reply"

    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", result.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()

    if not ("export default" in cleaned and "function" in cleaned and "return" in cleaned):
        logger.warning("p05: LLM portal home missing required tokens — falling back to template")
        return None, "missing_export_default_or_return"

    return cleaned, ""


async def write_portal_home_llm(*args: Any, **kwargs: Any) -> Optional[str]:
    """The portal home code, or None when the template must be used (why: kwarg `fallbacks`, see _recorded)."""
    return await _recorded(write_portal_home_checked, "pages/customer/Home.tsx", args, kwargs)


async def write_dashboard_checked(
    domain: str,
    entities: list,
    project_name: str,
    raw_input: str,
    domain_ir: Any,
    design_tokens: dict,
    timeout: float = 120.0,
) -> tuple[Optional[str], str]:
    """Generate a domain-specific admin dashboard via one LLM call. (code, "") when usable, (None, reason) otherwise (the reason goes to frontend_meta.json)."""
    if os.environ.get("ENVIRONMENT") == "test":
        return None, "test_env"

    from aether_os.core.llm.client import get_llm_client

    tokens = design_tokens or get_design_tokens(domain)
    entity_names = [e.get("name") or e.get("table", "") for e in (entities or [])[:8]]

    prompt = (
        f'Generate a React 18 + TypeScript admin dashboard page for the "{project_name}" ({domain}) app.\n\n'
        f"User's original request: {raw_input[:400]}\n\n"
        f"Entities in this app: {', '.join(entity_names) or 'items'}\n\n"
        "The dashboard MUST include:\n"
        "- Summary stats cards, one per entity (total) plus overdue where it applies, with real entity names\n"
        "- 3–4 quick-action buttons that link to entity pages (use TanStack Router <Link>)\n\n"
        "Hard requirements:\n"
        "- React 18 + TypeScript + TanStack Router + Tailwind CSS\n"
        "- Import useQuery from '@tanstack/react-query' for any async data\n"
        "- Use shadcn/ui components imported from '@/components/ui/*' (Button, Card)\n"
        "- Every number comes from the backend: import { stats } from '@/lib/api'; useQuery({ queryKey: ['stats'], queryFn: stats }) "
        "returns keys total_<table> and overdue_<table>. NEVER write a numeric literal, mock row or invented name as data; "
        "show a skeleton while loading and an empty state when no data. Pages with hard-coded counts are rejected\n"
        "- Include: {/* DOMAIN_WIDGET_SLOT */} comment as a placeholder inside the JSX\n"
        "- Export: export default function Dashboard()\n"
        + _COLORS +
        "- Max 350 lines total\n"
        "- Return ONLY the .tsx code — no markdown fences, no prose.\n"
        + _rules(tokens)
    )

    client = get_llm_client()
    try:
        result = await asyncio.wait_for(
            client.call(prompt, task_type="code_generation"),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("p05: LLM dashboard for %s timed out after %.0fs", project_name, timeout)
        return None, f"timeout_{timeout:.0f}s"
    except Exception as exc:
        logger.warning("p05: LLM dashboard for %s failed: %s", project_name, exc)
        return None, f"llm_error: {str(exc)[:120]}"

    if not result:
        return None, "empty_reply"

    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", result.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()

    if not ("export default" in cleaned and "function" in cleaned and "return" in cleaned):
        logger.warning("p05: LLM dashboard missing required tokens — falling back to template")
        return None, "missing_export_default_or_return"

    return cleaned, ""


async def write_dashboard_llm(*args: Any, **kwargs: Any) -> Optional[str]:
    """The dashboard code, or None when the template must be used (why: kwarg `fallbacks`, see _recorded)."""
    return await _recorded(write_dashboard_checked, "pages/Dashboard.tsx", args, kwargs)


_FORM_ATTR = re.compile(r"""\bform=["']([\w-]+)["']""")


def page_defects(code: str) -> list:
    """Contract defects that make a model-written page silently useless; the template page is used instead.

    - a button bound with form="x" to a form that has no id="x" does nothing when clicked (run 33: Users "Create");
    - a page must never send or show a stored password hash: the API takes `password` and hashes it (run 29/33)."""
    out = []
    for form_id in sorted(set(_FORM_ATTR.findall(code))):
        if not re.search(rf"""\bid=["']{re.escape(form_id)}["']""", code):
            out.append(f'button bound to form "{form_id}", which does not exist')
    if "password_hash" in code:
        out.append("handles password_hash (send `password`; the API hashes it)")
    return out


def mutations_without_error_handler(code: str) -> int:
    """How many useMutation({...}) calls have no onError. Run 23's page had three: a rejected save (422) left the
    dialog open with no message (KAN-242)."""
    missing = 0
    for m in re.finditer(r"useMutation\s*(?:<[^>]*>)?\s*\(", code):
        depth, i = 1, m.end()
        while i < len(code) and depth:
            depth += {"(": 1, ")": -1}.get(code[i], 0)
            i += 1
        if "onError" not in code[m.end():i]:
            missing += 1
    return missing


async def write_entity_page_checked(
    entity: dict,
    route_map: dict,
    project_name: str,
    domain: str,
    raw_input: str,
    domain_ir: Any,
    design_tokens: dict,
    timeout: float = 120.0,
) -> tuple[Optional[str], str]:
    """One LLM call for a full entity CRUD page: (code, "") when accepted, (None, reason) when the template page
    must be used. The reason is recorded in frontend_meta.json (KAN-252: 0.67-0.75 template debt could not be
    diagnosed because every rejection looked the same)."""
    # ponytail: test env skips the network round-trip; template fallback handles it.
    if os.environ.get("ENVIRONMENT") == "test":
        return None, "test_env"

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
        "- For this entity's CRUD calls, import the typed helper from '@/lib/api' (e.g. import { {camel}Api } from '@/lib/api'): "
        "{camel}Api.list(page, pageSize) resolves to { items: T[], total, page, page_size, limit } (rows are `.items`, there is NO `.data` field), "
        "plus get(id), create(data), update(id, data), remove(id). Do NOT declare your own list/response types for CRUD resources "
        "(no ListResponse / PaginatedResponse interface) and never write `data.data` or `data?.data.map`. For related entities use "
        "their helpers too (e.g. usersApi.list(1, 200)); import entity types from '@/types'\n"
        "- Full CRUD: list table, Create button opening modal, Edit row → modal, Delete with confirm\n"
        "- Every useMutation has an onError that shows the server's reason: import { apiErrorMessage } from '@/lib/api' and show "
        "apiErrorMessage(err, 'Could not save') in the open dialog (role=\"alert\") or a toast. A rejected save keeps the dialog "
        "open with the user's input; never swallow an error\n"
        f"- Use only these shadcn/ui components, each imported from its file '@/components/ui/<File>' (file: exports): {ui_catalog()}. "
        "Nothing else exists there; anything more you need, write inline\n"
        "- No hardcoded data — all rows come from the API\n"
        "- Export: export default function {name}Page()\n"
        + _COLORS +
        "- Max 350 lines total\n"
        "- Return ONLY the .tsx code — no markdown fences, no prose.\n"
        + _rules(tokens)
    ).replace("{name}", name).replace("{camel}", _camel(table))

    client = get_llm_client()
    try:
        result = await asyncio.wait_for(
            call_with_backoff(lambda: client.call(prompt, task_type="code_generation"), f"entity page {name}"),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("p05: LLM entity page for %s timed out after %.0fs", name, timeout)
        return None, f"timeout_{timeout:.0f}s"
    except Exception as exc:
        logger.warning("p05: LLM entity page for %s failed: %s", name, exc)
        return None, f"llm_error: {str(exc)[:120]}"

    if not result:
        return None, "empty_reply"

    # Strip markdown fences
    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", result.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()

    if not ("export default" in cleaned and "function" in cleaned and "return" in cleaned):
        logger.warning("p05: LLM entity page for %s missing required tokens — falling back", name)
        return None, "missing_export_default_or_return"

    defects = page_defects(cleaned)
    if defects:
        logger.warning("p05: LLM entity page for %s refused (%s) — falling back", name, "; ".join(defects))
        return None, "defect: " + "; ".join(defects)

    silent = mutations_without_error_handler(cleaned)
    if silent:
        logger.warning("p05: LLM entity page for %s has %d mutation(s) without onError — falling back", name, silent)
        return None, f"{silent}_mutation_without_onError"

    return enforce_list_contract(cleaned, f"{name}Page"), ""


async def write_entity_page_llm(*args: Any, **kwargs: Any) -> Optional[str]:
    """The page code, or None when the template must be used (why: kwarg `fallbacks`, see _recorded)."""
    ent = kwargs.get("entity") or {}
    key = f"pages/{ent.get('name') or str(ent.get('table', 'items')).title().replace('_', '')}Page.tsx"
    return await _recorded(write_entity_page_checked, key, args, kwargs)
