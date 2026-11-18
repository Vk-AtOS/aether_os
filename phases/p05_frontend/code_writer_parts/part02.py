from __future__ import annotations

from typing import Dict, List, Optional
from aether_os.phases.p05_frontend.scaffold import EXCLUDED_COLS, to_pascal_case, to_type_name, col_to_ts_type


def _generate_nginx_conf(config: Optional[dict] = None) -> str:
    # PIPELINE-044: use configurable container name and port instead of hardcoding
    _cfg = config or {}
    container_name = _cfg.get("container_name", "app")
    app_port = _cfg.get("app_port", 8000)
    return f"""\
server {{
  listen 80;
  root /usr/share/nginx/html;
  index index.html;

  gzip on;
  gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
  gzip_min_length 1024;

  # Security headers
  add_header X-Frame-Options "SAMEORIGIN" always;
  add_header X-Content-Type-Options "nosniff" always;
  add_header Referrer-Policy "strict-origin-when-cross-origin" always;

  # Proxy /api/* to the backend unchanged: the generated backend serves every route under /api.
  # (A trailing "/" on proxy_pass would strip the prefix and every call would 404.)
  # Backend service is named '{container_name}' in docker-compose.yml
  location /api/ {{
    proxy_pass http://{container_name}:{app_port};
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 60s;
    proxy_connect_timeout 10s;
  }}

  # Fingerprinted static assets — immutable long cache (safe because filenames include content hash)
  location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot|map)$ {{
    expires 1y;
    add_header Cache-Control "public, immutable";
    try_files $uri =404;
  }}

  # index.html — must never be cached so users always get the latest app version
  location = /index.html {{
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Pragma "no-cache";
    add_header Expires "0";
    try_files $uri =404;
  }}

  # SPA fallback — React Router handles client-side routes
  location / {{
    try_files $uri $uri/ /index.html;
  }}
}}
"""


def _generate_dockerfile() -> str:
    return """\
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
# Use npm ci if lockfile exists, otherwise npm install (for first-time builds)
RUN [ -f package-lock.json ] && npm ci || npm install
COPY . .
# Accept backend URL as build arg so API calls are baked into the bundle.
# Default is empty — nginx /api/ proxy handles routing on any server.
# Override: docker build --build-arg VITE_API_URL=http://your-server:8000 .
ARG VITE_API_URL=
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -qO- http://localhost:80 || exit 1
"""


def _generate_env_example() -> str:
    return (
        "# Frontend environment variables — copy to .env\n\n"
        "# VITE_API_URL — backend API base URL.\n"
        "#\n"
        "# Leave this UNSET (commented out) in most cases:\n"
        "#   - Local dev (npm run dev): Vite proxy rewrites /api/* → http://localhost:8000\n"
        "#   - Docker Compose: nginx rewrites /api/* → backend container automatically\n"
        "#\n"
        "# Set this ONLY when deploying the frontend separately from the backend\n"
        "# (e.g. Vercel/Netlify frontend + separate backend server):\n"
        "# VITE_API_URL=https://api.yourdomain.com\n"
    )


def _generate_headers_file() -> str:
    """Generate public/_headers for Cloudflare Pages / Netlify CDN deployments.

    Controls caching and security headers at the CDN edge — no server config needed.
    index.html is never cached so users always get the latest app version.
    Fingerprinted /assets/* are immutably cached for 1 year.
    """
    return """\
# CDN edge headers — Cloudflare Pages / Netlify compatible
# Vite builds fingerprinted asset filenames (e.g. index-BxK3p9aZ.js) so
# /assets/* can be cached indefinitely without risk of stale bundles.

/index.html
  Cache-Control: no-cache, no-store, must-revalidate
  X-Frame-Options: SAMEORIGIN
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin

/assets/*
  Cache-Control: public, max-age=31536000, immutable

/*
  X-Frame-Options: SAMEORIGIN
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
"""


