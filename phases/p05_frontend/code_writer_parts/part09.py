from __future__ import annotations

from typing import Dict, List, Optional
import json
from aether_os.phases.p05_frontend.scaffold import EXCLUDED_COLS, to_pascal_case, to_type_name, to_label, to_singular, col_to_field_def_type, col_to_field_options, pluralise


def _generate_entity_page(
    ent: dict,
    route_map: Dict[str, str],
    fk_refs: Optional[Dict[str, Dict[str, str]]] = None,
    realtime_features: bool = False,
) -> str:
    """Generate a full CRUD page for one entity.

    fk_refs: maps field_name -> {endpoint, label_key} from domain_ir FK data.
    When None, heuristic pluralisation is used as fallback.
    realtime_features: when True, include useSSE import and live-refresh hook.
    When False (default), SSE import and hook are omitted to avoid firing
    EventSource connections for domains that don't require real-time updates.
    """
    table = ent["table"]
    columns = ent["columns"]
    pascal = to_pascal_case(table)       # component name: "LeadContacts" (page class)
    type_name = to_type_name(table)      # type name: "LeadContact" (singular)
    camel = table[0].lower() + pascal[1:]  # api var: "leadContactsApi"
    label = to_label(table)
    singular = to_singular(label)

    # Visible columns for the table (exclude sensitive/system cols)
    display_cols = [c for c in columns if c.lower() not in EXCLUDED_COLS]

    # Form fields (exclude same set)
    form_cols = [c for c in columns if c.lower() not in EXCLUDED_COLS]

    # Build ColumnDef list
    col_defs: List[str] = []
    for col in display_cols:
        col_label = to_label(col)
        col_defs.append(
            f"  {{\n"
            f"    accessorKey: '{col}' as const,\n"
            f"    header: '{col_label}',\n"
            f"    cell: ({{ getValue }}) => {{\n"
            f"      const v = getValue() as unknown\n"
            f"      if (v === null || v === undefined) return <span className=\"text-muted-foreground\">—</span>\n"
            f"      return <span>{{String(v)}}</span>\n"
            f"    }},\n"
            f"  }},"
        )

    # Build FIELDS array — FK fields get fk-select type with real endpoint + label key
    field_defs: List[str] = []
    fk_config_entries: List[str] = []   # for FK_CONFIG prop (legacy CrudModal support)

    for col in form_cols:
        col_label = to_label(col)
        field_type = col_to_field_def_type(col)
        is_required = col.lower() not in ("description", "notes", "body", "content", "bio")
        options = col_to_field_options(col)
        col_lower = col.lower()

        is_fk = col_lower.endswith("_id") and col_lower != "id"

        if is_fk:
            # Resolve endpoint + label key from domain_ir refs (most accurate)
            # or fall back to corrected heuristic (fixed pluralisation, /api/ prefix)
            if fk_refs and col in fk_refs:
                ref_info = fk_refs[col]
                fk_endpoint = ref_info["endpoint"]
                fk_label = ref_info.get("label_key", "name")
            else:
                related = col[:-3]  # strip "_id": category_id → category
                fk_endpoint = f"/api/{pluralise(related)}"
                fk_label = "name"

            field_defs.append(
                f"  {{ name: '{col}', label: '{col_label}', type: 'fk-select', "
                f"required: {str(is_required).lower()}, "
                f"fkEndpoint: '{fk_endpoint}', fkLabelKey: '{fk_label}' }},"
            )
            fk_config_entries.append(f"  '{col}': '{fk_endpoint}',")

        elif options is not None:
            opts_json = json.dumps(options)
            field_defs.append(
                f"  {{ name: '{col}', label: '{col_label}', type: '{field_type}', "
                f"required: {str(is_required).lower()}, options: {opts_json} }},"
            )
        else:
            field_defs.append(
                f"  {{ name: '{col}', label: '{col_label}', type: '{field_type}', "
                f"required: {str(is_required).lower()} }},"
            )

    col_defs_str = "\n".join(col_defs)
    field_defs_str = "\n".join(field_defs)

    fk_config_str = "\n".join(fk_config_entries)
    fk_config_prop = "\n        fkConfig={FK_CONFIG}" if fk_config_entries else ""
    fk_config_const = (
        f"\nconst FK_CONFIG: Record<string, string> = {{\n{fk_config_str}\n}}\n"
        if fk_config_entries else ""
    )

    # SSE import and hook are only emitted when realtime_features is True.
    # Unconditionally firing EventSource for every entity floods the browser
    # with connection attempts when the domain doesn't expose SSE endpoints.
    _sse_import = "import {{ useSSE }} from '../hooks/useSSE'\n" if realtime_features else ""
    _sse_hook = f"""\
  // Real-time updates via SSE — refetch whenever the server pushes an event for this entity
  const {{ lastEvent: _sseEvent }} = useSSE(`/api/sse/{table}`)
  useEffect(() => {{
    if (_sseEvent) {{
      void refetch()
    }}
  }}, [_sseEvent])
""" if realtime_features else ""

    return f"""\
// Auto-generated by AetherOS p05_frontend
import {{ useState, useEffect }} from 'react'
import {{ useQuery, useMutation, useQueryClient }} from '@tanstack/react-query'
import {{ type ColumnDef }} from '@tanstack/react-table'
import {{ DataTable }} from '../components/DataTable'
import {{ CrudModal, type FieldDef }} from '../components/CrudModal'
import {{ Pagination }} from '../components/Pagination'
import {{ TableSkeleton }} from '../components/Skeleton'
import {{ RoleGuard }} from '../components/RoleGuard'
import {{ {camel}Api, apiErrorMessage }} from '../lib/api'
import {{ type {type_name} }} from '../types'
import {{ useToast }} from '../components/Toaster'
import {{ Plus, Pencil, Trash2 }} from 'lucide-react'
{_sse_import}
const PAGE_SIZE = 20

const FIELDS: FieldDef[] = [
{field_defs_str}
]
{fk_config_const}

export default function {pascal}Page() {{
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<{type_name} | null>(null)
  const [page, setPage] = useState(1)
  const qc = useQueryClient()
  const {{ toast }} = useToast()

  const {{ data: pageData, isLoading, refetch }} = useQuery({{
    queryKey: ['{table}', page],
    queryFn: () => {camel}Api.list(page, PAGE_SIZE),
    placeholderData: (prev) => prev,
  }})

{_sse_hook}

  // Support both paginated {{items, total}} and plain array responses
  const data: {type_name}[] = Array.isArray(pageData)
    ? pageData
    : ((pageData as any)?.items ?? [])
  const total: number = Array.isArray(pageData)
    ? pageData.length
    : ((pageData as any)?.total ?? 0)

  const create = useMutation({{
    mutationFn: {camel}Api.create,
    onSuccess: () => {{
      qc.invalidateQueries({{ queryKey: ['{table}'] }})
      setModalOpen(false)
      toast('{singular} created', 'success')
    }},
    onError: (err: unknown) => {{
      toast(apiErrorMessage(err, 'Failed to create {singular}'), 'error')
    }},
  }})

  const update = useMutation({{
    mutationFn: ({{ id, data }}: {{ id: string | number; data: Partial<{type_name}> }}) =>
      {camel}Api.update(id, data),
    onSuccess: () => {{
      qc.invalidateQueries({{ queryKey: ['{table}'] }})
      setModalOpen(false)
      setEditing(null)
      toast('{singular} updated', 'success')
    }},
    onError: (err: unknown) => {{
      toast(apiErrorMessage(err, 'Failed to update {singular}'), 'error')
    }},
  }})

  const remove = useMutation({{
    mutationFn: {camel}Api.remove,
    onSuccess: () => {{
      qc.invalidateQueries({{ queryKey: ['{table}'] }})
      toast('{singular} deleted', 'success')
    }},
    onError: (err: unknown) => toast(apiErrorMessage(err, 'Failed to delete {singular}'), 'error'),
  }})

  const columns: ColumnDef<{type_name}>[] = [
{col_defs_str}
    {{
      id: 'actions',
      header: '',
      cell: ({{ row }}) => (
        <div className="flex gap-2">
          <button
            onClick={{() => {{ setEditing(row.original); setModalOpen(true) }}}}
            className="p-1.5 text-muted-foreground hover:text-brand-600 rounded"
            title="Edit"
          >
            <Pencil size={{15}} />
          </button>
          <RoleGuard allowedRoles={{['admin', 'owner']}}>
            <button
              onClick={{() => {{
                if (window.confirm('Delete this record?')) {{
                  remove.mutate(row.original.id as string | number)
                }}
              }}}}
              className="p-1.5 text-muted-foreground hover:text-destructive rounded"
              title="Delete"
            >
              <Trash2 size={{15}} />
            </button>
          </RoleGuard>
        </div>
      ),
    }},
  ]

  const handleExport = () => {{
    if (!data.length) return
    // Quote cells with commas, quotes or line breaks, and defuse spreadsheet formulas: a text cell that starts with
    // = + - @ (or tab/CR) is EXECUTED by Excel and Sheets, so it gets a leading apostrophe.
    const escapeCell = (v: unknown): string => {{
      let s = String(v ?? '')
      if (typeof v !== 'number' && /^[=+\\-@\\t\\r]/.test(s)) s = "'" + s
      return /[",\\n\\r]/.test(s) ? `"${{s.replace(/"/g, '""')}}"` : s
    }}
    // the record id is not a table column but it is what identifies a row (and what foreign keys refer to)
    const headers = ['id', ...columns.map(c => String(c.header ?? ''))].map(escapeCell).join(',')
    const rows = data.map(item =>
      [(item as any).id, ...columns.map(c => (item as any)[c.id as string])].map(escapeCell).join(',')
    )
    const csv = '\\ufeff' + [headers, ...rows].join('\\r\\n')
    const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8;' }})
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `{table}_export.csv`
    a.click()
    URL.revokeObjectURL(url)
  }}

  return (
    <div className="p-4 sm:p-8 bg-card min-h-full">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-6 gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{label}</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage your {label.lower()} and track changes</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={{handleExport}}
            className="flex items-center gap-2 px-4 py-2 border border-input text-foreground rounded-lg hover:bg-muted text-sm font-medium transition-all"
          >
            Export CSV
          </button>
          <RoleGuard allowedRoles={{['admin', 'owner', 'manager']}}>
            <button
              onClick={{() => {{ setEditing(null); setModalOpen(true) }}}}
              className="flex items-center gap-2 px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 text-sm font-medium shadow-sm"
            >
              <Plus size={{16}} />
              Add {singular}
            </button>
          </RoleGuard>
        </div>
      </div>

      {{isLoading ? (
        <TableSkeleton rows={{5}} cols={{{len(display_cols) + 1}}} />
      ) : !isLoading && data.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <p className="text-xl font-medium">No {singular}s yet</p>
          <p className="text-sm mt-1">Create your first one to get started</p>
          <RoleGuard allowedRoles={{['admin', 'owner', 'manager']}}>
            <button
              onClick={{() => {{ setEditing(null); setModalOpen(true) }}}}
              className="mt-4 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700"
            >
              + Add {singular}
            </button>
          </RoleGuard>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <DataTable data={{data}} columns={{columns}} isLoading={{false}} />
          </div>
          <Pagination
            total={{total || data.length}}
            page={{page}}
            pageSize={{PAGE_SIZE}}
            onPageChange={{setPage}}
          />
        </>
      )}}

      <CrudModal
        isOpen={{modalOpen}}
        onClose={{() => {{ setModalOpen(false); setEditing(null) }}}}
        onSubmit={{formData => {{
          if (editing) {{
            update.mutate({{ id: editing.id as string | number, data: formData as Partial<{type_name}> }})
          }} else {{
            create.mutate(formData as any)
          }}
        }}}}
        initialValues={{editing ?? undefined}}
        fields={{FIELDS}}
        title={{editing ? `Edit {singular}` : `New {singular}`}}
        isLoading={{create.isPending || update.isPending}}{fk_config_prop}
      />
    </div>
  )
}}
"""


