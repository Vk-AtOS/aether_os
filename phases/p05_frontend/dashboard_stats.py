"""Dashboard stat cards and the DomainWidget fallback, built from the app's own entities and GET /api/stats (KAN-225).

Production run 20 shipped a dashboard whose cards were literals (12 projects, 87 tasks, 14 overdue) behind a fake
fetch, and a "Shelf Status" library widget for a SaaS task tracker. Here the cards and the fallback widget are a pure
function of the entity list, every number comes from /stats via the shared api client, and a post-check refuses any
model-written dashboard that hard-codes counts.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from aether_os.core.codegen.stats_fields import overdue_fields, stage_slug

logger = logging.getLogger(__name__)

MAX_CARDS = 8
_COLORS = ("blue", "green", "purple", "orange", "red", "teal")
SLOT = "      {/* DOMAIN_WIDGET_SLOT */}"


def _label(name: str) -> str:
    return name.replace("_", " ").title()


def _is_user(e: Dict[str, Any]) -> bool:
    return e.get("table") == "users" or e.get("name") == "User"      # the stats router has no users count


def _pairs(e: Dict[str, Any]) -> List[Tuple[str, Any]]:
    fields = e.get("fields") or []
    if fields and isinstance(fields[0], dict):
        return [(f.get("name", ""), f.get("type")) for f in fields]
    return [(c, None) for c in (e.get("columns") or [])]


def stat_cards(entities: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """(label, /stats key) for each domain entity's total plus an overdue card where the entity can be overdue."""
    cards: List[Tuple[str, str]] = []
    for e in (x for x in entities if not _is_user(x) and x.get("table")):
        cards.append((_label(e["table"]), f"total_{e['table']}"))
        if overdue_fields(_pairs(e)):
            cards.append((f"Overdue {_label(e['table'])}", f"overdue_{e['table']}"))
    return cards[:MAX_CARDS]


def stats_dashboard_tsx(entities: List[Dict[str, Any]], project_name: str, route_prefix: str = "") -> str:
    """The admin Dashboard: stat cards from /stats with loading, error and empty states, plus links and the widget slot.

    route_prefix is "/admin" in the dual-portal layout, where every admin route lives under it (a link to "/projects"
    is not a registered route there: TS2322 in every dual-portal build)."""
    cards = stat_cards(entities)
    card_rows = ",\n".join(f"  {{ label: {l!r}, key: {k!r}, tone: {_COLORS[i % 6]!r} }}" for i, (l, k) in enumerate(cards))
    links = "\n".join(
        f"          <Link to='{route_prefix}/{e['table'].replace('_', '-')}' className='flex items-center justify-between p-4 bg-card rounded-xl "
        f"border border-border hover:shadow-sm transition-all'><span className='font-semibold text-foreground'>"
        f"{_label(e['table'])}</span><span aria-hidden>→</span></Link>"
        for e in entities if not _is_user(e) and e.get("table"))
    title = project_name.replace("\\", " ").replace("'", " ").replace("{", " ").replace("}", " ").replace("<", " ").strip() or "Dashboard"
    return f"""import React from 'react';
import {{ useQuery }} from '@tanstack/react-query';
import {{ stats as fetchStats }} from '../lib/api';
import {{ Link }} from '@tanstack/react-router';

// Every number below comes from GET /api/stats; nothing on this page is a literal count.
const CARDS = [
{card_rows}
];
const TONES: Record<string, string> = {{
  blue: 'bg-accent text-primary border-border', green: 'bg-success-soft text-success border-success',
  purple: 'bg-accent text-primary border-border', orange: 'bg-warning-soft text-warning-foreground border-warning',
  red: 'bg-destructive-soft text-destructive border-destructive', teal: 'bg-success-soft text-success border-success',
}};

export default function Dashboard() {{
  const {{ data, isLoading, isError }} = useQuery({{ queryKey: ['stats'], queryFn: fetchStats, staleTime: 30_000 }});
  const empty = !isLoading && !isError && (!data || CARDS.every(c => typeof data[c.key] !== 'number'));

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-extrabold text-foreground">{title}</h1>
        <p className="text-muted-foreground mt-1 text-sm">Live totals from the API.</p>
      </div>

      {{isError && <p role="alert" className="text-sm text-destructive">The numbers could not be loaded. Try again shortly.</p>}}
      {{empty && <p className="text-sm text-muted-foreground">No data yet. Add records and the totals appear here.</p>}}

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {{CARDS.map(c => (
          <div key={{c.key}} className={{`rounded-2xl border p-6 shadow-sm ${{TONES[c.tone]}}`}}>
            <div className="text-xs font-bold uppercase tracking-widest opacity-60 mb-2">{{c.label}}</div>
            {{isLoading
              ? <div className="h-9 w-16 animate-pulse rounded bg-black/10" />
              : <div className="text-4xl font-extrabold">{{typeof data?.[c.key] === 'number' ? data[c.key] : '–'}}</div>}}
          </div>
        ))}}
      </div>

{SLOT}

      <div>
        <h2 className="text-base font-bold text-foreground uppercase tracking-wide mb-4">Quick Access</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
{links}
        </div>
      </div>
    </div>
  );
}}
"""


