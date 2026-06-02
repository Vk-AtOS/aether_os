"""
Deterministic frontend generators driven by Domain IR.

Produces:
  - Enhanced entity list (with typed fields from IR, not just column names)
  - Dashboard KPI cards from ir.dashboard_metrics (not generic stat boxes)
  - Entity pages with correct form field types (date picker, number, select, etc.)
  - TypeScript types derived from IR Aether types
  - api.ts client per entity

All structural code is generated from IR with no LLM involvement.
LLM is still called for the DomainWidget (copy/UX wording).
"""
from __future__ import annotations

from aether_os.core.domain_ir import AetherType, DomainIR, IREntity, IRField, TS_TYPE_MAP, ZOD_TYPE_MAP


# ---------------------------------------------------------------------------
# Convert DomainIR entities to the p05 entity dict format
# ---------------------------------------------------------------------------

def _field_to_input_type(f: IRField) -> str:
    """Map an IRField to HTML input type for form generation."""
    atype = f.type
    if atype in (AetherType.INTEGER, AetherType.DECIMAL, AetherType.FK):
        return "number"
    if atype == AetherType.BOOLEAN:
        return "checkbox"
    if atype in (AetherType.DATE, AetherType.DATETIME):
        return "date"
    if atype == AetherType.EMAIL:
        return "email"
    if atype == AetherType.URL:
        return "url"
    if atype in (AetherType.TEXT,):
        return "textarea"
    if atype == AetherType.ENUM:
        return "select"
    return "text"


def ir_to_p05_entities(ir: DomainIR) -> list[dict]:
    """
    Convert DomainIR entities to the dict format p05 uses internally.

    Each entity dict:
      table: str
      columns: list[str]
      fields: list[dict]  ← enhanced: includes type, input_type, enum_values, ref_entity
    """
    result = []
    for entity in ir.entities:
        columns = [f.name for f in entity.fields]
        fields = []
        for f in entity.fields:
            fields.append({
                "name": f.name,
                "type": f.type,
                "input_type": _field_to_input_type(f),
                "nullable": f.nullable,
                "unique": f.unique,
                "enum_values": f.enum_values,
                "ref_entity": f.ref_entity,
                "label": f.name.replace("_", " ").title(),
            })
        result.append({
            "table": entity.table,
            "name": entity.name,
            "columns": columns,
            "fields": fields,
            "description": entity.description,
        })
    return result


# ---------------------------------------------------------------------------
# Dashboard KPI cards from IR metrics
# ---------------------------------------------------------------------------

def generate_ir_dashboard_stats(ir: DomainIR) -> str:
    """
    Generate the stats section of Dashboard.tsx from ir.dashboard_metrics.
    Returns a JSX fragment with one StatCard per metric.
    """
    if not ir.dashboard_metrics:
        return ""

    cards = []
    colors = ["blue", "green", "purple", "orange", "red", "teal"]
    icons = {
        "count": "Users",
        "sum": "DollarSign",
        "avg": "TrendingUp",
        "max": "ArrowUp",
        "min": "ArrowDown",
    }

    for i, metric in enumerate(ir.dashboard_metrics):
        color = colors[i % len(colors)]
        icon = icons.get(metric.aggregation, "BarChart2")
        endpoint = f"/{metric.entity.lower()}s" if metric.entity else "/data"
        cards.append(f"""  <StatCard
    title="{metric.label}"
    endpoint="{endpoint}"
    aggregation="{metric.aggregation}"
    queryHint="{metric.query_hint}"
    color="{color}"
    icon="{icon}"
  />""")

    return "\n".join(cards)