def _generate_product_grid_page(ent: dict, route_map: Dict[str, str]) -> str:
    """Generate a beautiful product card grid page for ecommerce entities."""
    table = ent["table"]
    pascal = to_pascal_case(table)
    label = to_label(table)
    singular = to_singular(label)
    endpoint = route_map.get(table, f"/{table}")

    # Detect price / name / image fields
    cols = [c.lower() for c in ent.get("columns", [])]
    price_field = next((c for c in cols if c in ("price", "unit_price", "amount", "cost", "sale_price")), "price")
    name_field = next((c for c in cols if c in ("name", "title", "product_name")), "name")
    img_field = next((c for c in cols if "image" in c or "photo" in c or "thumbnail" in c), None)
    cat_field = next((c for c in cols if "category" in c or "type" in c or "collection" in c), None)

    img_expr = f"product.{img_field}" if img_field else "null"
    cat_expr = f"product.{cat_field} ?? 'Collection'" if cat_field else "'Collection'"

    return f"""\
// Auto-generated by AetherOS p05_frontend - product card grid
import {{ useState }} from 'react'
import {{ useQuery }} from '@tanstack/react-query'
import {{ apiClient }} from '../lib/api'
import {{ Star, ShoppingCart, Search, SlidersHorizontal }} from 'lucide-react'

const SORT_OPTIONS = [
  {{ value: 'default', label: 'Featured' }},
  {{ value: 'price-asc', label: 'Price: Low to High' }},
  {{ value: 'price-desc', label: 'Price: High to Low' }},
  {{ value: 'name', label: 'Name A–Z' }},
]

function StarRating({{ rating = 4.5 }}: {{ rating?: number }}) {{
  return (
    <div className="flex items-center gap-0.5">
      {{[1,2,3,4,5].map(s => (
        <Star key={{s}} size={{11}}
          className={{s <= Math.round(rating) ? 'fill-warning text-warning-foreground' : 'text-muted-foreground'}} />
      ))}}
    </div>
  )
}}

function ProductCard({{ product, index }}: {{ product: any; index: number }}) {{
  const seed = product.id ?? index + 1
  const rawPrice = product.{price_field} ?? 0
  const price = typeof rawPrice === 'number' ? rawPrice : parseFloat(rawPrice) || 0
  const rating = typeof product.rating === 'number' ? product.rating : null   // no invented ratings
  const imgSrc: string | null = {img_expr} ?? null

  return (
    <div className="group bg-card rounded-2xl overflow-hidden border border-border shadow-sm hover:shadow-xl transition-all duration-300 hover:-translate-y-0.5 flex flex-col">
      <div className="relative aspect-square bg-muted overflow-hidden">
        {{imgSrc
          ? <img src={{imgSrc}} alt={{product.{name_field} ?? '{singular}'}}
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
              loading="lazy"
              onError={{e => {{ (e.target as HTMLImageElement).style.display = 'none' }}}} />
          : <div aria-hidden="true" className="w-full h-full flex items-center justify-center text-5xl font-bold text-muted-foreground">{{String(product.{name_field} ?? '{singular}').charAt(0).toUpperCase()}}</div>}}
      </div>
      <div className="p-4 flex flex-col flex-1">
        <p className="text-[11px] font-bold text-brand-600 uppercase tracking-wider mb-1">{{{cat_expr}}}</p>
        <h3 className="text-sm font-semibold text-foreground leading-snug mb-2 line-clamp-2 flex-1">
          {{product.{name_field} ?? '{singular}'}}
        </h3>
        {{rating !== null && <StarRating rating={{rating}} />}}
        <div className="flex items-center justify-between mt-3">
          <span className="text-lg font-bold text-foreground">
            {{price > 0 ? `$${{price.toFixed(2)}}` : 'Contact us'}}
          </span>
          <button className="flex items-center gap-1.5 bg-brand-600 hover:bg-brand-700 active:scale-95 text-white px-3 py-1.5 rounded-xl text-xs font-bold transition-all">
            <ShoppingCart size={{13}} /> Add
          </button>
        </div>
      </div>
    </div>
  )
}}

export default function {pascal}Page() {{
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('default')
  const [showFilters, setShowFilters] = useState(false)

  const {{ data: raw, isLoading }} = useQuery({{
    queryKey: ['{table}'],
    queryFn: () => apiClient.get('{endpoint}').then(r => r.data),
    staleTime: 60_000,
  }})

  const all: any[] = Array.isArray(raw) ? raw : (raw?.items ?? raw?.data ?? [])
  const filtered = all
    .filter(p => !search || (p.{name_field} ?? '').toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {{
      if (sort === 'price-asc') return (a.{price_field} ?? 0) - (b.{price_field} ?? 0)
      if (sort === 'price-desc') return (b.{price_field} ?? 0) - (a.{price_field} ?? 0)
      if (sort === 'name') return (a.{name_field} ?? '').localeCompare(b.{name_field} ?? '')
      return 0
    }})

  return (
    <div className="min-h-screen bg-card">
      {{/* Page header */}}
      <div className="bg-muted border-b border-border py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h1 className="text-3xl font-extrabold text-foreground">{label}</h1>
          <p className="text-muted-foreground mt-1 text-sm">{{all.length}} items available</p>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {{/* Toolbar */}}
        <div className="flex flex-col sm:flex-row gap-4 mb-8">
          <div className="relative flex-1 max-w-sm">
            <Search size={{16}} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              placeholder="Search {label.lower()}..."
              value={{search}}
              onChange={{e => setSearch(e.target.value)}}
              className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-border bg-card text-sm focus:outline-none focus:ring-2 focus:ring-brand-300 focus:border-brand-400 transition-all"
            />
          </div>
          <div className="flex items-center gap-3 ml-auto">
            <button onClick={{() => setShowFilters(v => !v)}}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border text-sm font-medium text-muted-foreground hover:border-brand-400 hover:text-brand-600 transition-all">
              <SlidersHorizontal size={{15}} /> Filters
            </button>
            <select value={{sort}} onChange={{e => setSort(e.target.value)}}
              className="px-4 py-2.5 rounded-xl border border-border text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand-300 bg-card cursor-pointer">
              {{SORT_OPTIONS.map(o => <option key={{o.value}} value={{o.value}}>{{o.label}}</option>)}}
            </select>
          </div>
        </div>

        {{/* Results count */}}
        {{search && (
          <p className="text-sm text-muted-foreground mb-4">
            {{filtered.length}} result{{filtered.length !== 1 ? 's' : ''}} for "<span className="font-semibold">{{search}}</span>"
          </p>
        )}}

        {{/* Grid */}}
        {{isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
            {{Array.from({{ length: 12 }}).map((_, i) => (
              <div key={{i}} className="rounded-2xl bg-muted animate-pulse" style={{{{ aspectRatio: '3/4' }}}} />
            ))}}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-24">
            <ShoppingCart size={{48}} className="mx-auto mb-4 text-muted-foreground" />
            <h3 className="text-lg font-semibold text-foreground">No {label.lower()} found</h3>
            {{search && <p className="text-sm text-muted-foreground mt-1">Try a different search term</p>}}
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
            {{filtered.map((p, i) => <ProductCard key={{p.id ?? i}} product={{p}} index={{i}} />)}}
          </div>
        )}}
      </div>
    </div>
  )
}}
"""


def _is_product_entity(table: str) -> bool:
    """Return True if this entity should render as a product card grid in storefront."""
    lower = table.lower()
    _product_kws = ("product", "item", "goods", "listing", "sku", "artifact", "merchandise", "commodity")
    return any(k in lower for k in _product_kws)