THEME_CSS: dict = {
    "glassmorphism": """\
/* Glassmorphism theme */
body { background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #db2777 100%) fixed; min-height: 100vh; }
.glass-card { background: rgba(255,255,255,0.12); backdrop-filter: blur(16px) saturate(180%); -webkit-backdrop-filter: blur(16px) saturate(180%); border: 1px solid rgba(255,255,255,0.25); box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
""",
    "neomorphism": """\
/* Neomorphism theme */
body { background: #e0e5ec; color: #4b5563; }
.neo-card { background: #e0e5ec; border-radius: 12px; box-shadow: 6px 6px 12px #a3b1c6, -6px -6px 12px #ffffff; border: none; }
.neo-inset { box-shadow: inset 4px 4px 8px #a3b1c6, inset -4px -4px 8px #ffffff; }
.neo-btn { background: #e0e5ec; border-radius: 8px; box-shadow: 4px 4px 8px #a3b1c6, -4px -4px 8px #ffffff; border: none; }
.neo-btn:active { box-shadow: inset 2px 2px 5px #a3b1c6, inset -2px -2px 5px #ffffff; }
""",
    "material": """\
/* Material Design 3 theme */
body { background: #fffbfe; color: #1c1b1f; font-family: 'Roboto', 'Google Sans', sans-serif; }
.md-surface { background: #f3edf7; border-radius: 12px; }
.md-surface-variant { background: #e7e0ec; }
.md-primary { background: #6750a4; color: #ffffff; border-radius: 100px; }
.md-secondary { background: #625b71; color: #ffffff; border-radius: 100px; }
.md-elevation-1 { box-shadow: 0 1px 2px rgba(0,0,0,0.3), 0 1px 3px 1px rgba(0,0,0,0.15); }
.md-elevation-2 { box-shadow: 0 1px 2px rgba(0,0,0,0.3), 0 2px 6px 2px rgba(0,0,0,0.15); }
.md-ripple { position: relative; overflow: hidden; }
""",
    "flat": """\
/* Flat / Minimal theme */
body { background: #ffffff; color: #111827; }
* { box-shadow: none !important; }
.flat-card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 0; }
.flat-btn { border-radius: 0; border: 2px solid #111827; background: #111827; color: #ffffff; }
.flat-btn-outline { border-radius: 0; border: 2px solid #111827; background: transparent; color: #111827; }
""",
    "brutalist": """\
/* Brutalist theme */
body { background: #ffffff; color: #000000; font-family: 'Courier New', monospace; }
* { border-radius: 0 !important; }
.brut-card { background: #ffffff; border: 2px solid #000000; box-shadow: 4px 4px 0 #000000; }
.brut-card:hover { box-shadow: 6px 6px 0 #000000; transform: translate(-2px,-2px); }
.brut-btn { background: #000000; color: #ffffff; border: 2px solid #000000; padding: 8px 16px; box-shadow: 3px 3px 0 #f97316; }
.brut-btn:hover { box-shadow: 5px 5px 0 #f97316; transform: translate(-2px,-2px); }
.brut-accent { background: #facc15; color: #000000; }
""",
    "neon_cyberpunk": """\
/* Neon / Cyberpunk theme */
body { background: #050810; color: #e2e8f0; font-family: 'Share Tech Mono', 'Courier New', monospace; }
body::before { content:''; position:fixed; inset:0; background-image: linear-gradient(rgba(0,255,255,0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(0,255,255,0.03) 1px,transparent 1px); background-size: 40px 40px; pointer-events:none; z-index:0; }
.cyber-card { background: rgba(5,8,16,0.85); border: 1px solid #00ffff; box-shadow: 0 0 12px rgba(0,255,255,0.25), inset 0 0 12px rgba(0,255,255,0.05); }
.cyber-card-magenta { border-color: #ff00ff; box-shadow: 0 0 12px rgba(255,0,255,0.25), inset 0 0 12px rgba(255,0,255,0.05); }
.cyber-text-glow { color: #00ffff; text-shadow: 0 0 8px #00ffff; }
.cyber-btn { background: transparent; border: 1px solid #00ffff; color: #00ffff; box-shadow: 0 0 8px rgba(0,255,255,0.4); }
.cyber-btn:hover { background: rgba(0,255,255,0.1); box-shadow: 0 0 16px rgba(0,255,255,0.6); }
""",
    "soft_pastel": """\
/* Soft Pastel theme */
body { background: #fdf4ff; color: #3b1f5e; font-family: 'Nunito', 'Inter', sans-serif; }
.pastel-card { background: #fce7f3; border: 1px solid #fbcfe8; border-radius: 16px; box-shadow: 0 4px 20px rgba(168,85,247,0.08); }
.pastel-card-blue { background: #e0f2fe; border-color: #bae6fd; }
.pastel-card-green { background: #dcfce7; border-color: #bbf7d0; }
.pastel-btn { background: #a855f7; color: #ffffff; border-radius: 50px; box-shadow: 0 4px 12px rgba(168,85,247,0.3); }
.pastel-btn:hover { background: #9333ea; box-shadow: 0 6px 16px rgba(168,85,247,0.4); transform: translateY(-1px); }
""",
}