def generate_ir_dashboard_tsx(ir: DomainIR, entities: list[dict], project_name: str) -> str:
    """
    Generate a complete Dashboard.tsx with real KPI cards from IR metrics.
    Falls back gracefully if no metrics defined.
    """
    metric_imports = "import { Users, DollarSign, TrendingUp, BarChart2, ArrowUp, ArrowDown } from 'lucide-react';"

    # Build entity table links section
    entity_links = "\n".join([
        f"          <Link to='/{e['table']}' className='block p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors'>"
        f"\n            <div className='font-medium text-gray-900'>{e.get('name', e['table'].title())}</div>"
        f"\n            <div className='text-sm text-gray-500'>{e.get('description', 'Manage ' + e['table'])}</div>"
        f"\n          </Link>"
        for e in entities
    ])

    # Build stat cards from IR metrics or fallback to entity counts
    if ir.dashboard_metrics:
        stat_cards_jsx = "\n".join([
            f"        <StatCard key='{m.name}' title='{m.label}' "
            f"endpoint='/{m.entity.lower()}s' aggregation='{m.aggregation}' "
            f"color='{['blue','green','purple','orange','red','teal'][i % 6]}' />"
            for i, m in enumerate(ir.dashboard_metrics)
        ])
    else:
        cards2 = []
        for e in entities[:6]:
            tbl = e['table']
            ename = e.get('name', tbl.title())
            cards2.append(f"        <StatCard key='{tbl}' title='Total {ename}' endpoint='/{tbl}' aggregation='count' color='blue' />")
        stat_cards_jsx = "\n".join(cards2)

    return f"""import React, {{ useState, useEffect }} from 'react';
import {{ Link }} from 'react-router-dom';
import {{ useQuery }} from '@tanstack/react-query';
import {{ api }} from '../lib/api';
{metric_imports}

interface StatCardProps {{
  title: string;
  endpoint: string;
  aggregation?: string;
  queryHint?: string;
  color?: string;
  icon?: string;
}}

function StatCard({{ title, endpoint, aggregation = 'count', color = 'blue' }}: StatCardProps) {{
  const {{ data, isLoading }} = useQuery({{
    queryKey: ['stat', endpoint],
    queryFn: () => api.get(endpoint + '?limit=1').then(r => r.data),
    staleTime: 30_000,
  }});

  const value = isLoading ? '...' : (data?.total ?? data?.items?.length ?? 0);

  const colors = {{
    blue: 'bg-blue-50 text-blue-700 border-blue-200',
    green: 'bg-green-50 text-green-700 border-green-200',
    purple: 'bg-purple-50 text-purple-700 border-purple-200',
    orange: 'bg-orange-50 text-orange-700 border-orange-200',
    red: 'bg-red-50 text-red-700 border-red-200',
    teal: 'bg-teal-50 text-teal-700 border-teal-200',
  }};

  return (
    <div className={{`rounded-xl border p-5 ${{colors[color] ?? colors.blue}}`}}>
      <div className="text-sm font-medium opacity-70">{{title}}</div>
      <div className="mt-1 text-3xl font-bold">{{value}}</div>
    </div>
  );
}}

export default function Dashboard() {{
  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">{project_name}</h1>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
{stat_cards_jsx}
      </div>

      <div className="mt-6">
        <h2 className="text-lg font-semibold text-gray-700 mb-3">Quick Access</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
{entity_links}
        </div>
      </div>
    </div>
  );
}}
"""


# ---------------------------------------------------------------------------
# TypeScript types from IR
# ---------------------------------------------------------------------------

def generate_ir_types_ts(ir: DomainIR) -> str:
    """Generate types/index.ts with TypeScript interfaces and Zod schemas from IR."""
    lines = [
        "import { z } from 'zod';",
        "",
    ]

    for entity in ir.entities:
        name = entity.name

        # TypeScript interface
        lines.append(f"export interface {name} {{")
        lines.append("  id: number;")
        for f in entity.fields:
            ts_type = TS_TYPE_MAP.get(f.type, "string")
            optional = "?" if f.nullable else ""
            lines.append(f"  {f.name}{optional}: {ts_type};")
        lines.append("  created_at: string;")
        lines.append("  updated_at: string;")
        lines.append("}")
        lines.append("")

        # Zod schema for create/update
        lines.append(f"export const {name}Schema = z.object({{")
        for f in entity.fields:
            zod = ZOD_TYPE_MAP.get(f.type, "z.string()")
            if f.type == AetherType.ENUM and f.enum_values:
                vals = ", ".join(f"'{v}'" for v in f.enum_values)
                zod = f"z.enum([{vals}])"
            if f.nullable:
                zod = f"{zod}.optional()"
            lines.append(f"  {f.name}: {zod},")
        lines.append("});")
        lines.append(f"export type {name}Create = z.infer<typeof {name}Schema>;")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entity page with proper form fields
# ---------------------------------------------------------------------------

def _form_field_jsx(f: IRField, ref_data_var: str | None = None) -> str:
    """Generate a JSX form field for one IRField."""
    label = f.name.replace("_", " ").title()
    input_type = _field_to_input_type(f)
    required = "" if f.nullable else " required"

    if input_type == "textarea":
        return f"""      <div>
        <label className="block text-sm font-medium text-gray-700">{label}</label>
        <textarea name="{f.name}" defaultValue={{item?.{f.name} ?? ''}}{required}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm text-sm" rows={{3}} />
      </div>"""
    if input_type == "checkbox":
        return f"""      <div className="flex items-center gap-2">
        <input type="checkbox" name="{f.name}" defaultChecked={{item?.{f.name} ?? false}} />
        <label className="text-sm font-medium text-gray-700">{label}</label>
      </div>"""
    if input_type == "select" and f.enum_values:
        options = "\n".join(
            f"          <option value='{v}'>{v.replace('_', ' ').title()}</option>"
            for v in f.enum_values
        )
        return f"""      <div>
        <label className="block text-sm font-medium text-gray-700">{label}</label>
        <select name="{f.name}" defaultValue={{item?.{f.name} ?? ''}}{required}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm text-sm">
{options}
        </select>
      </div>"""
    # FK field: render a select populated by a sibling useQuery (data var injected by caller)
    if f.type == AetherType.FK and ref_data_var:
        return f"""      <div>
        <label className="block text-sm font-medium text-gray-700">{label}</label>
        <select name="{f.name}" defaultValue={{String(item?.{f.name} ?? '')}}{required}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm text-sm">
          <option value="">— select —</option>
          {{({ref_data_var}?.items ?? {ref_data_var} ?? []).map((r: any) => (
            <option key={{r.id}} value={{r.id}}>{{r.name ?? r.title ?? r.email ?? String(r.id)}}</option>
          ))}}
        </select>
      </div>"""
    return f"""      <div>
        <label className="block text-sm font-medium text-gray-700">{label}</label>
        <input type="{input_type}" name="{f.name}" defaultValue={{item?.{f.name} ?? ''}}{required}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm text-sm" />
      </div>"""