# --- post-check -------------------------------------------------------------------------------------------------

_LITERAL_COUNT = re.compile(
    r"""\b(?:total|overdue|active|count|completed|pending)\w*\s*:\s*\d"""      # totalTasks: 87
    r"""|\bvalue\s*:\s*['"]?\d[\d.,]*%?['"]?\s*[,}]"""                       # { label: 'Rate', value: '78%' }
    r"""|setTimeout\(\s*\w*resolve""",                                       # fake fetch with a delay
    re.I,
)
_CALLS_STATS = re.compile(r"""\bstats\s*(?:as\b|[,}])|\bstatsApi\b|\bstats\(\)|['"`]/stats['"`]""")


_STATS_KEY = re.compile(r"""\b((?:total|overdue)_[A-Za-z]\w*)\b""")


def served_keys(entities: List[Dict[str, Any]]) -> set:
    """The total_/overdue_ keys GET /stats returns for these entities (same rule as the p04a stats router)."""
    keys = set()
    for e in (x for x in entities if not _is_user(x) and x.get("table")):
        keys.add(f"total_{e['table']}")
        if overdue_fields(_pairs(e)):
            keys.add(f"overdue_{e['table']}")
    return keys


def hardcoded_counts_reason(code: str, entities: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    """Why a dashboard may not ship (hard-coded counts, no /stats call, or /stats keys the backend does not serve),
    None when it is fine."""
    if not _CALLS_STATS.search(code):
        return "does not read /stats"
    m = _LITERAL_COUNT.search(code)
    if m:
        return f"hard-coded count literal {m.group(0).strip()!r}"
    if entities:
        # Production run 21: the model read total_User / total_Project (entity names); /stats serves total_projects
        # (table names), so every card showed a dash.
        unknown = sorted({k for k in _STATS_KEY.findall(code)} - served_keys(entities))
        if unknown:
            return f"reads /stats keys the backend does not serve: {', '.join(unknown[:4])}"
    return None


def ensure_real_stats(code: str, entities: List[Dict[str, Any]], project_name: str,
                      route_prefix: str = "") -> Tuple[str, bool]:
    """(dashboard, replaced): the model's dashboard when it passes the post-check, else the deterministic template."""
    reason = hardcoded_counts_reason(code, entities)
    if reason is None:
        return code, False
    logger.warning("p05: Dashboard.tsx refused (%s); using the /stats template", reason)
    return stats_dashboard_tsx(entities, project_name, route_prefix), True


# --- DomainWidget fallback --------------------------------------------------------------------------------------

_MOCK_DATA = re.compile(r"\bconst\s+(?:mock|sample|dummy|fake)\w*\s*=", re.I)


# A JSX component tag: "<Name" not directly after an identifier (that would be a generic such as useQuery<Stats>).
_JSX_COMPONENT = re.compile(r"(?<![\w.$])<([A-Z]\w*)")
_COMMENTS = re.compile(r"/\*.*?\*/|(?<![:\\])//[^\n]*", re.S)


def undeclared_components(code: str) -> List[str]:
    """JSX components the code renders but never imports or declares: each one throws a ReferenceError at render.

    Conservative: a name counts as declared when it appears anywhere outside a tag (import, const, parameter,
    destructuring alias), so only a name that exists solely as <Name ...> / </Name> is reported."""
    code = _COMMENTS.sub("", code)
    missing = set()
    for name in set(_JSX_COMPONENT.findall(code)):
        if not re.search(rf"(?<![<\w/.$]){name}\b", code):
            missing.add(name)
    return sorted(missing)


def widget_reason(code: str) -> Optional[str]:
    """Why a model-written DomainWidget may not ship, None when it is fine.

    Refused: invented data, or a component used without an import. Run 22 shipped a widget that rendered
    <ClipboardList> without importing it; vite does not type-check, so the build passed and the admin landing
    page crashed into the error boundary right after sign-in."""
    m = _MOCK_DATA.search(code)
    if m:
        return f"invented data ({m.group(0).strip()})"
    missing = undeclared_components(code)
    return f"renders undeclared components ({', '.join(missing[:5])})" if missing else None


def _widget_head(imports: str) -> str:
    return ("import React from 'react'\nimport { useQuery } from '@tanstack/react-query'\n"
            "import { stats as fetchStats } from '../lib/api'\n" + imports)


def fallback_widget(domain: str, entities: List[Dict[str, Any]]) -> Tuple[str, str]:
    """(kind, tsx) chosen from this app's entities, never from another domain's canned widget.

    kind "pipeline": an entity with a status/stage enum, one tile per value from /stats stage_<slug> (+ overdue).
    kind "overview": a count per entity from /stats. Domain only words the heading; no data is invented."""
    ents = [e for e in entities if not _is_user(e) and e.get("table")]
    heading = f"{_label(domain or 'app')} overview"
    for e in ents:
        enum_field = next((f for f in (e.get("fields") or []) if isinstance(f, dict) and f.get("name") in ("status", "stage")
                           and f.get("enum_values")), None)
        if enum_field:
            tiles = ",\n".join(f"  {{ label: {str(v)!r}, key: 'stage_{stage_slug(v)}' }}" for v in enum_field["enum_values"][:6])
            return "pipeline", _widget_head("") + f"""
const TILES = [
{tiles}
]

export default function DomainWidget() {{
  const {{ data, isLoading }} = useQuery({{ queryKey: ['stats'], queryFn: fetchStats, staleTime: 30_000 }})
  return (
    <section className="p-6 bg-card rounded-2xl border" aria-label="{_label(e['table'])} by {enum_field['name']}">
      <h2 className="text-lg font-bold mb-4">{_label(e['table'])} by {enum_field['name']}</h2>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {{TILES.map(t => (
          <div key={{t.key}} className="rounded-xl border p-4">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">{{t.label}}</div>
            {{isLoading ? <div className="h-7 w-10 animate-pulse rounded bg-muted" /> : <div className="text-2xl font-bold">{{typeof data?.[t.key] === 'number' ? data[t.key] : '–'}}</div>}}
          </div>
        ))}}
      </div>
    </section>
  )
}}
"""
    rows = ",\n".join(f"  {{ label: {_label(e['table'])!r}, key: 'total_{e['table']}' }}" for e in ents[:6])
    return "overview", _widget_head("") + f"""
const ROWS = [
{rows}
]

export default function DomainWidget() {{
  const {{ data, isLoading }} = useQuery({{ queryKey: ['stats'], queryFn: fetchStats, staleTime: 30_000 }})
  return (
    <section className="p-6 bg-card rounded-2xl border" aria-label="{heading}">
      <h2 className="text-lg font-bold mb-4">{heading}</h2>
      {{ROWS.length === 0 ? <p className="text-sm text-muted-foreground">No records yet.</p> : (
        <ul className="divide-y">
          {{ROWS.map(r => (
            <li key={{r.key}} className="flex items-center justify-between py-2 text-sm">
              <span>{{r.label}}</span>
              {{isLoading ? <span className="h-4 w-8 animate-pulse rounded bg-muted" /> : <span className="font-semibold">{{typeof data?.[r.key] === 'number' ? data[r.key] : '–'}}</span>}}
            </li>
          ))}}
        </ul>
      )}}
    </section>
  )
}}
"""