SPEED_MS: dict = {
    "instant": 0, "fast": 150, "normal": 300, "slow": 500, "cinematic": 800,
}


TRANSITION_CSS: dict = {
    "fade":  "transition: opacity {ms}ms ease;",
    "slide": "transition: transform {ms}ms ease, opacity {ms}ms ease;",
    "scale": "transition: transform {ms}ms cubic-bezier(.4,0,.2,1), opacity {ms}ms ease;",
    "flip":  "transition: transform {ms}ms ease; transform-style: preserve-3d;",
    "blur":  "transition: filter {ms}ms ease, opacity {ms}ms ease;",
}


SKELETON_CSS: dict = {
    "pulse":   ".skeleton { animation: pulse 1.5s cubic-bezier(.4,0,.6,1) infinite; background: rgba(148,163,184,.2); border-radius:4px; } @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}",
    "shimmer": ".skeleton { background: linear-gradient(90deg,rgba(148,163,184,.1) 25%,rgba(148,163,184,.25) 50%,rgba(148,163,184,.1) 75%); background-size:200% 100%; animation:shimmer 1.5s infinite; border-radius:4px; } @keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}",
}


def _generate_index_css(
    ui_theme: str = "default",
    page_transition: str = "fade",
    animation_speed: str = "normal",
    micro_interactions: bool = True,
    scroll_reveal: bool = True,
    loading_style: str = "shimmer",
    hover_lift: bool = True,
) -> str:
    base = """\
@tailwind base;
@tailwind components;
@tailwind utilities;
"""
    parts: list[str] = [base]

    # Theme layer
    theme_extra = THEME_CSS.get(ui_theme, "")
    if theme_extra:
        parts.append(theme_extra)

    # Animation speed variable
    ms = SPEED_MS.get(animation_speed, 300)
    parts.append(f":root {{ --anim-speed: {ms}ms; }}")

    # Page transitions
    if page_transition != "none" and ms > 0:
        tpl = TRANSITION_CSS.get(page_transition, TRANSITION_CSS["fade"])
        rule = tpl.replace("{ms}", str(ms))
        parts.append(f".page-enter {{ {rule} }}")

    # Loading skeleton
    skel = SKELETON_CSS.get(loading_style, "")
    if skel:
        parts.append(skel)

    # Hover lift
    if hover_lift:
        parts.append(
            ".hover-lift { transition: transform var(--anim-speed) ease, box-shadow var(--anim-speed) ease; }"
            " .hover-lift:hover { transform: translateY(-3px); box-shadow: 0 8px 24px rgba(0,0,0,0.18); }"
        )

    # Micro-interactions
    if micro_interactions:
        parts.append(
            ".btn-press:active { transform: scale(0.96); }"
            " .btn-press { transition: transform calc(var(--anim-speed) * 0.5) ease; }"
        )

    # Scroll reveal (CSS-only baseline; JS layer can enhance)
    if scroll_reveal:
        parts.append(
            ".reveal { opacity: 0; transform: translateY(16px); transition: opacity var(--anim-speed) ease, transform var(--anim-speed) ease; }"
            " .reveal.visible { opacity: 1; transform: translateY(0); }"
        )

    return "\n".join(parts)