def generate_ir_entity_page(entity: IREntity) -> str:
    """Generate a complete EntityPage.tsx with typed form fields from IR."""
    name = entity.name
    table = entity.table
    label = name.replace("_", " ")

    # Collect FK refs → unique query hooks
    fk_hook_lines = []
    fk_var_map: dict[str, str] = {}
    seen_refs: set[str] = set()
    for f in entity.fields:
        if f.type == AetherType.FK and f.ref_entity:
            ref = f.ref_entity
            data_var = ref[0].lower() + ref[1:] + "Data"
            fk_var_map[f.name] = data_var
            if ref not in seen_refs:
                seen_refs.add(ref)
                ref_table = "".join(
                    "_" + c.lower() if c.isupper() else c for c in ref
                ).lstrip("_") + "s"
                fk_hook_lines.append(
                    f"  const {{ data: {data_var} }} = useQuery({{ queryKey: ['{ref_table}'], "
                    f"queryFn: () => api.get('/{ref_table}').then(r => r.data) }});"
                )
    fk_hooks = ("\n" + "\n".join(fk_hook_lines)) if fk_hook_lines else ""

    # Columns for the table (all fields)
    col_headers = "\n".join(
        f"              <th className='px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase'>"
        f"{f.name.replace('_', ' ').title()}</th>"
        for f in entity.fields[:6]
    )
    col_cells = "\n".join(
        f"              <td className='px-4 py-2 text-sm text-gray-900'>{{String(row.{f.name} ?? '')}}</td>"
        for f in entity.fields[:6]
    )
    form_fields = "\n".join(_form_field_jsx(f, fk_var_map.get(f.name)) for f in entity.fields)

    return f"""import React, {{ useState }} from 'react';
import {{ useQuery, useMutation, useQueryClient }} from '@tanstack/react-query';
import {{ api }} from '../lib/api';
import type {{ {name} }} from '../types';

export default function {name}Page() {{
  const qc = useQueryClient();
  const [editing, setEditing] = useState<{name} | null | 'new'>(null);

  const {{ data, isLoading }} = useQuery({{
    queryKey: ['{table}'],
    queryFn: () => api.get('/{table}').then(r => r.data),
  }});{fk_hooks}

  const save = useMutation({{
    mutationFn: (payload: Partial<{name}>) =>
      editing === 'new'
        ? api.post('/{table}', payload)
        : api.patch(`/{table}/${{(editing as {name}).id}}`, payload),
    onSuccess: () => {{ qc.invalidateQueries({{ queryKey: ['{table}'] }}); setEditing(null); }},
  }});

  const remove = useMutation({{
    mutationFn: (id: number) => api.delete(`/{table}/${{id}}`),
    onSuccess: () => qc.invalidateQueries({{ queryKey: ['{table}'] }}),
  }});

  const rows: {name}[] = data?.items ?? data ?? [];

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {{
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const payload = Object.fromEntries(fd.entries());
    save.mutate(payload as any);
  }}

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold text-gray-900">{label}</h1>
        <button onClick={{() => setEditing('new')}}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
          + New {label}
        </button>
      </div>

      {{isLoading ? (
        <div className="text-gray-500">Loading…</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
{col_headers}
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {{rows.map(row => (
                <tr key={{row.id}} className="hover:bg-gray-50">
{col_cells}
                  <td className="px-4 py-2 text-sm space-x-2">
                    <button onClick={{() => setEditing(row)}}
                      className="text-blue-600 hover:underline">Edit</button>
                    <button onClick={{() => remove.mutate(row.id)}}
                      className="text-red-600 hover:underline">Delete</button>
                  </td>
                </tr>
              ))}}
            </tbody>
          </table>
        </div>
      )}}

      {{editing && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-lg shadow-xl">
            <h2 className="text-lg font-semibold mb-4">
              {{editing === 'new' ? 'New {label}' : 'Edit {label}'}}
            </h2>
            <form onSubmit={{handleSubmit}} className="space-y-4">
              {{/* typed form fields generated from Domain IR */}}
              {{(() => {{ const item = editing === 'new' ? null : editing; return (
                <>
{form_fields}
                </>
              ); }})()}}
              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={{() => setEditing(null)}}
                  className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
                <button type="submit"
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
                  {{save.isPending ? 'Saving…' : 'Save'}}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}}
    </div>
  );
}}
"""