def _generate_main_tsx() -> str:
    return """\
import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { ToastProvider } from './components/Toaster'
import { ErrorBoundary } from './components/ErrorBoundary'
import { router } from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
    mutations: { retry: 0 },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ErrorBoundary>
          <RouterProvider router={router} />
        </ErrorBoundary>
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
"""


def _generate_auth_ts() -> str:
    return """\
// Auto-generated by AetherOS p05_frontend
// Only the short-lived access token is kept in the browser. The refresh token is an HttpOnly cookie set by the
// API (script cannot read it, so an XSS cannot steal a long-lived session); it is never stored here.
const TOKEN_KEY = 'auth_token'

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY)
export const setToken = (access: string): void => {
  localStorage.setItem(TOKEN_KEY, access)
}
export const clearToken = (): void => {
  localStorage.removeItem(TOKEN_KEY)
  // best effort: asks the API to drop the HttpOnly refresh cookie
  fetch(`${import.meta.env.VITE_API_URL ?? ''}/api/auth/logout`, { method: 'POST', credentials: 'include' }).catch(() => undefined)
}
"""


# ── Dynamic file generators ────────────────────────────────────────────────────

def _col_to_ts_type_full(col: str, columns: List[str]) -> str:
    """Map column name to TypeScript type, using Optional[X]→X | null for nullable fields.

    Fields that are typically nullable get the union-null form so generated components
    can safely handle missing values without TypeScript errors.
    """
    # Nullable column heuristics: description / optional business fields
    _nullable_kws = ("description", "notes", "body", "content", "bio", "comment",
                     "image", "photo", "avatar", "thumbnail", "url", "website",
                     "address", "bio", "middle_name", "suffix", "company")
    lower = col.lower()
    base = col_to_ts_type(col)
    is_nullable = (
        lower in _nullable_kws
        or any(lower.startswith(p) for p in ("image_", "photo_", "thumb_", "avatar_"))
        or lower.endswith("_url")
        or lower.endswith("_at")  # timestamps often null
    )
    if is_nullable:
        return f"{base} | null"
    return base


def _generate_types(entities: List[dict]) -> str:
    """Generate src/types/index.ts with one typed interface per entity.

    Additions over the basic version:
    - Nullable (X | null) for optional fields (descriptions, images, timestamps)
    - XListResponse interface so callers can type paginated API responses
    - XCreate Omit type for create payloads
    """
    lines: List[str] = [
        "// Auto-generated by AetherOS p05_frontend",
        "// TypeScript interfaces for all entities + paginated list responses",
        "",
        "/** Generic paginated response returned by list endpoints. */",
        "export interface PaginatedResponse<T> {",
        "  items: T[]",
        "  total: number",
        "  page: number",
        "  page_size: number",
        "}",
        "",
    ]

    for ent in entities:
        table = ent["table"]
        columns = ent["columns"]
        type_name = to_type_name(table)  # singular: "Patient", "TelemetryEntry"

        lines.append(f"export interface {type_name} {{")
        for col in columns:
            ts_type = _col_to_ts_type_full(col, columns)
            optional = col.lower() in ("created_at", "updated_at", "deleted_at") or col == "id"
            suffix = "?" if optional else ""
            lines.append(f"  {col}{suffix}: {ts_type}")
        lines.append("}")
        lines.append("")

        # Paginated list response
        lines.append(f"export type {type_name}ListResponse = PaginatedResponse<{type_name}>")
        lines.append("")

        # Create type (omit id, created_at, updated_at, deleted_at)
        omit_fields = [c for c in columns if c.lower() in EXCLUDED_COLS]
        if omit_fields:
            omit_str = " | ".join(f"'{f}'" for f in omit_fields)
            lines.append(f"export type {type_name}Create = Omit<{type_name}, {omit_str}>")
        else:
            lines.append(f"export type {type_name}Create = {type_name}")
        lines.append("")

    return "\n".join(lines)


def _generate_api(entities: List[dict], route_map: Dict[str, str]) -> str:
    """Generate src/lib/api.ts."""
    lines: List[str] = [
        "// Auto-generated by AetherOS p05_frontend",
        "import axios from 'axios'",
        "import { getToken, clearToken } from './auth'",
        "",
    ]

    # Build entity type imports (use singular type names)
    type_imports = [to_type_name(e["table"]) for e in entities]
    create_imports = [f"{to_type_name(e['table'])}Create" for e in entities]
    all_type_imports = type_imports + create_imports
    lines.append(f"import type {{ {', '.join(all_type_imports)} }} from '../types'")
    lines.append("")
    lines.append("// The backend serves every route under /api. With VITE_API_URL set the browser calls that server")
    lines.append("// directly; unset, the Vite dev proxy and nginx forward /api/* to it unchanged.")
    lines.append("const BASE = import.meta.env.VITE_API_URL ?? ''")
    lines.append("const API_PREFIX = '/api'")
    lines.append("")
    lines.append("export const apiClient = axios.create({ baseURL: BASE + API_PREFIX })")
    lines.append("export const api = apiClient  // alias used by IR-generated components")
    lines.append("")
    lines.append("apiClient.interceptors.request.use(cfg => {")
    lines.append("  const token = getToken()")
    lines.append("  if (token) cfg.headers.Authorization = `Bearer ${token}`")
    lines.append("  return cfg")
    lines.append("})")
    lines.append("")
    lines.append("// Debounce flag — prevents concurrent 401s from triggering multiple redirects")
    lines.append("let _sessionExpired = false")
    lines.append("")
    lines.append("apiClient.interceptors.response.use(")
    lines.append("  r => r,")
    lines.append("  err => {")
    lines.append("    const url = err.config?.url ?? ''")
    lines.append("    const is401 = err.response?.status === 401")
    lines.append("    const isAuthRoute = url.includes('/auth/login') || url.includes('/auth/register')")
    lines.append("    if (is401 && !isAuthRoute && !_sessionExpired) {")
    lines.append("      _sessionExpired = true")
    lines.append("      clearToken()")
    lines.append("      // Use replace (not href=) so the browser back-button still works after re-login")
    lines.append("      setTimeout(() => { _sessionExpired = false; window.location.replace(import.meta.env.BASE_URL + 'login') }, 80)")
    lines.append("    }")
    lines.append("    return Promise.reject(err)")
    lines.append("  },")
    lines.append(")")
    lines.append("")
    lines.append("export const authApi = {")
    lines.append("  login: (email: string, password: string) =>")
    lines.append("    apiClient.post<{ access_token: string; refresh_token: string }>('/auth/login', { email, password }).then(r => r.data),")
    lines.append("  register: (email: string, password: string) =>")
    lines.append("    apiClient.post('/auth/register', { email, password }).then(r => r.data),")
    lines.append("}")

    for ent in entities:
        table = ent["table"]
        type_name = to_type_name(table)    # singular: "Patient"
        endpoint = route_map.get(table, f"/{table}")
        # camelCase api object name: e.g. "lead_contacts" → "leadContactsApi"
        camel = table[0].lower() + to_pascal_case(table)[1:]

        lines.append("")
        lines.append(f"export const {camel}Api = {{")
        lines.append(
            f"  list: (page = 1, pageSize = 20) => "
            f"apiClient.get<{{items: {type_name}[]; total: number; page: number; page_size: number}}>("
            f"'{endpoint}', {{ params: {{ page, page_size: pageSize }} }}"
            f").then(r => r.data),"
        )
        lines.append(f"  create: (data: {type_name}Create) => apiClient.post<{type_name}>('{endpoint}', data).then(r => r.data),")
        lines.append(f"  update: (id: string | number, data: Partial<{type_name}Create>) =>")
        lines.append(f"    apiClient.patch<{type_name}>(`{endpoint}/${{id}}`, data).then(r => r.data),")
        lines.append(f"  remove: (id: string | number) => apiClient.delete(`{endpoint}/${{id}}`),")
        lines.append("}")

    return "\n".join(lines) + "\n"
