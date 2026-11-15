"""P05 Frontend — file-writing / scaffold helpers.

All _generate_* functions that produce static file content for the generated
React/Vite/TanStack project live here. Each function returns a string (the
file contents to write). The run() function in task_agent.py calls these
and writes the results to disk.
"""
from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.phases.p05_frontend.prompts import (
    DOMAIN_STAT_LABELS,
    THEME_CSS,
    SPEED_MS,
    TRANSITION_CSS,
    SKELETON_CSS,
)
from aether_os.phases.p05_frontend.scaffold import (
    EXCLUDED_COLS,
    to_pascal_case,
    to_type_name,
    to_label,
    to_singular,
    slug,
    col_to_ts_type,
    col_to_field_def_type,
    col_to_field_options,
    entity_icon,
    entity_emoji,
    pluralise,
)

logger = logging.getLogger(__name__)

def generate_package_json(project_slug: str) -> str:
    data = {
        "name": project_slug,
        "private": True,
        "version": "0.1.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview",
            "lint": "eslint src --ext .ts,.tsx --report-unused-disable-directives --max-warnings 0",
            "typecheck": "tsc --noEmit",
            "test": "vitest run",
            "test:watch": "vitest",
            "test:coverage": "vitest run --coverage"
        },
        "dependencies": {
            "react": "^18.3.1",
            "react-dom": "^18.3.1",
            "@tanstack/react-query": "^5.62.7",
            "@tanstack/react-router": "^1.58.3",
            "@tanstack/react-table": "^8.20.5",
            "axios": "^1.7.9",
            "lucide-react": "^0.441.0",
            "recharts": "^2.12.7",
            "react-hook-form": "^7.53.0",
            "@hookform/resolvers": "^3.9.0",
            "zod": "^3.23.8",
            "@radix-ui/react-dialog": "^1.1.1",
            "@radix-ui/react-dropdown-menu": "^2.1.1",
            "@radix-ui/react-select": "^2.1.0",
            "@radix-ui/react-toast": "^1.2.1",
            "@radix-ui/react-tooltip": "^1.1.2",
            "class-variance-authority": "^0.7.0",
            "clsx": "^2.1.1",
            "framer-motion": "^11.3.24",
            "tailwind-merge": "^2.5.2"
        },
        "devDependencies": {
            "@types/react": "^18.3.5",
            "@types/react-dom": "^18.3.0",
            "@typescript-eslint/eslint-plugin": "^7.18.0",
            "@typescript-eslint/parser": "^7.18.0",
            "eslint": "^8.57.0",
            "eslint-plugin-react-hooks": "^4.6.2",
            "eslint-plugin-react-refresh": "^0.4.9",
            "@vitejs/plugin-react": "^4.3.4",
            "typescript": "^5.5.3",
            "vite": "^6.0.5",
            "tailwindcss": "^3.4.17",
            "autoprefixer": "^10.4.20",
            "postcss": "^8.4.45",
            "@testing-library/react": "^14.0.0",
            "@testing-library/jest-dom": "^6.0.0",
            "@testing-library/user-event": "^14.0.0",
            "vitest": "^1.0.0",
            "@vitest/coverage-v8": "^1.0.0",
            "jsdom": "^24.0.0"
        }
    }
    return json.dumps(data, indent=2)


def _generate_eslint_config() -> str:
    return """\
module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs'],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  rules: {
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    '@typescript-eslint/no-explicit-any': 'warn',
    '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
  },
}
"""


def _generate_vite_config() -> str:
    return """\
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// BASE_PATH: where the built app is served from. '/' unless the host sets VITE_BASE_PATH (a preview host that
// serves it under a sub-path sets it). The router derives its basepath from it (import.meta.env.BASE_URL).
const BASE_PATH = process.env.VITE_BASE_PATH || '/'

export default defineConfig({
  base: BASE_PATH,
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
      },
    }
  }
})
"""


def _generate_tsconfig() -> str:
    data = {
        "compilerOptions": {
            "target": "ES2020",
            "useDefineForClassFields": True,
            "lib": ["ES2020", "DOM", "DOM.Iterable"],
            "module": "ESNext",
            "skipLibCheck": True,
            "moduleResolution": "bundler",
            "allowImportingTsExtensions": True,
            "resolveJsonModule": True,
            "isolatedModules": True,
            "noEmit": True,
            "jsx": "react-jsx",
            "strict": True,
            "noUnusedLocals": False,
            "noUnusedParameters": False,
            "noFallthroughCasesInSwitch": True,
            "types": ["vite/client"],
            "baseUrl": ".",
            "paths": {"@/*": ["./src/*"]}
        },
        "include": ["src"],
        "exclude": ["src/__tests__"]
    }
    return json.dumps(data, indent=2)


def _generate_tailwind_config(ui_theme: str = "default") -> str:
    # Theme-appropriate brand palette + dark-mode class
    _neon_palette = """\
        brand: {
          50:  '#e0ffff',
          100: '#b3fffe',
          200: '#80fffd',
          300: '#4dfffc',
          400: '#00ffff',
          500: '#00e5e5',
          600: '#00b3b3',
          700: '#008080',
          800: '#005555',
          900: '#003333',
        },
        surface: {
          50: '#0a0f1e',
          100: '#050810',
          200: '#0d1117',
          300: '#1a2035',
          400: '#242b45',
        },
        accent: {
          pink:   '#ff00ff',
          cyan:   '#00ffff',
          yellow: '#facc15',
        },"""
    _glass_palette = """\
        brand: {
          50:  '#f5f3ff',
          200: '#ddd6fe',
          500: '#8b5cf6',
          600: '#7c3aed',
          700: '#6d28d9',
          900: '#4c1d95',
        },"""
    _default_palette = """\
        brand: {
          50:  '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          900: '#1e3a8a',
        },"""
    # Domain-specific palettes — each domain gets a distinct visual identity
    _domain_palettes = {
        # Healthcare: clinical teal — trust, cleanliness, calm
        "healthcare": ("""\
        brand: {
          50:  '#f0fdfa',
          100: '#ccfbf1',
          200: '#99f6e4',
          500: '#14b8a6',
          600: '#0d9488',
          700: '#0f766e',
          900: '#134e4a',
        },""", None),
        # FinTech: deep navy + gold — wealth, authority, precision
        "fintech": ("""\
        brand: {
          50:  '#fefce8',
          100: '#fef9c3',
          200: '#fef08a',
          500: '#eab308',
          600: '#ca8a04',
          700: '#1e3a5f',
          900: '#0f172a',
        },""", None),
        # Restaurant / Food: warm amber/orange — appetite, warmth
        "restaurant": ("""\
        brand: {
          50:  '#fff7ed',
          100: '#ffedd5',
          200: '#fed7aa',
          500: '#f97316',
          600: '#ea580c',
          700: '#c2410c',
          900: '#7c2d12',
        },""", None),
        # E-commerce / Marketplace: vibrant rose-pink — energy, deals
        "ecommerce": ("""\
        brand: {
          50:  '#fdf2f8',
          100: '#fce7f3',
          200: '#fbcfe8',
          500: '#ec4899',
          600: '#db2777',
          700: '#be185d',
          900: '#831843',
        },""", None),
        "marketplace": ("""\
        brand: {
          50:  '#fdf2f8',
          100: '#fce7f3',
          200: '#fbcfe8',
          500: '#ec4899',
          600: '#db2777',
          700: '#be185d',
          900: '#831843',
        },""", None),
        # Education: friendly cyan-sky — openness, learning
        "education": ("""\
        brand: {
          50:  '#ecfeff',
          100: '#cffafe',
          200: '#a5f3fc',
          500: '#06b6d4',
          600: '#0891b2',
          700: '#0e7490',
          900: '#164e63',
        },""", None),
        # Fitness / Gym: energetic red-orange — power, action
        "fitness": ("""\
        brand: {
          50:  '#fff1f2',
          100: '#ffe4e6',
          200: '#fecdd3',
          500: '#f43f5e',
          600: '#e11d48',
          700: '#be123c',
          900: '#881337',
        },""", None),
        "gym_fitness": ("""\
        brand: {
          50:  '#fff1f2',
          100: '#ffe4e6',
          200: '#fecdd3',
          500: '#f43f5e',
          600: '#e11d48',
          700: '#be123c',
          900: '#881337',
        },""", None),
        # Real Estate: earthy green — stability, growth, trust
        "real_estate": ("""\
        brand: {
          50:  '#f0fdf4',
          100: '#dcfce7',
          200: '#bbf7d0',
          500: '#22c55e',
          600: '#16a34a',
          700: '#15803d',
          900: '#14532d',
        },""", None),
        # Hospitality: warm golden — luxury, welcome
        "hospitality": ("""\
        brand: {
          50:  '#fffbeb',
          100: '#fef3c7',
          200: '#fde68a',
          500: '#f59e0b',
          600: '#d97706',
          700: '#b45309',
          900: '#78350f',
        },""", None),
        # Logistics / IoT: slate-blue — reliability, technology
        "logistics": ("""\
        brand: {
          50:  '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          900: '#0f172a',
        },""", None),
        "iot": ("""\
        brand: {
          50:  '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          900: '#0f172a',
        },""", None),
        # HRM / CRM / Analytics: professional indigo
        "hrm": ("""\
        brand: {
          50:  '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          900: '#312e81',
        },""", None),
        "crm": ("""\
        brand: {
          50:  '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          900: '#312e81',
        },""", None),
        "analytics": ("""\
        brand: {
          50:  '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          900: '#312e81',
        },""", None),
        # SaaS: modern violet — innovation, product
        "saas": ("""\
        brand: {
          50:  '#faf5ff',
          100: '#f3e8ff',
          200: '#e9d5ff',
          500: '#a855f7',
          600: '#9333ea',
          700: '#7e22ce',
          900: '#581c87',
        },""", None),
        # Food delivery: deep orange
        "food": ("""\
        brand: {
          50:  '#fff7ed',
          100: '#ffedd5',
          200: '#fed7aa',
          500: '#f97316',
          600: '#ea580c',
          700: '#c2410c',
          900: '#7c2d12',
        },""", None),
    }

    _theme_palettes = {
        "neon_cyberpunk": (_neon_palette, "'Share Tech Mono', 'Courier New', monospace"),
        "glassmorphism":  (_glass_palette, None),
        "brutalist":      (_default_palette, "'Courier New', monospace"),
    }
    # Domain themes override the ui_theme name when it's still "default"
    if ui_theme in _domain_palettes:
        _palette, _font = _domain_palettes[ui_theme]
    else:
        _palette, _font = _theme_palettes.get(ui_theme, (_default_palette, None))
    # Dark mode enabled for all themes — class-based toggle with localStorage persistence
    _dark = "darkMode: 'class',"
    _font_block = f"""
      fontFamily: {{
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: [{_font}],
      }},""" if _font else """
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },"""
    return f"""\
export default {{
  content: ['./index.html', './src/**/*.{{js,ts,jsx,tsx}}'],
  {_dark}
  theme: {{
    extend: {{
      colors: {{
{_palette}
      }},{_font_block}
      fontSize: {{
        'xs':   ['0.75rem',  {{ lineHeight: '1rem' }}],
        'sm':   ['0.875rem', {{ lineHeight: '1.25rem' }}],
        'base': ['1rem',     {{ lineHeight: '1.5rem' }}],
        'lg':   ['1.125rem', {{ lineHeight: '1.75rem' }}],
        'xl':   ['1.25rem',  {{ lineHeight: '1.75rem' }}],
        '2xl':  ['1.5rem',   {{ lineHeight: '2rem' }}],
        '3xl':  ['1.875rem', {{ lineHeight: '2.25rem' }}],
        '4xl':  ['2.25rem',  {{ lineHeight: '2.5rem' }}],
      }},
      fontWeight: {{
        normal:    '400',
        medium:    '500',
        semibold:  '600',
        bold:      '700',
      }},
    }}
  }},
  plugins: []
}}
"""


def _generate_postcss_config() -> str:
    return """\
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} }
}
"""


def _generate_index_html(project_name: str, description: str = "", domain: str = "saas") -> str:
    # Both values come from the spec: escaped for HTML text/attributes, and JSON-encoded (with `<` neutralised, so
    # `</script>` cannot end the block) inside the JSON-LD script. `x</title><script>` used to run as a script.
    _desc = description or f"{project_name} — the modern platform built for your business."
    _ld_name = json.dumps(project_name).replace("<", "\\u003c")
    _ld_desc = json.dumps(_desc).replace("<", "\\u003c")
    project_name = html.escape(project_name, quote=True)
    _desc = html.escape(_desc, quote=True)
    _og_type = "website"
    _schema_type = "WebSite"
    if domain in ("ecommerce", "marketplace"):
        _og_type = "website"
        _schema_type = "Store"
    elif domain == "saas":
        _schema_type = "SoftwareApplication"
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="description" content="{_desc}" />
  <meta name="robots" content="index, follow" />
  <meta name="theme-color" content="#6366f1" />

  <!-- Open Graph / Social -->
  <meta property="og:type" content="{_og_type}" />
  <meta property="og:title" content="{project_name}" />
  <meta property="og:description" content="{_desc}" />
  <meta property="og:site_name" content="{project_name}" />

  <!-- Twitter Card -->
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{project_name}" />
  <meta name="twitter:description" content="{_desc}" />

  <!-- Preconnect for perf -->
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />

  <!-- Inter font — primary typography system -->
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />

  <!-- Favicon -->
  <link rel="icon" type="image/svg+xml" href="/vite.svg" />

  <title>{project_name}</title>

  <!-- Schema.org structured data -->
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "{_schema_type}",
    "name": {_ld_name},
    "description": {_ld_desc},
    "url": "/"
  }}
  </script>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.tsx"></script>
</body>
</html>
"""


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
const TOKEN_KEY = 'auth_token'
const REFRESH_KEY = 'auth_refresh_token'

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY)
export const getRefreshToken = (): string | null => localStorage.getItem(REFRESH_KEY)
export const setToken = (access: string, refresh: string): void => {
  localStorage.setItem(TOKEN_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
}
export const clearToken = (): void => {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
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
    access_token = "demo"
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


def _generate_app(entities: List[dict], dual_portal: bool = False) -> str:
    """Generate src/App.tsx with TanStack Router.

    When dual_portal=True, generates two route trees:
      - Customer portal at /  (browsing, self-service)
      - Admin portal at /admin (full CRUD management)
    Login page reads JWT role and redirects accordingly.
    """
    if dual_portal:
        return _generate_dual_app(entities)

    entity_imports: List[str] = []
    entity_routes: List[str] = []
    entity_route_children: List[str] = []

    for ent in entities:
        table = ent["table"]
        pascal = ent.get("name") or to_pascal_case(table)
        route_path = f"/{table.replace('_', '-')}"
        route_var = f"{table}Route"

        entity_imports.append(f"import {pascal}Page from './pages/{pascal}Page'")
        entity_routes.append(
            f"const {route_var} = createRoute({{\n"
            f"  getParentRoute: () => layoutRoute,\n"
            f"  path: '{route_path}',\n"
            f"  component: {pascal}Page,\n"
            f"}})"
        )
        entity_route_children.append(f"    {route_var},")

    imports_str = "\n".join(entity_imports)
    routes_str = "\n\n".join(entity_routes)
    children_str = "\n".join(entity_route_children)

    return f"""\
// Auto-generated by AetherOS p05_frontend
import {{ createRootRoute, createRoute, createRouter, Outlet, redirect }} from '@tanstack/react-router'
import {{ Layout }} from './components/Layout'
import {{ LoginPage }} from './pages/LoginPage'
import {{ getToken }} from './lib/auth'
import Dashboard from './pages/Dashboard'
import NotFoundPage from './pages/NotFoundPage'
{imports_str}

const rootRoute = createRootRoute({{ component: () => <Outlet /> }})

const layoutRoute = createRoute({{
  getParentRoute: () => rootRoute,
  id: 'layout',
  component: Layout,
  beforeLoad: () => {{
    if (!getToken()) throw redirect({{ to: '/login' }})
  }},

}})

const loginRoute = createRoute({{
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
}})

const dashboardRoute = createRoute({{
  getParentRoute: () => layoutRoute,
  path: '/',
  component: Dashboard,
}})

{routes_str}

const routeTree = rootRoute.addChildren([
  loginRoute,
  layoutRoute.addChildren([
    dashboardRoute,
{children_str}
  ]),
])

export const router = createRouter({{ routeTree, basepath: import.meta.env.BASE_URL.replace(/\\/+$/, '') || '/', defaultNotFoundComponent: NotFoundPage }})

declare module '@tanstack/react-router' {{
  interface Register {{ router: typeof router }}
}}
"""


def _generate_dual_app(entities: List[dict]) -> str:
    """Generate App.tsx with two portals: /  (customer) and /admin (owner/operator)."""
    entity_imports: List[str] = []
    admin_routes: List[str] = []
    admin_children: List[str] = []
    customer_routes: List[str] = []
    customer_children: List[str] = []

    # Customer-facing entities: product-like browsable items and member-self-service entities
    _customer_kws = ("product", "item", "listing", "service", "book", "course", "event",
                     "article", "post", "property", "menu", "catalog",
                     "class", "schedule", "trainer", "workout", "session", "plan",
                     "member", "booking", "reservation", "room", "team", "player",
                     "match", "fixture", "table", "dish")

    for ent in entities:
        table = ent["table"]
        pascal = ent.get("name") or to_pascal_case(table)
        route_var = f"{table}Route"
        admin_route_var = f"admin{pascal}Route"

        entity_imports.append(f"import {pascal}Page from './pages/{pascal}Page'")

        # Every entity goes to admin
        admin_routes.append(
            f"const {admin_route_var} = createRoute({{\n"
            f"  getParentRoute: () => adminLayoutRoute,\n"
            f"  path: '/admin/{table.replace('_', '-')}',\n"
            f"  component: {pascal}Page,\n"
            f"}})"
        )
        admin_children.append(f"    {admin_route_var},")

        # Customer-like entities also appear in the customer portal (read-oriented)
        is_customer_entity = any(k in table.lower() for k in _customer_kws)
        if is_customer_entity:
            customer_routes.append(
                f"const {route_var} = createRoute({{\n"
                f"  getParentRoute: () => customerLayoutRoute,\n"
                f"  path: '/{table.replace('_', '-')}',\n"
                f"  component: {pascal}Page,\n"
                f"}})"
            )
            customer_children.append(f"    {route_var},")

    imports_str = "\n".join(entity_imports)
    admin_routes_str = "\n\n".join(admin_routes)
    customer_routes_str = "\n\n".join(customer_routes)
    admin_children_str = "\n".join(admin_children)
    customer_children_str = "\n".join(customer_children)

    return f"""\
// Auto-generated by AetherOS p05_frontend — dual portal (customer + admin)
import {{ createRootRoute, createRoute, createRouter, Outlet, redirect }} from '@tanstack/react-router'
import {{ CustomerLayout }} from './components/CustomerLayout'
import {{ AdminLayout }} from './components/AdminLayout'
import {{ LoginPage }} from './pages/LoginPage'
import {{ getToken }} from './lib/auth'
import CustomerHome from './pages/CustomerHome'
import AdminDashboard from './pages/Dashboard'
import NotFoundPage from './pages/NotFoundPage'
{imports_str}
function _getRole(): string | null {{
  try {{
    const t = getToken()
    if (!t) return null
    return JSON.parse(atob(t.split('.')[1]))?.role ?? 'user'
  }} catch {{ return null }}
}}

const rootRoute = createRootRoute({{ component: () => <Outlet /> }})

// ── Customer portal ───────────────────────────────────────────────────────────
const customerLayoutRoute = createRoute({{
  getParentRoute: () => rootRoute,
  id: 'customer',
  component: CustomerLayout,
  beforeLoad: () => {{
    if (!getToken()) throw redirect({{ to: '/login' }})
  }},

}})

const customerHomeRoute = createRoute({{
  getParentRoute: () => customerLayoutRoute,
  path: '/',
  component: CustomerHome,
}})

{customer_routes_str}

// ── Admin portal ──────────────────────────────────────────────────────────────
const adminLayoutRoute = createRoute({{
  getParentRoute: () => rootRoute,
  id: 'admin',
  component: AdminLayout,
  beforeLoad: () => {{
    const role = _getRole()
    if (!role) throw redirect({{ to: '/login' }})
    if (role !== 'admin') throw redirect({{ to: '/' }})
  }},
}})

const adminDashboardRoute = createRoute({{
  getParentRoute: () => adminLayoutRoute,
  path: '/admin',
  component: AdminDashboard,
}})

{admin_routes_str}

// ── Auth ──────────────────────────────────────────────────────────────────────
const loginRoute = createRoute({{
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
}})

const routeTree = rootRoute.addChildren([
  loginRoute,
  customerLayoutRoute.addChildren([
    customerHomeRoute,
{customer_children_str}
  ]),
  adminLayoutRoute.addChildren([
    adminDashboardRoute,
{admin_children_str}
  ]),
])

export const router = createRouter({{ routeTree, basepath: import.meta.env.BASE_URL.replace(/\\/+$/, '') || '/', defaultNotFoundComponent: NotFoundPage }})

declare module '@tanstack/react-router' {{
  interface Register {{ router: typeof router }}
}}
"""


def _generate_admin_layout(entities: List[dict], project_name: str) -> str:
    """Generate AdminLayout.tsx — dark sidebar for the owner/operator portal."""
    nav_items: List[str] = ["  { to: '/admin' as const, label: 'Dashboard', icon: 'LayoutDashboard' },"]
    for ent in entities:
        table = ent["table"]
        label = to_label(table)
        icon = entity_icon(table)
        nav_items.append(f"  {{ to: '/admin/{table.replace('_', '-')}' as const, label: '{label}', icon: '{icon}' }},")
    nav_str = "\n".join(nav_items)
    icons_needed = sorted({"LayoutDashboard", "LogOut"} | {entity_icon(e["table"]) for e in entities})
    icons_import = ", ".join(icons_needed)

    return f"""\
// Auto-generated by AetherOS p05_frontend — admin/owner portal layout
import {{ Outlet, Link, useRouter }} from '@tanstack/react-router'
import {{ {icons_import} }} from 'lucide-react'
import {{ clearToken }} from '../lib/auth'

const _ICON_MAP: Record<string, React.FC<any>> = {{ {", ".join(f"'{i}': {i}" for i in icons_needed)} }}

const NAV = [
{nav_str}
]

export function AdminLayout() {{
  const router = useRouter()
  const handleLogout = () => {{ clearToken(); router.navigate({{ to: '/login' }}) }}
  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      <aside className="w-64 bg-gray-900 text-white flex flex-col shrink-0">
        <div className="px-6 py-5 border-b border-gray-700">
          <span className="text-lg font-bold text-white">{project_name}</span>
          <span className="ml-2 text-xs bg-brand-600 text-white px-2 py-0.5 rounded-full font-semibold">Admin</span>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {{NAV.map(item => {{
            const Icon = _ICON_MAP[item.icon]
            return (
              <Link key={{item.to}} to={{item.to}}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-300 hover:bg-gray-800 hover:text-white transition-colors [&.active]:bg-brand-600 [&.active]:text-white text-sm font-medium">
                {{Icon && <Icon size={{16}} />}} {{item.label}}
              </Link>
            )
          }})}}
        </nav>
        <div className="px-3 py-4 border-t border-gray-700 space-y-1">
          <a href="/" className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white text-sm transition-colors">
            <span className="text-xs">🌐</span> Customer View
          </a>
          <button onClick={{handleLogout}}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white text-sm transition-colors">
            <LogOut size={{16}} /> Logout
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}}
"""


def _generate_customer_layout(entities: List[dict], project_name: str) -> str:
    """Generate CustomerLayout.tsx — clean top-nav for the end-user/customer portal."""
    # Customer nav items: only browsable entity pages and member-self-service entities
    _customer_kws = ("product", "item", "listing", "service", "book", "course", "event",
                     "article", "post", "property", "menu", "catalog",
                     "class", "schedule", "trainer", "workout", "session", "plan",
                     "member", "booking", "reservation", "room", "team", "player",
                     "match", "fixture", "table", "dish")
    nav_items: List[str] = ["  { to: '/' as const, label: 'Home' },"]
    for ent in entities:
        table = ent["table"]
        if any(k in table.lower() for k in _customer_kws):
            label = to_label(table)
            nav_items.append(f"  {{ to: '/{table.replace('_', '-')}' as const, label: '{label}' }},")
    nav_str = "\n".join(nav_items)

    return f"""\
// Auto-generated by AetherOS p05_frontend — customer-facing portal layout
import {{ Outlet, Link, useRouter }} from '@tanstack/react-router'
import {{ LogOut, User }} from 'lucide-react'
import {{ clearToken, getToken }} from '../lib/auth'

const NAV = [
{nav_str}
]

export function CustomerLayout() {{
  const router = useRouter()
  const handleLogout = () => {{ clearToken(); router.navigate({{ to: '/login' }}) }}
  const isLoggedIn = !!getToken()
  return (
    <div className="min-h-screen bg-white flex flex-col">
      <header className="sticky top-0 z-40 bg-white border-b border-gray-100 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link to="/" className="text-xl font-extrabold text-gray-900 hover:text-brand-600 transition-colors">
            {project_name}
          </Link>
          <nav className="hidden md:flex items-center gap-1">
            {{NAV.map(item => (
              <Link key={{item.to}} to={{item.to}}
                className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors [&.active]:text-brand-600 [&.active]:bg-brand-50">
                {{item.label}}
              </Link>
            ))}}
          </nav>
          <div className="flex items-center gap-2">
            {{isLoggedIn ? (
              <button onClick={{handleLogout}}
                className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors">
                <LogOut size={{15}} /> Sign out
              </button>
            ) : (
              <Link to="/login"
                className="flex items-center gap-2 px-4 py-2 bg-brand-600 text-white text-sm font-semibold rounded-lg hover:bg-brand-700 transition-colors">
                <User size={{15}} /> Sign in
              </Link>
            )}}
          </div>
        </div>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
      <footer className="bg-gray-50 border-t border-gray-100 py-8 mt-12">
        <div className="max-w-7xl mx-auto px-4 text-center text-sm text-gray-400">
          © {{new Date().getFullYear()}} {project_name}
        </div>
      </footer>
    </div>
  )
}}
"""


def _generate_customer_home(
    entities: List[dict],
    route_map: Dict[str, str],
    project_name: str,
    domain: str,
    app_brand: Optional[Dict[str, Any]] = None,
    app_tagline: str = "",
) -> str:
    """Generate CustomerHome.tsx — public-facing landing page for the customer portal."""
    _app_brand = app_brand or {}
    # Domain-specific hero gradient (pairs with the brand palette in tailwind.config.js)
    _domain_hero_gradient = {
        "healthcare":  "from-teal-900 via-teal-800 to-teal-600",
        "fintech":     "from-slate-900 via-slate-800 to-yellow-700",
        "restaurant":  "from-orange-900 via-orange-800 to-amber-600",
        "food":        "from-orange-900 via-orange-800 to-amber-600",
        "ecommerce":   "from-rose-900 via-pink-800 to-pink-600",
        "marketplace": "from-rose-900 via-pink-800 to-pink-600",
        "education":   "from-cyan-900 via-sky-800 to-cyan-600",
        "fitness":     "from-red-900 via-rose-800 to-red-600",
        "gym_fitness": "from-red-900 via-rose-800 to-red-600",
        "real_estate": "from-green-900 via-emerald-800 to-green-600",
        "hospitality": "from-amber-900 via-yellow-800 to-amber-600",
        "logistics":   "from-slate-900 via-gray-800 to-slate-600",
        "iot":         "from-slate-900 via-gray-800 to-slate-600",
        "hrm":         "from-indigo-900 via-indigo-800 to-violet-600",
        "crm":         "from-indigo-900 via-indigo-800 to-violet-600",
        "analytics":   "from-indigo-900 via-purple-800 to-indigo-600",
        "saas":        "from-violet-900 via-purple-800 to-violet-600",
    }
    _hero_gradient = _domain_hero_gradient.get(domain, "from-gray-900 via-brand-900 to-brand-700")
    # Pick the most browsable entity (product-like items)
    _browse_kws = ("product", "item", "listing", "book", "service", "course", "event",
                   "article", "menu", "property", "catalog")
    primary = next(
        (e for e in entities if any(k in e["table"].lower() for k in _browse_kws)),
        entities[0] if entities else {"table": "items", "columns": []}
    )
    primary_table = primary["table"]
    primary_label = to_label(primary_table)
    primary_endpoint = route_map.get(primary_table, f"/{primary_table}")
    primary_route = f"/{primary_table.replace('_', '-')}"

    # Domain-specific hero copy
    _hero_copy = {
        "ecommerce":   ("Shop the Collection", "Handcrafted products built to last. Free shipping on orders over $50."),
        "marketplace": ("Discover Unique Finds", "Connect with sellers and discover products you'll love."),
        "library":     ("Explore Our Collection", "Browse thousands of books. Reserve online, pick up in-store."),
        "healthcare":  ("Your Health, Your Way", "Book appointments and manage your health records online."),
        "education":   ("Learn Something New", "Explore courses from expert instructors at your own pace."),
        "hospitality": ("Book Your Stay", "Discover beautiful rooms and seamless experiences."),
        "events":      ("Find Your Next Event", "Concerts, workshops, and experiences near you."),
        "food":        ("Order Fresh, Eat Well", "Restaurant-quality meals delivered to your door."),
        "saas":        ("Start Building Today", "Powerful tools to grow your business faster."),
        "gym_fitness": ("Train Smarter, Live Better", "Book classes, track progress, and manage your membership — all in one place."),
        "sports":      ("Play Your Best Game", "Schedules, standings, and stats for your league — all in one place."),
        "hospitality": ("Your Perfect Stay Awaits", "Browse rooms, check availability, and book in seconds."),
        "real_estate": ("Find Your Next Property", "Browse listings, schedule viewings, and manage your lease online."),
        "hrm":         ("Your Workforce, Simplified", "Manage teams, track attendance, and run payroll with ease."),
        "crm":         ("Close More Deals", "Track leads, manage pipelines, and grow your revenue."),
        "restaurant":  ("Great Food, Great Experience", "Reserve a table, browse the menu, and order online."),
    }
    _domain_title, _domain_sub = _hero_copy.get(domain, (f"Welcome to {project_name}", "Explore what we have to offer."))
    # app_brand and app_tagline override domain defaults when explicitly provided
    hero_title = _app_brand.get("headline") or project_name or _domain_title
    hero_sub = _app_brand.get("tagline") or app_tagline or _domain_sub

    return f"""\
// Auto-generated by AetherOS p05_frontend — customer home
import React from 'react'
import {{ useQuery }} from '@tanstack/react-query'
import {{ Link }} from '@tanstack/react-router'
import {{ apiClient }} from '../lib/api'
import {{ ArrowRight, Star }} from 'lucide-react'

export default function CustomerHome() {{
  const {{ data: raw, isLoading }} = useQuery({{
    queryKey: ['{primary_table}'],
    queryFn: () => apiClient.get('{primary_endpoint}').then(r => r.data),
    staleTime: 60_000,
  }})
  const items: any[] = Array.isArray(raw) ? raw : (raw?.items ?? raw?.data ?? [])
  const featured = items.slice(0, 8)

  return (
    <div className="min-h-screen bg-white">
      {{/* Hero */}}
      <section className="bg-gradient-to-br {_hero_gradient} text-white py-24 md:py-36 relative overflow-hidden">
        <div className="absolute inset-0 opacity-[0.06]"
          style={{{{ backgroundImage: 'repeating-linear-gradient(0deg,transparent,transparent 40px,#fff 40px,#fff 41px),repeating-linear-gradient(90deg,transparent,transparent 40px,#fff 40px,#fff 41px)' }}}} />
        <div className="relative max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-5xl md:text-7xl font-extrabold leading-none tracking-tight mb-6">
            {hero_title}
          </h1>
          <p className="text-lg md:text-xl text-gray-300 mb-10 max-w-2xl mx-auto">{hero_sub}</p>
          <Link to="{primary_route}"
            className="inline-flex items-center gap-2 bg-white text-brand-800 font-bold px-8 py-4 rounded-xl hover:bg-brand-50 transition-all shadow-xl">
            Browse {primary_label} <ArrowRight size={{18}} />
          </Link>
        </div>
        <div className="absolute bottom-0 left-0 right-0">
          <svg viewBox="0 0 1440 40" fill="white" preserveAspectRatio="none" className="w-full h-8">
            <path d="M0,40 C360,0 1080,40 1440,10 L1440,40 Z" />
          </svg>
        </div>
      </section>

      {{/* Featured items */}}
      <section className="py-16 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-end justify-between mb-8">
          <div>
            <h2 className="text-2xl font-extrabold text-gray-900">Featured {primary_label}</h2>
            <p className="text-gray-500 mt-1 text-sm">Handpicked just for you</p>
          </div>
          <Link to="{primary_route}" className="text-sm font-semibold text-brand-600 hover:text-brand-700 flex items-center gap-1">
            View all <ArrowRight size={{14}} />
          </Link>
        </div>
        {{isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {{[...Array(8)].map((_,i) => (
              <div key={{i}} className="rounded-2xl bg-gray-100 h-64 animate-pulse" />
            ))}}
          </div>
        ) : featured.length === 0 ? (
          <div className="text-center py-16 text-gray-400">No items found.</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
            {{featured.map((item: any, i: number) => {{
              const seed = item.id ?? i + 1
              const name = item.name ?? item.title ?? item.label ?? `Item ${{item.id}}`
              const price = item.price ?? item.unit_price ?? item.fee ?? null
              return (
                <Link key={{item.id ?? i}} to="{primary_route}"
                  className="group bg-white rounded-2xl border border-gray-100 shadow-sm hover:shadow-xl transition-all hover:-translate-y-1 overflow-hidden flex flex-col">
                  <div className="aspect-square bg-gradient-to-br from-gray-50 to-gray-100 overflow-hidden">
                    {{(item.image_url ?? item.image ?? item.thumbnail)
                      ? <img src={{item.image_url ?? item.image ?? item.thumbnail}} alt={{name}}
                          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                          loading="lazy" onError={{(e) => {{ (e.target as HTMLImageElement).style.display = 'none' }}}} />
                      : <div aria-hidden="true" className="w-full h-full flex items-center justify-center text-4xl font-bold text-gray-300">{{String(name).charAt(0).toUpperCase()}}</div>}}
                  </div>
                  <div className="p-4 flex flex-col flex-1">
                    <h3 className="font-semibold text-gray-900 text-sm line-clamp-2 mb-2">{{name}}</h3>
                    {{price != null && (
                      <p className="text-lg font-bold text-gray-900 mt-auto">${{typeof price === 'number' ? price.toFixed(2) : price}}</p>
                    )}}
                  </div>
                </Link>
              )
            }})}}
          </div>
        )}}
      </section>
    </div>
  )
}}
"""


def _generate_layout(entities: List[dict], project_name: str, layout_mode: str = "admin") -> str:
    """Generate src/components/Layout.tsx."""
    # Collect icons needed
    icons_needed = {"LayoutDashboard", "LogOut"}
    for ent in entities:
        icons_needed.add(entity_icon(ent["table"]))
    for ent in entities:
        icons_needed.add(entity_icon(ent["table"]))

    if layout_mode == "storefront":
        # Premium storefront layout: announcement bar, sticky nav with search + cart badge, rich footer
        nav_items_list: List[str] = []
        for ent in entities:
            table = ent["table"]
            label = to_label(table)
            route_path = f"/{table.replace('_', '-')}"
            nav_items_list.append(f"  {{ to: '{route_path}' as const, label: '{label}' }},")
        nav_items_str = "\n".join(nav_items_list)

        return f"""\
// Auto-generated by AetherOS p05_frontend — premium storefront layout
import {{ useState }} from 'react'
import {{ Link, useRouter, Outlet }} from '@tanstack/react-router'
import {{ clearToken }} from '../lib/auth'
import {{ ShoppingCart, User, Search, Menu, X, Heart }} from 'lucide-react'
import {{ useQuery }} from '@tanstack/react-query'
import {{ apiClient }} from '../lib/api'

const NAV_ITEMS = [
{nav_items_str}
]

const FOOTER_HELP = ['FAQ', 'Shipping & Returns', 'Track Your Order', 'Size Guide', 'Contact Us']
const FOOTER_COMPANY = ['About Us', 'Blog', 'Careers', 'Press', 'Sustainability']
const PAYMENT_METHODS = ['VISA', 'MC', 'AMEX', 'PayPal', 'Apple Pay']

export function Layout() {{
  const router = useRouter()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)

  const handleLogout = () => {{
    clearToken()
    router.navigate({{ to: '/login' }})
  }}

  const {{ data: cartData }} = useQuery({{
    queryKey: ['__cart_count'],
    queryFn: () => apiClient.get('/carts').then(r => {{
      const d = r.data
      return Array.isArray(d) ? d.length : (d?.items?.length ?? d?.total ?? 0)
    }}).catch(() => 0),
    refetchInterval: 60_000,
    staleTime: 30_000,
  }})
  const cartCount = (cartData as number) || 0

  return (
    <div className="min-h-screen bg-white flex flex-col font-sans">
      {{/* ── Sticky header ── */}}
      <header className="sticky top-0 z-50 bg-white/95 backdrop-blur-sm border-b border-gray-100 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16 gap-4">
            {{/* Logo */}}
            <Link to="/" className="flex-shrink-0 text-xl font-extrabold tracking-tight text-gray-900 hover:text-brand-600 transition-colors">
              {project_name}
            </Link>

            {{/* Center nav — desktop */}}
            <nav className="hidden lg:flex items-center gap-7 flex-1 justify-center">
              {{NAV_ITEMS.map(({{ to, label }}) => (
                <Link key={{to}} to={{to}}
                  className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors relative group
                    [&.active]:text-brand-600 [&.active]:font-semibold">
                  {{label}}
                  <span className="absolute -bottom-1 left-0 h-0.5 w-0 bg-brand-600 transition-all duration-200 group-hover:w-full group-[&.active]:w-full rounded-full" />
                </Link>
              ))}}
            </nav>

            {{/* Right actions */}}
            <div className="flex items-center gap-1">
              <button onClick={{() => setSearchOpen(v => !v)}}
                className="p-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                aria-label="Search">
                <Search size={{20}} />
              </button>
              <button className="hidden sm:block p-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                aria-label="Wishlist">
                <Heart size={{20}} />
              </button>
              <Link to="/carts" className="relative p-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                aria-label="Cart">
                <ShoppingCart size={{20}} />
                {{cartCount > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 h-5 w-5 flex items-center justify-center rounded-full bg-brand-600 text-[10px] font-bold text-white shadow">
                    {{cartCount > 9 ? '9+' : cartCount}}
                  </span>
                )}}
              </Link>
              <button onClick={{handleLogout}}
                className="hidden sm:flex items-center gap-1.5 ml-1 px-3 py-1.5 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                aria-label="Account">
                <User size={{16}} />
                Account
              </button>
              <button className="lg:hidden p-2 text-gray-500 hover:bg-gray-100 rounded-lg ml-1"
                onClick={{() => setMobileOpen(v => !v)}} aria-label="Menu">
                {{mobileOpen ? <X size={{22}} /> : <Menu size={{22}} />}}
              </button>
            </div>
          </div>
        </div>

        {{/* Search bar */}}
        {{searchOpen && (
          <div className="border-t border-gray-100 px-4 py-3 bg-white animate-in fade-in duration-150">
            <div className="max-w-2xl mx-auto flex items-center gap-3 bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus-within:border-brand-400 focus-within:ring-2 focus-within:ring-brand-100 transition-all">
              <Search size={{16}} className="text-gray-400 shrink-0" />
              <input autoFocus placeholder="Search products, categories..."
                className="flex-1 bg-transparent text-sm text-gray-900 placeholder-gray-400 focus:outline-none"
                onKeyDown={{e => e.key === 'Escape' && setSearchOpen(false)}} />
              <button onClick={{() => setSearchOpen(false)}} className="text-gray-400 hover:text-gray-600">
                <X size={{16}} />
              </button>
            </div>
          </div>
        )}}

        {{/* Mobile nav */}}
        {{mobileOpen && (
          <div className="lg:hidden border-t border-gray-100 bg-white px-4 pb-4">
            {{NAV_ITEMS.map(({{ to, label }}) => (
              <Link key={{to}} to={{to}} onClick={{() => setMobileOpen(false)}}
                className="block py-3 border-b border-gray-50 text-base font-medium text-gray-700 hover:text-brand-600 transition-colors">
                {{label}}
              </Link>
            ))}}
            <button onClick={{handleLogout}} className="mt-3 flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700">
              <User size={{16}} /> Account / Sign Out
            </button>
          </div>
        )}}
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      {{/* ── Rich footer ── */}}
      <footer className="bg-gray-900 text-gray-400 mt-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-14 pb-8">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-10 mb-12">
            {{/* Brand column */}}
            <div>
              <span className="text-xl font-extrabold text-white block mb-3">{project_name}</span>
              <p className="text-sm leading-relaxed mb-5">
                Curated quality. Delivered with care. Your go-to destination for authentic craftsmanship and thoughtful design.
              </p>
              <div className="flex gap-2">
                {{['𝕏', 'f', 'in', '▶'].map(s => (
                  <button key={{s}} className="w-9 h-9 rounded-full bg-gray-800 hover:bg-brand-600 flex items-center justify-center text-xs font-bold text-gray-300 hover:text-white transition-all">
                    {{s}}
                  </button>
                ))}}
              </div>
            </div>
            {{/* Shop links */}}
            <div>
              <h4 className="text-white font-semibold text-xs uppercase tracking-widest mb-4">Shop</h4>
              <ul className="space-y-2.5 text-sm">
                {{NAV_ITEMS.slice(0, 6).map(({{ to, label }}) => (
                  <li key={{to}}>
                    <Link to={{to}} className="hover:text-white hover:translate-x-0.5 transition-all inline-block">{{label}}</Link>
                  </li>
                ))}}
              </ul>
            </div>
            {{/* Help links */}}
            <div>
              <h4 className="text-white font-semibold text-xs uppercase tracking-widest mb-4">Help</h4>
              <ul className="space-y-2.5 text-sm">
                {{FOOTER_HELP.map(l => (
                  <li key={{l}}><a href="#" className="hover:text-white transition-colors">{{l}}</a></li>
                ))}}
              </ul>
            </div>
            {{/* Newsletter */}}
            <div>
              <h4 className="text-white font-semibold text-xs uppercase tracking-widest mb-4">Stay in the Loop</h4>
              <p className="text-sm mb-4">New arrivals, exclusive deals, and insider stories. No spam, ever.</p>
              <div className="flex gap-2">
                <input type="email" placeholder="your@email.com"
                  className="flex-1 min-w-0 px-3 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-all" />
                <button className="shrink-0 px-4 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-sm font-semibold transition-colors">
                  Join
                </button>
              </div>
              <p className="text-xs mt-2 text-gray-600">By subscribing you agree to our Privacy Policy.</p>
            </div>
          </div>

          <div className="border-t border-gray-800 pt-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs">
            <p>&copy; {{new Date().getFullYear()}} {project_name}. All rights reserved.</p>
            <div className="flex flex-wrap items-center gap-4">
              {{['Privacy Policy', 'Terms of Service', 'Cookie Settings'].map(l => (
                <a key={{l}} href="#" className="hover:text-white transition-colors">{{l}}</a>
              ))}}
              <div className="flex items-center gap-1.5 ml-2">
                {{PAYMENT_METHODS.map(p => (
                  <span key={{p}} className="bg-gray-800 border border-gray-700 px-2 py-0.5 rounded text-[10px] font-mono text-gray-400">{{p}}</span>
                ))}}
              </div>
            </div>
          </div>
        </div>
      </footer>
    </div>
  )
}}
"""

    # Default admin sidebar layout
    icons_str = ", ".join(sorted(icons_needed))
    nav_items_admin: List[str] = [
        "  { to: '/' as const, label: 'Dashboard', Icon: LayoutDashboard },",
    ]
    for ent in entities:
        table = ent["table"]
        label = to_label(table)
        icon = entity_icon(table)
        route_path = f"/{table.replace('_', '-')}"
        nav_items_admin.append(f"  {{ to: '{route_path}' as const, label: '{label}', Icon: {icon} }},")

    nav_items_str = "\n".join(nav_items_admin)

    return f"""\
// Auto-generated by AetherOS p05_frontend
import {{ useState, useEffect }} from 'react'
import {{ Link, useRouter, Outlet }} from '@tanstack/react-router'
import {{ clearToken }} from '../lib/auth'
import {{ {icons_str}, Moon, Sun }} from 'lucide-react'

const NAV_ITEMS = [
{nav_items_str}
]

export function Layout() {{
  const router = useRouter()
  const handleLogout = () => {{
    clearToken()
    router.navigate({{ to: '/login' }})
  }}

  // Class-based dark mode — persisted to localStorage
  const [darkMode, setDarkMode] = useState<boolean>(() => {{
    if (typeof window === 'undefined') return false
    const stored = localStorage.getItem('theme')
    if (stored) return stored === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  }})

  useEffect(() => {{
    if (darkMode) {{
      document.documentElement.classList.add('dark')
      localStorage.setItem('theme', 'dark')
    }} else {{
      document.documentElement.classList.remove('dark')
      localStorage.setItem('theme', 'light')
    }}
  }}, [darkMode])

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
      <aside className="w-64 bg-gray-900 dark:bg-gray-950 text-white flex flex-col border-r border-gray-700 dark:border-gray-800">
        <div className="p-6 border-b border-gray-700 dark:border-gray-800 flex items-center justify-between">
          <h1 className="text-xl font-bold text-white">{project_name}</h1>
          <button
            onClick={{() => setDarkMode(d => !d)}}
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
            aria-label="Toggle dark mode"
            title={{darkMode ? 'Switch to light mode' : 'Switch to dark mode'}}
          >
            {{darkMode ? <Sun size={{16}} /> : <Moon size={{16}} />}}
          </button>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {{NAV_ITEMS.map(({{ to, label, Icon }}) => (
            <Link
              key={{to}}
              to={{to}}
              className="flex items-center gap-3 px-4 py-2.5 rounded-lg text-gray-300 hover:bg-gray-800 hover:text-white transition-colors [&.active]:bg-brand-600 [&.active]:text-white"
            >
              <Icon size={{18}} />
              {{label}}
            </Link>
          ))}}
        </nav>
        <button
          onClick={{handleLogout}}
          className="flex items-center gap-3 px-8 py-4 text-gray-400 hover:text-white border-t border-gray-700 dark:border-gray-800"
        >
          <LogOut size={{18}} />
          Logout
        </button>
      </aside>
      <main className="flex-1 overflow-auto bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
        <Outlet />
      </main>
    </div>
  )
}}
"""


def _generate_data_table() -> str:
    return """\
// Auto-generated by AetherOS p05_frontend
import { useState } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { ChevronUp, ChevronDown } from 'lucide-react'

interface Props<T> {
  data: T[]
  columns: ColumnDef<T>[]
  isLoading?: boolean
}

export function DataTable<T>({ data, columns, isLoading }: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [globalFilter, setGlobalFilter] = useState('')

  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  })

  if (isLoading) {
    return (
      <div role="status" aria-label="Loading data" className="space-y-3">
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} className="h-12 bg-gray-100 rounded-lg animate-pulse" />
        ))}
        <span className="sr-only">Loading…</span>
      </div>
    )
  }

  return (
    <div>
      <input
        value={globalFilter}
        onChange={e => setGlobalFilter(e.target.value)}
        placeholder="Search..."
        className="mb-4 w-full max-w-sm px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500"
        aria-label="Search records"
      />
      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
        <table className="w-full text-sm" aria-label="Data table">
          <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
            {table.getHeaderGroups().map(hg => (
              <tr key={hg.id}>
                {hg.headers.map(header => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-300 cursor-pointer hover:text-gray-900 dark:hover:text-gray-100 select-none"
                    aria-label={`Sort by ${header.column.columnDef.header}`}
                  >
                    <div className="flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() === 'asc' ? (
                        <ChevronUp size={14} />
                      ) : header.column.getIsSorted() === 'desc' ? (
                        <ChevronDown size={14} />
                      ) : null}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map(row => (
              <tr key={row.id} className="border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                {row.getVisibleCells().map(cell => (
                  <td key={cell.id} className="px-4 py-3 text-gray-700 dark:text-gray-200">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {table.getRowModel().rows.length === 0 && (
          <div className="text-center py-12 text-gray-400 dark:text-gray-500">No records found</div>
        )}
      </div>
      <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
        {table.getFilteredRowModel().rows.length} records
      </p>
    </div>
  )
}
"""


def _generate_crud_modal() -> str:
    return """\
// Auto-generated by AetherOS p05_frontend
import { useEffect, useId, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { X } from 'lucide-react'
import { apiClient } from '../lib/api'

export interface FieldDef {
  name: string
  label: string
  type: 'text' | 'email' | 'tel' | 'date' | 'number' | 'textarea' | 'select' | 'fk-select'
  required?: boolean
  options?: { value: string; label: string }[]
  /** For fk-select: the related entity endpoint path, e.g. "/categories" */
  fkEndpoint?: string
  /** For fk-select: key to use as option label from fetched records */
  fkLabelKey?: string
}

interface Props<T extends Record<string, unknown>> {
  isOpen: boolean
  onClose: () => void
  onSubmit: (data: T) => void
  initialValues?: Partial<T>
  fields: FieldDef[]
  title: string
  isLoading?: boolean
  /** fkConfig: maps field name → entity endpoint path for auto-populated FK dropdowns */
  fkConfig?: Record<string, string>
}

export function CrudModal<T extends Record<string, unknown>>({
  isOpen,
  onClose,
  onSubmit,
  initialValues,
  fields,
  title,
  isLoading,
  fkConfig,
}: Props<T>) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<T>()

  const [fkOptions, setFkOptions] = useState<Record<string, { value: string; label: string }[]>>({})

  useEffect(() => {
    if (isOpen) reset((initialValues ?? {}) as T)
  }, [isOpen, initialValues, reset])

  // Fetch FK options when the modal opens
  useEffect(() => {
    if (!isOpen) return
    const fkFields = fields.filter(f => f.type === 'fk-select' || (f.name.endsWith('_id') && fkConfig?.[f.name]))
    fkFields.forEach(field => {
      const endpoint = field.fkEndpoint ?? fkConfig?.[field.name]
      if (!endpoint) return
      const labelKey = field.fkLabelKey ?? 'name'
      // the client's baseURL already ends in /api: a configured "/api/x" would be requested as /api/api/x.
      // 200 is the most rows a list endpoint returns per page.
      apiClient.get<{ items?: unknown[]; [k: string]: unknown }>(endpoint.replace(/^\\/api(?=\\/)/, ''), { params: { page: 1, page_size: 200 } })
        .then(res => {
          const records: unknown[] = (res.data as any)?.items ?? (Array.isArray(res.data) ? res.data : [])
          const opts = records.map((r: any) => ({
            value: String(r.id ?? r._id ?? ''),
            label: String(r[labelKey] ?? r.name ?? r.title ?? r.email ?? r.id ?? ''),
          }))
          setFkOptions(prev => ({ ...prev, [field.name]: opts }))
        })
        .catch(() => {})
    })
  }, [isOpen, fields, fkConfig])

  // Accessibility: dialog semantics, labels tied to their fields, focus moves into the dialog, Tab stays inside it,
  // Escape closes it and focus returns to what opened it.
  const uid = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!isOpen) return
    const opener = document.activeElement as HTMLElement | null
    const node = dialogRef.current
    const focusable = () => Array.from(node?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])') ?? [])
    ;(node?.querySelector<HTMLElement>('input, select, textarea') ?? focusable()[0])?.focus()
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return }
      if (e.key !== 'Tab') return
      const items = focusable()
      if (items.length === 0) return
      const first = items[0], last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => { document.removeEventListener('keydown', onKeyDown); opener?.focus() }
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={`${uid}-title`}
           className="bg-white dark:bg-gray-900 rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-gray-700">
          <h2 id={`${uid}-title`} className="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X size={20} aria-hidden="true" />
          </button>
        </div>
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="flex-1 overflow-y-auto p-6 space-y-4"
        >
          {fields.map(f => {
            // Determine if this is a FK select field
            const isFkSelect = f.type === 'fk-select' || (f.name.endsWith('_id') && !!(fkConfig?.[f.name] || f.fkEndpoint))
            const resolvedOptions = isFkSelect ? (fkOptions[f.name] ?? []) : (f.options ?? [])
            return (
              <div key={f.name}>
                <label htmlFor={`${uid}-${f.name}`} className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {f.label}
                  {f.required && <span className="text-red-500 ml-1">*</span>}
                </label>
                {f.type === 'textarea' ? (
                  <textarea
                    id={`${uid}-${f.name}`}
                    {...register(f.name as keyof T extends string ? keyof T : never, {
                      required: f.required ? `${f.label} is required` : false,
                    } as any)}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-brand-500"
                    rows={3}
                  />
                ) : f.type === 'select' || isFkSelect ? (
                  <select
                    id={`${uid}-${f.name}`}
                    {...register(f.name as any, { required: f.required ? `${f.label} is required` : false })}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-brand-500"
                  >
                    <option value="">
                      {isFkSelect && resolvedOptions.length === 0 ? 'Loading...' : 'Select...'}
                    </option>
                    {resolvedOptions.map(o => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    id={`${uid}-${f.name}`}
                    type={f.type}
                    {...register(f.name as any, {
                      required: f.required ? `${f.label} is required` : false,
                      ...(f.type === 'email' ? {
                        pattern: {
                          value: /\\S+@\\S+\\.\\S+/,
                          message: 'Invalid email address',
                        },
                      } : {}),
                    })}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-brand-500"
                  />
                )}
                {errors[f.name as keyof T] && (
                  <p role="alert" className="text-xs text-red-500 mt-1">
                    {(errors[f.name as keyof T] as { message?: string })?.message ?? `${f.label} is required`}
                  </p>
                )}
              </div>
            )
          })}
          <div className="flex justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
            >
              {isLoading ? 'Saving...' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
"""


def _generate_toaster() -> str:
    return """\
// Auto-generated by AetherOS p05_frontend
// Simple toast notification component using state
import { useState, useCallback, createContext, useContext } from 'react'
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react'

interface Toast {
  id: string
  message: string
  type: 'success' | 'error' | 'info'
}

interface ToastContextValue {
  toast: (message: string, type?: Toast['type']) => void
}

const ToastContext = createContext<ToastContextValue>({ toast: () => undefined })

export function useToast() {
  return useContext(ToastContext)
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const toast = useCallback((message: string, type: Toast['type'] = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3500)
  }, [])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map(t => (
          <div
            key={t.id}
            className={`flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg text-sm text-white min-w-[260px] ${
              t.type === 'success' ? 'bg-green-600'
              : t.type === 'error' ? 'bg-red-600'
              : 'bg-gray-800'
            }`}
          >
            {t.type === 'success' ? <CheckCircle size={16} />
              : t.type === 'error' ? <AlertCircle size={16} />
              : <Info size={16} />}
            <span className="flex-1">{t.message}</span>
            <button
              onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))}
              className="text-white/70 hover:text-white"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
"""


def _generate_vitest_config() -> str:
    return """\
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
    },
  },
})
"""


def _generate_test_setup() -> str:
    return """\
import '@testing-library/jest-dom'
"""


def _generate_login_test(project_name: str) -> str:
    return """\
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { LoginPage } from '../pages/LoginPage'

describe('LoginPage', () => {
  it('renders login form', () => {
    render(<LoginPage />)
    expect(screen.getByRole('button', { name: /sign in|log in|login/i })).toBeInTheDocument()
  })

  it('shows email and password fields', () => {
    render(<LoginPage />)
    expect(screen.getByPlaceholderText(/email/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/password/i)).toBeInTheDocument()
  })
})
"""


def _generate_dashboard_test() -> str:
    return """\
import { render } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Mock the api module to match apiClient export
vi.mock('../lib/api', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}))

describe('Dashboard', () => {
  it('renders without crashing', async () => {
    const { default: Dashboard } = await import('../pages/Dashboard')
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <QueryClientProvider client={qc}><Dashboard /></QueryClientProvider>
    )
    expect(container).toBeTruthy()
  })
})
"""


def _generate_error_boundary() -> str:
    return """\
import { Component, ErrorInfo, ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Optional custom fallback UI. When omitted the built-in error card is shown. */
  fallback?: ReactNode
}
interface State { hasError: boolean; error: Error | null }

/**
 * Catches render-time errors anywhere in the subtree and shows a recovery UI.
 * Wrap the router or any page section where you want isolated error handling.
 *
 * Usage:
 *   <ErrorBoundary fallback={<p>Custom error UI</p>}>
 *     <MyComponent />
 *   </ErrorBoundary>
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return <>{this.props.fallback}</>
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
          <div className="text-center p-8 max-w-md">
            <div className="text-6xl mb-4">⚠️</div>
            <h1 className="text-2xl font-bold text-gray-900 mb-2">Something went wrong</h1>
            <p className="text-gray-500 mb-6">{this.state.error?.message ?? 'An unexpected error occurred.'}</p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              Try again
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
"""


def _generate_not_found_page() -> str:
    return """\
import { Link } from '@tanstack/react-router'

export function NotFoundPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center p-8 max-w-md">
        <div className="text-8xl font-black text-gray-200 mb-4">404</div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Page not found</h1>
        <p className="text-gray-500 mb-6">The page you're looking for doesn't exist or has been moved.</p>
        <Link
          to="/"
          className="inline-block px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          Back to home
        </Link>
      </div>
    </div>
  )
}

export default NotFoundPage
"""


def _generate_pagination() -> str:
    """Generate src/components/Pagination.tsx — page navigator for list views."""
    return """\
// Auto-generated by AetherOS p05_frontend
interface PaginationProps {
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number) => void
}

/**
 * Renders Previous / numbered page buttons / Next.
 * Shows at most 7 page numbers with ellipsis for large sets.
 */
export function Pagination({ total, page, pageSize, onPageChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  if (totalPages <= 1) return null

  // Build visible page numbers with ellipsis
  const getPages = (): (number | '...')[] => {
    if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1)
    const pages: (number | '...')[] = [1]
    if (page > 3) pages.push('...')
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) {
      pages.push(i)
    }
    if (page < totalPages - 2) pages.push('...')
    pages.push(totalPages)
    return pages
  }

  const btn = 'px-3 py-1.5 text-sm rounded-lg border transition-colors disabled:opacity-40 disabled:cursor-not-allowed'
  const active = 'bg-brand-600 text-white border-brand-600 font-semibold'
  const inactive = 'bg-white text-gray-700 border-gray-200 hover:border-brand-400 hover:text-brand-600'

  return (
    <div className="flex items-center justify-between mt-4 px-1">
      <p className="text-xs text-gray-400">
        {Math.min((page - 1) * pageSize + 1, total)}–{Math.min(page * pageSize, total)} of {total}
      </p>
      <div className="flex items-center gap-1">
        <button
          className={`${btn} ${inactive}`}
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          ‹ Prev
        </button>
        {getPages().map((p, i) =>
          p === '...' ? (
            <span key={`ellipsis-${i}`} className="px-2 text-gray-400 text-sm select-none">…</span>
          ) : (
            <button
              key={p}
              onClick={() => onPageChange(p as number)}
              className={`${btn} ${p === page ? active : inactive}`}
              aria-label={`Page ${p}`}
              aria-current={p === page ? 'page' : undefined}
            >
              {p}
            </button>
          )
        )}
        <button
          className={`${btn} ${inactive}`}
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          aria-label="Next page"
        >
          Next ›
        </button>
      </div>
    </div>
  )
}
"""


def _generate_skeleton() -> str:
    """Generate src/components/Skeleton.tsx — animated placeholders for loading states."""
    return """\
// Auto-generated by AetherOS p05_frontend

/**
 * TableSkeleton: shows animated placeholder rows while list data loads.
 * Use in place of the table when React Query's isLoading=true.
 */
export const TableSkeleton = ({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) => (
  <div className="animate-pulse" aria-label="Loading data" role="status">
    {/* Header row */}
    <div className="flex gap-4 py-3 border-b border-gray-200 mb-1">
      {Array.from({ length: cols }).map((_, j) => (
        <div key={j} className="h-3 bg-gray-300 rounded w-20" />
      ))}
    </div>
    {/* Data rows */}
    {Array.from({ length: rows }).map((_, i) => (
      <div key={i} className="flex gap-4 py-3 border-b border-gray-100">
        {Array.from({ length: cols }).map((_, j) => (
          <div
            key={j}
            className="h-4 bg-gray-100 rounded flex-1"
            style={{ animationDelay: `${i * 60 + j * 20}ms` }}
          />
        ))}
      </div>
    ))}
    <span className="sr-only">Loading…</span>
  </div>
)

/**
 * CardSkeleton: animated placeholder for a single record card / detail panel.
 */
export const CardSkeleton = () => (
  <div className="animate-pulse space-y-4 p-4 bg-white rounded-xl border border-gray-100">
    <div className="h-6 bg-gray-200 rounded w-3/4" />
    <div className="h-4 bg-gray-100 rounded w-1/2" />
    <div className="h-4 bg-gray-100 rounded w-2/3" />
    <div className="h-4 bg-gray-100 rounded w-1/3" />
  </div>
)

/**
 * FormSkeleton: animated placeholder while form initialValues are loading.
 */
export const FormSkeleton = ({ fields = 4 }: { fields?: number }) => (
  <div className="animate-pulse space-y-5 p-6">
    {Array.from({ length: fields }).map((_, i) => (
      <div key={i} className="space-y-1.5">
        <div className="h-3 bg-gray-200 rounded w-24" />
        <div className="h-9 bg-gray-100 rounded-lg w-full" />
      </div>
    ))}
  </div>
)
"""


def _generate_role_guard() -> str:
    """Generate src/components/RoleGuard.tsx — conditionally renders children by user role.

    Reads role from the JWT payload stored in localStorage so no extra API call is needed.
    """
    return """\
// Auto-generated by AetherOS p05_frontend
import { ReactNode } from 'react'
import { getToken } from '../lib/auth'

/**
 * Decode the JWT stored in localStorage and return the user's role string.
 * Returns null when not logged in or when the token is malformed.
 */
function _getRole(): string | null {
  try {
    const t = getToken()
    if (!t) return null
    const payload = JSON.parse(atob(t.split('.')[1]))
    return (payload?.role ?? payload?.roles?.[0] ?? 'user') as string
  } catch {
    return null
  }
}

interface RoleGuardProps {
  /** Roles that are allowed to see the children. */
  allowedRoles: string[]
  children: ReactNode
  /** Optional fallback content shown when the role check fails (default: nothing). */
  fallback?: ReactNode
}

/**
 * Wraps any content that should only be visible to specific roles.
 *
 * Usage:
 *   <RoleGuard allowedRoles={['admin', 'owner']}>
 *     <DeleteButton />
 *   </RoleGuard>
 */
export function RoleGuard({ allowedRoles, children, fallback = null }: RoleGuardProps) {
  const role = _getRole()
  if (!role || !allowedRoles.includes(role)) return <>{fallback}</>
  return <>{children}</>
}
"""


def _generate_frontend_readme(project_name: str) -> str:
    return f"""\
# {project_name} Frontend

Auto-generated React 18 + Vite 5 + TypeScript frontend by AetherOS.

## Quick Start

```bash
cp .env.example .env
npm install
npm run dev
```

Runs on http://localhost:3000

## Stack

- React 18 + TypeScript
- Vite 5 (bundler)
- TanStack Router (routing)
- TanStack Query (data fetching)
- Tailwind CSS (styling)
- shadcn/ui components

## Scripts

| Command | Description |
|---|---|
| npm run dev | Dev server with HMR |
| npm run build | Production build |
| npm run test | Run Vitest tests |
| npm run test:coverage | Coverage report |
| npm run lint | ESLint |

## Environment Variables

Copy `.env.example` to `.env` and set:
- `VITE_API_URL` — backend API base URL
"""


def _generate_login_page(project_name: str, layout_mode: str = "admin") -> str:
    access_token = "demo"
    if layout_mode == "dual":
        return f"""\
// Auto-generated by AetherOS p05_frontend — dual portal login
import {{ useState }} from 'react'
import {{ useNavigate }} from '@tanstack/react-router'
import {{ authApi }} from '../lib/api'
import {{ setToken }} from '../lib/auth'

function _getRole(token: string): string {{
  try {{ return JSON.parse(atob(token.split('.')[1]))?.role ?? 'user' }}
  catch {{ return 'user' }}
}}

export function LoginPage() {{
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {{
    e.preventDefault()
    setLoading(true)
    setError('')
    try {{
      const {{ access_token, refresh_token }} = await authApi.login(email, password)
      setToken(access_token, refresh_token)

      const role = _getRole(access_token)
      // Route admins to the management portal, everyone else to the customer portal
      navigate({{ to: role === 'admin' ? '/admin' : '/' }})
    }} catch {{
      setError('Invalid email or password')
    }} finally {{
      setLoading(false)
    }}
  }}

  return (
    <div className="min-h-screen flex">
      {{/* Hero / branding panel — hidden on mobile */}}
      <div className="hidden lg:flex lg:w-1/2 bg-brand-600 flex-col items-center justify-center p-12 text-white">
        <div className="max-w-md text-center space-y-6">
          <h1 className="text-4xl font-extrabold">{project_name}</h1>
          <p className="text-brand-100 text-lg">
            Sign in to access your account and everything {project_name} has to offer.
          </p>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div className="bg-brand-700/50 rounded-xl p-4">
              <p className="font-bold text-white text-base mb-1">Members</p>
              <p className="text-brand-200">Book, manage and track — all in one place.</p>
            </div>
            <div className="bg-brand-700/50 rounded-xl p-4">
              <p className="font-bold text-white text-base mb-1">Admins</p>
              <p className="text-brand-200">Full management portal with analytics.</p>
            </div>
          </div>
        </div>
      </div>
      {{/* Login form panel */}}
      <div className="flex-1 flex items-center justify-center bg-gray-50 p-8">
        <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-md">
          <div className="lg:hidden mb-6 text-center">
            <h1 className="text-2xl font-bold text-brand-600">{project_name}</h1>
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-1">Welcome back</h2>
          <p className="text-gray-500 mb-8 text-sm">Sign in to your account to continue.</p>
          <form onSubmit={{handleSubmit}} className="space-y-4">
            <div>
              <label htmlFor="login-email" className="block text-sm font-medium text-gray-700 mb-1">Email address</label>
              <input id="login-email" type="email" value={{email}} onChange={{e => setEmail(e.target.value)}} required
                placeholder="you@example.com"
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 text-sm" />
            </div>
            <div>
              <label htmlFor="login-password" className="block text-sm font-medium text-gray-700 mb-1">Password</label>
              <input id="login-password" type="password" value={{password}} onChange={{e => setPassword(e.target.value)}} required
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 text-sm" />
            </div>
            {{error && <p className="text-sm text-red-500 bg-red-50 px-3 py-2 rounded-lg">{{error}}</p>}}
            <button type="submit" disabled={{loading}}
              className="w-full py-3 bg-brand-600 text-white rounded-xl hover:bg-brand-700 disabled:opacity-50 font-semibold text-sm transition-colors">
              {{loading ? 'Signing in…' : 'Sign in'}}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}}
"""

    if layout_mode == "storefront":
        return f"""\
// Auto-generated by AetherOS p05_frontend (storefront login)
import {{ useState }} from 'react'
import {{ useNavigate }} from '@tanstack/react-router'
import {{ authApi }} from '../lib/api'
import {{ setToken }} from '../lib/auth'

export function LoginPage() {{
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {{
    e.preventDefault()
    setLoading(true)
    setError('')
    try {{
      const {{ access_token, refresh_token }} = await authApi.login(email, password)
      setToken(access_token, refresh_token)

      navigate({{ to: '/' }})
    }} catch {{
      setError('Invalid email or password')
    }} finally {{
      setLoading(false)
    }}
  }}

  return (
    <div className="min-h-screen bg-gradient-to-br from-brand-50 to-brand-100 flex">
      {{/* Branding / Hero panel */}}
      <div className="hidden lg:flex lg:w-1/2 bg-brand-600 flex-col items-center justify-center p-12 text-white">
        <div className="max-w-md text-center">
          <h1 className="text-4xl font-extrabold mb-4">{project_name}</h1>
          <p className="text-brand-100 text-lg mb-8">
            Welcome back! Sign in to access your account and continue shopping.
          </p>
        </div>
      </div>
      {{/* Login form panel */}}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-md">
          <div className="lg:hidden mb-6 text-center">
            <h1 className="text-2xl font-bold text-brand-600">{project_name}</h1>
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-1">Sign in</h2>
          <p className="text-gray-500 mb-8">Welcome back — we missed you!</p>
          <form onSubmit={{handleSubmit}} className="space-y-4">
            <div>
              <label htmlFor="login-email" className="block text-sm font-medium text-gray-700 mb-1">Email address</label>
              <input
                id="login-email" type="email"
                value={{email}}
                onChange={{e => setEmail(e.target.value)}}
                required
                placeholder="you@example.com"
                className="w-full px-3 py-2.5 border rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
              />
            </div>
            <div>
              <label htmlFor="login-password" className="block text-sm font-medium text-gray-700 mb-1">Password</label>
              <input
                id="login-password" type="password"
                value={{password}}
                onChange={{e => setPassword(e.target.value)}}
                required
                className="w-full px-3 py-2.5 border rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
              />
            </div>
            {{error && <p className="text-sm text-red-500">{{error}}</p>}}
            <button
              type="submit"
              disabled={{loading}}
              className="w-full py-3 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-semibold text-base transition-colors"
            >
              {{loading ? 'Signing in...' : 'Sign in to your account'}}
            </button>
          </form>
          <p className="mt-6 text-center text-sm text-gray-500">
            Don't have an account?{{' '}}
            <a href="#" className="text-brand-600 font-medium hover:underline">Create one free</a>
          </p>
        </div>
      </div>
    </div>
  )
}}
"""

    # Default admin login page
    return f"""\
// Auto-generated by AetherOS p05_frontend
import {{ useState }} from 'react'
import {{ useNavigate }} from '@tanstack/react-router'
import {{ authApi }} from '../lib/api'
import {{ setToken }} from '../lib/auth'

export function LoginPage() {{
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {{
    e.preventDefault()
    setLoading(true)
    setError('')
    try {{
      const {{ access_token, refresh_token }} = await authApi.login(email, password)
      setToken(access_token, refresh_token)

      navigate({{ to: '/' }})
    }} catch {{
      setError('Invalid email or password')
    }} finally {{
      setLoading(false)
    }}
  }}

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-brand-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-brand-600 rounded-xl mb-4">
            <span className="text-white font-extrabold text-xl">{project_name[0] if project_name else 'A'}</span>
          </div>
          <h1 className="text-2xl font-extrabold text-gray-900">{project_name}</h1>
          <p className="text-gray-500 mt-1 text-sm">Sign in to your admin account</p>
        </div>
        <form onSubmit={{handleSubmit}} className="space-y-4">
          <div>
            <label htmlFor="login-email" className="block text-sm font-medium text-gray-700 mb-1">Email address</label>
            <input
              id="login-email" type="email"
              value={{email}}
              onChange={{e => setEmail(e.target.value)}}
              required
              placeholder="you@example.com"
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 text-sm"
            />
          </div>
          <div>
            <label htmlFor="login-password" className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              id="login-password" type="password"
              value={{password}}
              onChange={{e => setPassword(e.target.value)}}
              required
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-brand-500 text-sm"
            />
          </div>
          {{error && <p className="text-sm text-red-500 bg-red-50 px-3 py-2 rounded-lg">{{error}}</p>}}
          <button
            type="submit"
            disabled={{loading}}
            className="w-full py-3 bg-brand-600 text-white rounded-xl hover:bg-brand-700 disabled:opacity-50 font-semibold text-sm transition-colors"
          >
            {{loading ? 'Signing in…' : 'Sign in'}}
          </button>
        </form>
      </div>
    </div>
  )
}}
"""


def _generate_dashboard(entities: List[dict], route_map: Dict[str, str], domain: str = "saas", ui_theme: str = "default") -> str:
    """Generate src/pages/Dashboard.tsx — storefront homepage for ecommerce, stat cards for others."""
    if domain in ("ecommerce", "marketplace"):
        return _generate_storefront_home(entities, route_map, domain=domain)

    # Domain-appropriate page background and text colours
    _theme_bg: Dict[str, str] = {
        "healthcare":  "bg-teal-50",
        "fintech":     "bg-slate-900",
        "education":   "bg-sky-50",
        "gym_fitness": "bg-red-50",
        "fitness":     "bg-red-50",
        "real_estate": "bg-emerald-50",
        "hospitality": "bg-amber-50",
        "restaurant":  "bg-orange-50",
        "food":        "bg-orange-50",
        "logistics":   "bg-slate-50",
        "iot":         "bg-slate-900",
        "security":    "bg-slate-900",
        "hrm":         "bg-indigo-50",
        "crm":         "bg-indigo-50",
        "analytics":   "bg-indigo-50",
        "saas":        "bg-violet-50",
        "sports":      "bg-green-50",
        "library":     "bg-stone-50",
    }
    _theme_heading: Dict[str, str] = {
        "healthcare":  "text-teal-900",
        "fintech":     "text-yellow-300",
        "education":   "text-sky-900",
        "gym_fitness": "text-red-900",
        "fitness":     "text-red-900",
        "real_estate": "text-emerald-900",
        "hospitality": "text-amber-900",
        "restaurant":  "text-orange-900",
        "food":        "text-orange-900",
        "logistics":   "text-slate-900",
        "iot":         "text-cyan-300",
        "security":    "text-red-300",
        "hrm":         "text-indigo-900",
        "crm":         "text-indigo-900",
        "analytics":   "text-indigo-900",
        "saas":        "text-violet-900",
        "sports":      "text-green-900",
        "library":     "text-stone-900",
    }
    _theme_sub: Dict[str, str] = {
        "fintech": "text-slate-400", "iot": "text-slate-400", "security": "text-slate-400",
    }
    _theme_card: Dict[str, str] = {
        "healthcare":  "bg-white border-teal-100",
        "fintech":     "bg-slate-800 border-slate-700",
        "education":   "bg-white border-sky-100",
        "gym_fitness": "bg-white border-red-100",
        "fitness":     "bg-white border-red-100",
        "real_estate": "bg-white border-emerald-100",
        "hospitality": "bg-white border-amber-100",
        "restaurant":  "bg-white border-orange-100",
        "food":        "bg-white border-orange-100",
        "logistics":   "bg-white border-slate-200",
        "iot":         "bg-slate-800 border-slate-700",
        "security":    "bg-slate-800 border-slate-700",
        "hrm":         "bg-white border-indigo-100",
        "crm":         "bg-white border-indigo-100",
        "analytics":   "bg-white border-indigo-100",
        "saas":        "bg-white border-violet-100",
        "sports":      "bg-white border-green-100",
        "library":     "bg-white border-stone-200",
    }
    _theme_stat_text: Dict[str, str] = {
        "fintech": "text-yellow-200", "iot": "text-cyan-200", "security": "text-red-200",
    }

    _eff_theme = ui_theme if ui_theme and ui_theme != "default" else domain
    page_bg    = _theme_bg.get(_eff_theme, "bg-gray-50")
    heading_cl = _theme_heading.get(_eff_theme, "text-gray-900")
    sub_cl     = _theme_sub.get(_eff_theme, "text-gray-500")
    card_cl    = _theme_card.get(_eff_theme, "bg-white border-gray-100")
    stat_cl    = _theme_stat_text.get(_eff_theme, "text-gray-900")

    query_lines: List[str] = []
    stat_cards: List[str] = []

    icons = ["BarChart3", "Users", "Activity", "TrendingUp", "Package", "FileText", "Calendar", "Database"]
    domain_labels = DOMAIN_STAT_LABELS.get(domain, DOMAIN_STAT_LABELS["saas"])

    for i, ent in enumerate(entities):
        table = ent["table"]
        camel = table[0].lower() + to_pascal_case(table)[1:]
        endpoint = route_map.get(table, f"/{table}")
        label = domain_labels[i] if i < len(domain_labels) else to_label(table)
        icon = icons[i % len(icons)]

        query_lines.append(
            f"  const {{ data: {camel}Data }} = useQuery({{\n"
            f"    queryKey: ['{table}'],\n"
            f"    queryFn: () => apiClient.get<{{items: unknown[]; total?: number}}>('{endpoint}').then(r => Array.isArray(r.data) ? r.data : (r.data?.items ?? [])),\n"
            f"  }})"
        )
        stat_cards.append(
            f"        <div className=\"{card_cl} rounded-2xl border p-6 shadow-sm hover:shadow-md transition-shadow\">\n"
            f"          <div className=\"flex items-center justify-between mb-3\">\n"
            f"            <p className=\"text-sm font-semibold text-brand-600 uppercase tracking-wide\">{label}</p>\n"
            f"            <div className=\"p-2 bg-brand-50 rounded-lg\">\n"
            f"              <{icon} size={{18}} className=\"text-brand-600\" />\n"
            f"            </div>\n"
            f"          </div>\n"
            f"          <p className=\"text-4xl font-bold {stat_cl}\">{{{camel}Data?.length ?? '—'}}</p>\n"
            f"          <p className=\"text-xs text-brand-400 mt-2\">Total {label.lower()}</p>\n"
            f"        </div>"
        )

    queries_str = "\n".join(query_lines)
    cards_str = "\n".join(stat_cards)
    used_icons = sorted(set(icons[i % len(icons)] for i in range(len(entities))))
    icons_import = ", ".join(used_icons) if used_icons else "BarChart3"

    return f"""\
// Auto-generated by AetherOS p05_frontend  (domain: {domain}, theme: {_eff_theme})
import {{ useQuery }} from '@tanstack/react-query'
import {{ {icons_import} }} from 'lucide-react'
import {{ apiClient }} from '../lib/api'

export default function Dashboard() {{
{queries_str}

  return (
    <div className="{page_bg} min-h-screen p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-3xl font-extrabold {heading_cl}">Dashboard</h1>
          <p className="{sub_cl} mt-1">Welcome back. Here's what's happening today.</p>
        </div>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
{cards_str}
        </div>
        {{/* DOMAIN_WIDGET_SLOT */}}
      </div>
    </div>
  )
}}
"""


def _generate_storefront_home(entities: List[dict], route_map: Dict[str, str], domain: str = "ecommerce") -> str:
    """Generate a full storefront homepage: hero, trust badges, live product grid."""
    _domain_hero_gradient = {
        "ecommerce":   "from-rose-900 via-pink-800 to-pink-600",
        "marketplace": "from-violet-900 via-purple-800 to-violet-600",
    }
    _hero_gradient = _domain_hero_gradient.get(domain, "from-gray-900 via-brand-900 to-brand-700")
    # Pick the most product-like entity as the primary showcase
    _product_keywords = ("product", "item", "goods", "service", "listing", "sku", "artifact", "piece")
    primary_entity = next(
        (e for e in entities if any(k in e["table"].lower() for k in _product_keywords)),
        entities[0] if entities else {"table": "products", "columns": []}
    )
    primary_table = primary_entity["table"]
    primary_endpoint = route_map.get(primary_table, f"/{primary_table}")
    primary_route = f"/{primary_table.replace('_', '-')}"

    # Build category nav from other entities (avoid backslash in f-string expressions)
    other_entities = [e for e in entities if e["table"] != primary_table][:5]
    _cat_parts: List[str] = []
    for _ce in other_entities:
        _ct = _ce["table"]
        _cl = to_label(_ct)
        _ce_emoji = entity_emoji(_ct)
        _cat_parts.append(
            f"            <a href='#{_ct}' className=\"group flex flex-col items-center gap-3 p-4 rounded-2xl bg-gray-50 hover:bg-brand-50 border border-transparent hover:border-brand-200 transition-all\">\n"
            f"              <div className=\"text-2xl\">{_ce_emoji}</div>\n"
            f"              <span className=\"text-xs font-semibold text-gray-700 group-hover:text-brand-700 text-center\">{_cl}</span>\n"
            f"            </a>"
        )
    category_links = "\n".join(_cat_parts)

    return f"""\
// Auto-generated by AetherOS p05_frontend — storefront homepage
import {{ useQuery }} from '@tanstack/react-query'
import {{ Link }} from '@tanstack/react-router'
import {{ apiClient }} from '../lib/api'
import {{ ArrowRight, Star, ShoppingCart, CheckCircle }} from 'lucide-react'

function StarRating({{ rating = 4.5 }}: {{ rating?: number }}) {{
  return (
    <div className="flex items-center gap-0.5">
      {{[1,2,3,4,5].map(s => (
        <Star key={{s}} size={{12}}
          className={{s <= Math.round(rating) ? 'fill-amber-400 text-amber-400' : 'text-gray-200'}} />
      ))}}
    </div>
  )
}}

function ProductCard({{ product, index }}: {{ product: any; index: number }}) {{
  const seed = product.id ?? index + 1
  const rawPrice = product.price ?? product.unit_price ?? product.amount ?? 0
  const price = typeof rawPrice === 'number' ? rawPrice : parseFloat(rawPrice) || 0
  const category = product.category ?? product.type ?? product.collection ?? 'Collection'
  const rating = typeof product.rating === 'number' ? product.rating : null   // no invented ratings

  return (
    <div className="group relative bg-white rounded-2xl overflow-hidden border border-gray-100 shadow-sm hover:shadow-2xl transition-all duration-300 hover:-translate-y-1 flex flex-col">
      {{/* Image */}}
      <div className="relative aspect-square bg-gradient-to-br from-gray-50 to-gray-100 overflow-hidden">
        {{(product.image_url ?? product.image ?? product.thumbnail)
          ? <img
              src={{product.image_url ?? product.image ?? product.thumbnail}}
              alt={{product.name ?? 'Product'}}
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
              loading="lazy"
              onError={{(e) => {{ (e.target as HTMLImageElement).style.display = 'none' }}}}
            />
          : <div aria-hidden="true" className="w-full h-full flex items-center justify-center text-5xl font-bold text-gray-300">{{String(product.name ?? product.title ?? '?').charAt(0).toUpperCase()}}</div>}}
        {{product.is_featured && (
          <span className="absolute top-3 left-3 bg-brand-600 text-white text-[10px] font-bold px-2.5 py-1 rounded-full uppercase tracking-wider">
            Featured
          </span>
        )}}
        {{product.stock_quantity === 0 && (
          <div className="absolute inset-0 bg-white/60 flex items-center justify-center">
            <span className="text-sm font-semibold text-gray-600">Out of Stock</span>
          </div>
        )}}
      </div>
      {{/* Content */}}
      <div className="p-4 flex flex-col flex-1">
        <p className="text-[11px] font-bold text-brand-600 uppercase tracking-wider mb-1">{{category}}</p>
        <h3 className="font-semibold text-gray-900 text-sm leading-snug mb-2 line-clamp-2 flex-1">
          {{product.name ?? product.title ?? 'Product'}}
        </h3>
        {{rating !== null && (
          <div className="flex items-center gap-2 mb-3">
            <StarRating rating={{rating}} />
            {{typeof product.review_count === 'number' && <span className="text-[11px] text-gray-400">({{product.review_count}})</span>}}
          </div>
        )}}
        <div className="flex items-center justify-between mt-auto">
          <div>
            <span className="text-lg font-bold text-gray-900">${{price > 0 ? price.toFixed(2) : '—'}}</span>
          </div>
          <button
            className="flex items-center gap-1.5 bg-brand-600 hover:bg-brand-700 active:scale-95 text-white px-3 py-1.5 rounded-xl text-sm font-semibold transition-all"
            disabled={{product.stock_quantity === 0}}
          >
            <ShoppingCart size={{14}} />
            Add
          </button>
        </div>
      </div>
    </div>
  )
}}

export default function Dashboard() {{
  const {{ data: raw, isLoading }} = useQuery({{
    queryKey: ['{primary_table}'],
    queryFn: () => apiClient.get('{primary_endpoint}').then(r => r.data),
    staleTime: 60_000,
  }})
  const products: any[] = Array.isArray(raw) ? raw : (raw?.items ?? raw?.data ?? [])

  return (
    <div className="min-h-screen bg-white">
      {{/* ── Hero Section ── */}}
      <section className="relative overflow-hidden bg-gradient-to-br {_hero_gradient} text-white">
        {{/* Subtle grid overlay */}}
        <div className="absolute inset-0 opacity-[0.07]"
          style={{{{ backgroundImage: 'repeating-linear-gradient(0deg,transparent,transparent 40px,#fff 40px,#fff 41px),repeating-linear-gradient(90deg,transparent,transparent 40px,#fff 40px,#fff 41px)' }}}} />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24 md:py-36">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 bg-white/10 backdrop-blur-sm border border-white/20 rounded-full px-4 py-1.5 mb-8">
              <CheckCircle size={{14}} className="text-green-400" />
              <span className="text-xs font-semibold tracking-wide">New Collection · Spring 2025</span>
            </div>
            <h1 className="text-5xl md:text-7xl font-extrabold leading-none tracking-tight mb-6">
              Discover<br />
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-200 to-white">
                Something
              </span><br />
              Beautiful
            </h1>
            <p className="text-lg md:text-xl text-gray-300 mb-10 leading-relaxed max-w-xl">
              Handcrafted with love. Every piece in our collection is thoughtfully designed and built to last a lifetime.
            </p>
            <div className="flex flex-wrap gap-4">
              <Link to="{primary_route}"
                className="inline-flex items-center gap-2 bg-white text-brand-800 font-bold px-8 py-4 rounded-xl hover:bg-brand-50 transition-all shadow-xl hover:shadow-2xl hover:-translate-y-0.5">
                Shop Now <ArrowRight size={{18}} />
              </Link>
              <a href="#featured"
                className="inline-flex items-center gap-2 border-2 border-white/30 text-white font-semibold px-8 py-4 rounded-xl hover:bg-white/10 transition-all">
                Explore Collection
              </a>
            </div>
          </div>
        </div>
        {{/* Wave divider */}}
        <div className="absolute bottom-0 left-0 right-0">
          <svg viewBox="0 0 1440 60" fill="white" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="none" className="w-full h-10 md:h-16">
            <path d="M0,60 C360,0 1080,60 1440,20 L1440,60 Z" />
          </svg>
        </div>
      </section>

      {{/* ── Featured Products ── */}}
      <section id="featured" className="py-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-end justify-between mb-10">
            <div>
              <p className="text-brand-600 text-xs font-bold uppercase tracking-widest mb-2">Our Collection</p>
              <h2 className="text-3xl md:text-4xl font-extrabold text-gray-900">Featured Products</h2>
            </div>
            <Link to="{primary_route}"
              className="hidden sm:flex items-center gap-2 text-sm font-semibold text-brand-600 hover:text-brand-700 transition-colors">
              View All <ArrowRight size={{16}} />
            </Link>
          </div>

          {{isLoading ? (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
              {{Array.from({{ length: 8 }}).map((_, i) => (
                <div key={{i}} className="rounded-2xl bg-gray-100 animate-pulse" style={{{{ aspectRatio: '3/4' }}}} />
              ))}}
            </div>
          ) : products.length === 0 ? (
            <div className="text-center py-20 text-gray-400">
              <ShoppingCart size={{48}} className="mx-auto mb-4 opacity-30" />
              <p className="text-lg font-medium">No products yet</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
              {{products.slice(0, 8).map((p, i) => (
                <ProductCard key={{p.id ?? i}} product={{p}} index={{i}} />
              ))}}
            </div>
          )}}

          {{products.length > 8 && (
            <div className="text-center mt-10">
              <Link to="{primary_route}"
                className="inline-flex items-center gap-2 border-2 border-brand-600 text-brand-600 font-bold px-8 py-3.5 rounded-xl hover:bg-brand-600 hover:text-white transition-all">
                View All {{products.length}} Products <ArrowRight size={{18}} />
              </Link>
            </div>
          )}}
        </div>
      </section>

      {{/* ── Why Choose Us ── */}}
      <section className="py-16 bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <p className="text-brand-600 text-xs font-bold uppercase tracking-widest mb-2">Why Us</p>
          <h2 className="text-3xl font-extrabold text-gray-900 mb-12">Made With Purpose</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {{[
              {{ emoji: '🎨', title: 'Artisan Quality', desc: 'Every item is crafted by skilled artisans using time-tested techniques and premium materials.' }},
              {{ emoji: '🌱', title: 'Sustainably Sourced', desc: 'We partner with ethical suppliers to ensure our products are good for you and the planet.' }},
              {{ emoji: '❤️', title: 'Made with Love', desc: 'Each product carries the dedication and passion of the maker—quality you can feel.' }},
            ].map(f => (
              <div key={{f.title}} className="bg-white rounded-2xl p-8 shadow-sm hover:shadow-md transition-shadow">
                <div className="text-4xl mb-4">{{f.emoji}}</div>
                <h3 className="text-lg font-bold text-gray-900 mb-2">{{f.title}}</h3>
                <p className="text-sm text-gray-600 leading-relaxed">{{f.desc}}</p>
              </div>
            ))}}
          </div>
        </div>
      </section>
    </div>
  )
}}
"""


def _generate_use_sse_hook() -> str:
    """Generate src/hooks/useSSE.ts — lightweight per-entity SSE subscription hook.

    Each entity list page imports this hook to subscribe to server-sent events
    for that entity type and automatically refetch when new data arrives.
    """
    return """\
// useSSE.ts — generated by AetherOS p05_frontend
// Lightweight SSE hook for per-entity real-time subscription.
// Usage: const { lastEvent } = useSSE('/api/sse/products')

import { useEffect, useState } from 'react'
import { getToken } from '../lib/auth'

interface SSEState {
  lastEvent: unknown | null
}

export function useSSE(endpoint: string): SSEState {
  const [lastEvent, setLastEvent] = useState<unknown | null>(null)

  useEffect(() => {
    if (!endpoint) return
    const token = getToken() ?? ''
    const url = endpoint + (token ? `?token=${encodeURIComponent(token)}` : '')
    const es = new EventSource(url)

    es.onmessage = (e: MessageEvent) => {
      try {
        setLastEvent(JSON.parse(e.data as string))
      } catch {
        // Non-JSON keepalive frames are intentionally ignored
        setLastEvent({ _ts: Date.now() })
      }
    }

    es.onerror = () => {
      // EventSource reconnects automatically; close to prevent runaway loops
      es.close()
    }

    return () => {
      es.close()
    }
  }, [endpoint])

  return { lastEvent }
}
"""


def _generate_use_websocket_hook() -> str:
    """Generate src/hooks/useWebSocket.ts — auto-reconnecting WebSocket hook."""
    return """\
// useWebSocket.ts — generated by AetherOS p05_frontend
// Auto-reconnecting WebSocket hook with typed message dispatch.
// Usage: const { send, lastMessage, status } = useWebSocket('/api/ws/chat')

import { useEffect, useRef, useState, useCallback } from 'react'
import { getToken } from '../lib/auth'

type WSStatus = 'connecting' | 'open' | 'closed' | 'error'

interface UseWebSocketResult {
  send: (data: unknown) => void
  lastMessage: unknown | null
  status: WSStatus
}

export function useWebSocket(path: string): UseWebSocketResult {
  const [lastMessage, setLastMessage] = useState<unknown | null>(null)
  const [status, setStatus] = useState<WSStatus>('connecting')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    const token = getToken() ?? ''
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const base = `${proto}//${window.location.host}`
    const url = `${base}${path}${token ? `?token=${encodeURIComponent(token)}` : ''}`
    const ws = new WebSocket(url)
    wsRef.current = ws
    setStatus('connecting')

    ws.onopen = () => { if (mountedRef.current) setStatus('open') }

    ws.onmessage = (e: MessageEvent) => {
      if (!mountedRef.current) return
      try {
        setLastMessage(JSON.parse(e.data as string))
      } catch {
        setLastMessage({ raw: e.data, _ts: Date.now() })
      }
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setStatus('closed')
      // Exponential back-off reconnect (max 10 s)
      reconnectTimer.current = setTimeout(connect, Math.min(1000 * 2 ** 3, 10000))
    }

    ws.onerror = () => { if (mountedRef.current) setStatus('error') }
  }, [path])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }, [])

  return { send, lastMessage, status }
}
"""


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
            f"      if (v === null || v === undefined) return <span className=\"text-gray-400\">—</span>\n"
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
import {{ {camel}Api }} from '../lib/api'
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
      const msg = (err as {{ response?: {{ data?: {{ detail?: string }} }} }})?.response?.data?.detail ?? 'Failed to create {singular}'
      toast(msg, 'error')
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
      const msg = (err as {{ response?: {{ data?: {{ detail?: string }} }} }})?.response?.data?.detail ?? 'Failed to update {singular}'
      toast(msg, 'error')
    }},
  }})

  const remove = useMutation({{
    mutationFn: {camel}Api.remove,
    onSuccess: () => {{
      qc.invalidateQueries({{ queryKey: ['{table}'] }})
      toast('{singular} deleted', 'success')
    }},
    onError: () => toast('Failed to delete {singular}', 'error'),
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
            className="p-1.5 text-gray-400 hover:text-brand-600 rounded"
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
              className="p-1.5 text-gray-400 hover:text-red-500 rounded"
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
    <div className="p-4 sm:p-8 bg-white dark:bg-gray-900 min-h-full">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-6 gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{label}</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Manage your {label.lower()} and track changes</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={{handleExport}}
            className="flex items-center gap-2 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 text-sm font-medium transition-all"
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
        <div className="text-center py-16 text-gray-400 dark:text-gray-500">
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
          className={{s <= Math.round(rating) ? 'fill-amber-400 text-amber-400' : 'text-gray-200'}} />
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
    <div className="group bg-white rounded-2xl overflow-hidden border border-gray-100 shadow-sm hover:shadow-xl transition-all duration-300 hover:-translate-y-0.5 flex flex-col">
      <div className="relative aspect-square bg-gray-50 overflow-hidden">
        {{imgSrc
          ? <img src={{imgSrc}} alt={{product.{name_field} ?? '{singular}'}}
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
              loading="lazy"
              onError={{e => {{ (e.target as HTMLImageElement).style.display = 'none' }}}} />
          : <div aria-hidden="true" className="w-full h-full flex items-center justify-center text-5xl font-bold text-gray-300">{{String(product.{name_field} ?? '{singular}').charAt(0).toUpperCase()}}</div>}}
      </div>
      <div className="p-4 flex flex-col flex-1">
        <p className="text-[11px] font-bold text-brand-600 uppercase tracking-wider mb-1">{{{cat_expr}}}</p>
        <h3 className="text-sm font-semibold text-gray-900 leading-snug mb-2 line-clamp-2 flex-1">
          {{product.{name_field} ?? '{singular}'}}
        </h3>
        {{rating !== null && <StarRating rating={{rating}} />}}
        <div className="flex items-center justify-between mt-3">
          <span className="text-lg font-bold text-gray-900">
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
    <div className="min-h-screen bg-white">
      {{/* Page header */}}
      <div className="bg-gray-50 border-b border-gray-100 py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h1 className="text-3xl font-extrabold text-gray-900">{label}</h1>
          <p className="text-gray-500 mt-1 text-sm">{{all.length}} items available</p>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {{/* Toolbar */}}
        <div className="flex flex-col sm:flex-row gap-4 mb-8">
          <div className="relative flex-1 max-w-sm">
            <Search size={{16}} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="search"
              placeholder="Search {label.lower()}..."
              value={{search}}
              onChange={{e => setSearch(e.target.value)}}
              className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-gray-200 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-300 focus:border-brand-400 transition-all"
            />
          </div>
          <div className="flex items-center gap-3 ml-auto">
            <button onClick={{() => setShowFilters(v => !v)}}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-gray-200 text-sm font-medium text-gray-600 hover:border-brand-400 hover:text-brand-600 transition-all">
              <SlidersHorizontal size={{15}} /> Filters
            </button>
            <select value={{sort}} onChange={{e => setSort(e.target.value)}}
              className="px-4 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-brand-300 bg-white cursor-pointer">
              {{SORT_OPTIONS.map(o => <option key={{o.value}} value={{o.value}}>{{o.label}}</option>)}}
            </select>
          </div>
        </div>

        {{/* Results count */}}
        {{search && (
          <p className="text-sm text-gray-500 mb-4">
            {{filtered.length}} result{{filtered.length !== 1 ? 's' : ''}} for "<span className="font-semibold">{{search}}</span>"
          </p>
        )}}

        {{/* Grid */}}
        {{isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
            {{Array.from({{ length: 12 }}).map((_, i) => (
              <div key={{i}} className="rounded-2xl bg-gray-100 animate-pulse" style={{{{ aspectRatio: '3/4' }}}} />
            ))}}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-24">
            <ShoppingCart size={{48}} className="mx-auto mb-4 text-gray-200" />
            <h3 className="text-lg font-semibold text-gray-700">No {label.lower()} found</h3>
            {{search && <p className="text-sm text-gray-400 mt-1">Try a different search term</p>}}
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


def _generate_docker_compose(project_dir: Path) -> str:
    """Generate a docker-compose.yml that wires app + frontend services."""
    return """\
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "${API_PORT:-8000}:8000"
    environment:
      DATABASE_URL: ${DATABASE_URL:-sqlite:///./data/app.db}
      # no default: a placeholder secret in the file is a secret everyone knows. Set it in .env (openssl rand -hex 32)
      SECRET_KEY: ${SECRET_KEY:?set SECRET_KEY in .env (openssl rand -hex 32)}
      RSA_PRIVATE_KEY_PATH: /keys/private_key.pem
    volumes:
      - db_data:/app/data
      - keys:/keys       # the JWT signing key, shared by every replica
    healthcheck:
      test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 20s

  frontend:
    build:
      context: ./frontend
      args:
        # VITE_ vars baked at build time — pass as args, not runtime env
        # Default is empty so nginx /api/ proxy is used (works on any server)
        # Override: VITE_API_URL=http://your-server:8000 docker-compose up
        VITE_API_URL: ${VITE_API_URL:-}
    ports:
      - "${PORT:-80}:80"
    depends_on:
      app:
        condition: service_healthy

volumes:
  db_data:
  keys:
"""


# ── New premium UI component generators ───────────────────────────────────────

def _generate_lib_utils() -> str:
    """Generate src/lib/utils.ts — cn() utility combining clsx + tailwind-merge."""
    return """\
// Auto-generated by AetherOS p05_frontend
// cn() utility: combines clsx conditional class logic with tailwind-merge deduplication.
// This is the standard shadcn/ui pattern — import cn() anywhere Tailwind classes need merging.
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
"""


def _generate_ui_button() -> str:
    """Generate src/components/ui/Button.tsx — shadcn/ui-compatible Button with variants."""
    return """\
// Auto-generated by AetherOS p05_frontend — shadcn/ui-compatible Button
import { ButtonHTMLAttributes, forwardRef } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'
import { Loader2 } from 'lucide-react'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-lg text-sm font-semibold tracking-tight transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default:     'bg-brand-600 text-white shadow-sm hover:bg-brand-700 active:scale-[0.98]',
        outline:     'border border-gray-300 bg-white text-gray-700 shadow-sm hover:bg-gray-50 hover:border-gray-400 active:scale-[0.98]',
        ghost:       'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
        destructive: 'bg-red-600 text-white shadow-sm hover:bg-red-700 active:scale-[0.98]',
        secondary:   'bg-gray-100 text-gray-900 hover:bg-gray-200 active:scale-[0.98]',
        link:        'text-brand-600 underline-offset-4 hover:underline p-0 h-auto',
      },
      size: {
        sm: 'h-8 px-3 text-xs',
        md: 'h-10 px-4',
        lg: 'h-11 px-6 text-base',
        icon: 'h-9 w-9 p-0',
      },
    },
    defaultVariants: { variant: 'default', size: 'md' },
  }
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
)
Button.displayName = 'Button'
"""


def _generate_ui_input() -> str:
    """Generate src/components/ui/Input.tsx — labeled input with error/helper text."""
    return """\
// Auto-generated by AetherOS p05_frontend — shadcn/ui-compatible Input
import { InputHTMLAttributes, forwardRef } from 'react'
import { cn } from '../../lib/utils'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, helperText, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\\s+/g, '-')
    return (
      <div className="space-y-1.5">
        {label && (
          <label
            htmlFor={inputId}
            className="block text-sm font-medium text-gray-700"
          >
            {label}
            {props.required && <span className="text-red-500 ml-1" aria-hidden>*</span>}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            'flex h-10 w-full rounded-lg border px-3 py-2 text-sm ring-offset-white transition-colors',
            'placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2',
            'disabled:cursor-not-allowed disabled:opacity-50',
            error
              ? 'border-red-400 bg-red-50 focus-visible:ring-red-400'
              : 'border-gray-300 bg-white hover:border-gray-400',
            className
          )}
          aria-invalid={!!error}
          aria-describedby={error ? `${inputId}-error` : helperText ? `${inputId}-helper` : undefined}
          {...props}
        />
        {error && (
          <p id={`${inputId}-error`} className="text-xs text-red-600 flex items-center gap-1">
            {error}
          </p>
        )}
        {helperText && !error && (
          <p id={`${inputId}-helper`} className="text-xs text-gray-500">
            {helperText}
          </p>
        )}
      </div>
    )
  }
)
Input.displayName = 'Input'
"""


def _generate_ui_card() -> str:
    """Generate src/components/ui/Card.tsx — Card with Header/Content/Footer sub-components."""
    return """\
// Auto-generated by AetherOS p05_frontend — shadcn/ui-compatible Card
import { HTMLAttributes, forwardRef } from 'react'
import { cn } from '../../lib/utils'

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('rounded-2xl border border-gray-100 bg-white shadow-sm', className)}
      {...props}
    />
  )
)
Card.displayName = 'Card'

export const CardHeader = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex flex-col space-y-1.5 p-6', className)} {...props} />
  )
)
CardHeader.displayName = 'CardHeader'

export const CardTitle = forwardRef<HTMLHeadingElement, HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3
      ref={ref}
      className={cn('text-xl font-semibold tracking-tight text-gray-900', className)}
      {...props}
    />
  )
)
CardTitle.displayName = 'CardTitle'

export const CardDescription = forwardRef<HTMLParagraphElement, HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p ref={ref} className={cn('text-sm text-gray-500', className)} {...props} />
  )
)
CardDescription.displayName = 'CardDescription'

export const CardContent = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('p-6 pt-0', className)} {...props} />
  )
)
CardContent.displayName = 'CardContent'

export const CardFooter = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex items-center p-6 pt-0', className)} {...props} />
  )
)
CardFooter.displayName = 'CardFooter'
"""


def _generate_ui_badge() -> str:
    """Generate src/components/ui/Badge.tsx — status badge with semantic variants."""
    return """\
// Auto-generated by AetherOS p05_frontend — shadcn/ui-compatible Badge
import { HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold tracking-tight transition-colors',
  {
    variants: {
      variant: {
        default:  'bg-brand-100 text-brand-800 border border-brand-200',
        success:  'bg-green-100  text-green-800  border border-green-200',
        warning:  'bg-amber-100  text-amber-800  border border-amber-200',
        error:    'bg-red-100    text-red-800    border border-red-200',
        outline:  'border border-gray-300 text-gray-700 bg-white',
        secondary:'bg-gray-100   text-gray-700   border border-gray-200',
      },
    },
    defaultVariants: { variant: 'default' },
  }
)

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

/** Derive badge variant from common status strings. */
export function statusVariant(status: string): BadgeProps['variant'] {
  const s = status?.toLowerCase() ?? ''
  if (['active', 'completed', 'paid', 'success', 'approved', 'published'].includes(s)) return 'success'
  if (['pending', 'processing', 'draft', 'review'].includes(s)) return 'warning'
  if (['inactive', 'cancelled', 'failed', 'rejected', 'error', 'overdue'].includes(s)) return 'error'
  return 'default'
}
"""


def _generate_ui_skeleton() -> str:
    """Generate src/components/ui/Skeleton.tsx — loading placeholder adapting to parent."""
    return """\
// Auto-generated by AetherOS p05_frontend — Skeleton loader
import { HTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

/** Generic skeleton — adapts to parent width/height via className. */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('animate-pulse rounded-md bg-gray-200', className)}
      aria-hidden="true"
      {...props}
    />
  )
}

/** Skeleton rows for a data table. */
export function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="animate-pulse space-y-0" role="status" aria-label="Loading">
      <div className="flex gap-4 px-4 py-3 border-b border-gray-100">
        {Array.from({ length: cols }).map((_, j) => (
          <Skeleton key={j} className="h-3 w-20 rounded" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 px-4 py-3 border-b border-gray-50">
          {Array.from({ length: cols }).map((_, j) => (
            <Skeleton
              key={j}
              className="h-4 flex-1 rounded"
              style={{ animationDelay: `${i * 60 + j * 20}ms` }}
            />
          ))}
        </div>
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  )
}

/** Card-shaped skeleton for detail panels. */
export function CardSkeleton() {
  return (
    <div className="space-y-4 p-6 bg-white rounded-2xl border border-gray-100">
      <Skeleton className="h-6 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/3" />
    </div>
  )
}
"""


def _generate_ui_modal() -> str:
    """Generate src/components/ui/Modal.tsx — Radix Dialog with backdrop, close, focus trap."""
    return """\
// Auto-generated by AetherOS p05_frontend — Radix-based Modal
import { ReactNode } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from '../../lib/utils'

interface ModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: ReactNode
  className?: string
  /** Width class for the dialog panel (default: max-w-lg) */
  size?: 'sm' | 'md' | 'lg' | 'xl'
}

const sizeMap = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
}

export function Modal({ open, onOpenChange, title, description, children, className, size = 'md' }: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        {/* Backdrop */}
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        {/* Panel */}
        <Dialog.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2',
            'w-full rounded-2xl bg-white dark:bg-gray-900 shadow-2xl',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
            'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            'max-h-[90vh] flex flex-col',
            sizeMap[size],
            className
          )}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-gray-100 dark:border-gray-700 shrink-0">
            <div>
              <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-gray-100 tracking-tight">
                {title}
              </Dialog.Title>
              {description && (
                <Dialog.Description className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  {description}
                </Dialog.Description>
              )}
            </div>
            <Dialog.Close asChild>
              <button
                className="rounded-lg p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                aria-label="Close dialog"
              >
                <X size={18} />
              </button>
            </Dialog.Close>
          </div>
          {/* Scrollable content */}
          <div className="flex-1 overflow-y-auto px-6 py-4 text-gray-900 dark:text-gray-100">
            {children}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
"""


def _generate_ui_select() -> str:
    """Generate src/components/ui/Select.tsx — Radix Select with search support."""
    return """\
// Auto-generated by AetherOS p05_frontend — Radix-based Select
import { useState } from 'react'
import * as RadixSelect from '@radix-ui/react-select'
import { ChevronDown, ChevronUp, Check, Search } from 'lucide-react'
import { cn } from '../../lib/utils'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

interface SelectProps {
  value?: string
  onValueChange?: (value: string) => void
  options: SelectOption[]
  placeholder?: string
  label?: string
  error?: string
  disabled?: boolean
  className?: string
  /** Show search input when option count exceeds this threshold (default 10) */
  searchThreshold?: number
}

export function Select({
  value,
  onValueChange,
  options,
  placeholder = 'Select…',
  label,
  error,
  disabled,
  className,
  searchThreshold = 10,
}: SelectProps) {
  const [search, setSearch] = useState('')
  const showSearch = options.length > searchThreshold
  const filtered = showSearch
    ? options.filter(o => o.label.toLowerCase().includes(search.toLowerCase()))
    : options

  return (
    <div className={cn('space-y-1.5', className)}>
      {label && (
        <label className="block text-sm font-medium text-gray-700">{label}</label>
      )}
      <RadixSelect.Root value={value} onValueChange={onValueChange} disabled={disabled}>
        <RadixSelect.Trigger
          className={cn(
            'flex h-10 w-full items-center justify-between rounded-lg border px-3 py-2 text-sm',
            'bg-white ring-offset-white transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2',
            'disabled:cursor-not-allowed disabled:opacity-50',
            error ? 'border-red-400' : 'border-gray-300 hover:border-gray-400'
          )}
          aria-label={label}
        >
          <RadixSelect.Value placeholder={placeholder} />
          <RadixSelect.Icon>
            <ChevronDown className="h-4 w-4 text-gray-400" />
          </RadixSelect.Icon>
        </RadixSelect.Trigger>

        <RadixSelect.Portal>
          <RadixSelect.Content
            className="relative z-50 min-w-[8rem] overflow-hidden rounded-xl border border-gray-200 bg-white shadow-xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
            position="popper"
            sideOffset={4}
          >
            <RadixSelect.ScrollUpButton className="flex items-center justify-center py-1 text-gray-400">
              <ChevronUp className="h-4 w-4" />
            </RadixSelect.ScrollUpButton>

            {showSearch && (
              <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100">
                <Search className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                <input
                  className="flex-1 text-sm outline-none placeholder:text-gray-400 bg-transparent"
                  placeholder="Search…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  onKeyDown={e => e.stopPropagation()}
                />
              </div>
            )}

            <RadixSelect.Viewport className="p-1 max-h-60">
              {filtered.map(opt => (
                <RadixSelect.Item
                  key={opt.value}
                  value={opt.value}
                  disabled={opt.disabled}
                  className="relative flex cursor-pointer select-none items-center rounded-lg py-2 pl-8 pr-4 text-sm text-gray-700 outline-none focus:bg-brand-50 focus:text-brand-900 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                >
                  <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
                    <RadixSelect.ItemIndicator>
                      <Check className="h-4 w-4 text-brand-600" />
                    </RadixSelect.ItemIndicator>
                  </span>
                  <RadixSelect.ItemText>{opt.label}</RadixSelect.ItemText>
                </RadixSelect.Item>
              ))}
              {filtered.length === 0 && (
                <p className="px-4 py-6 text-center text-sm text-gray-400">No options found</p>
              )}
            </RadixSelect.Viewport>

            <RadixSelect.ScrollDownButton className="flex items-center justify-center py-1 text-gray-400">
              <ChevronDown className="h-4 w-4" />
            </RadixSelect.ScrollDownButton>
          </RadixSelect.Content>
        </RadixSelect.Portal>
      </RadixSelect.Root>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
"""


def _generate_ui_toast() -> str:
    """Generate src/components/ui/Toast.tsx — Radix Toast with success/error/warning/info."""
    return """\
// Auto-generated by AetherOS p05_frontend — Radix Toast
import { createContext, useContext, useState, useCallback, ReactNode } from 'react'
import * as RadixToast from '@radix-ui/react-toast'
import { X, CheckCircle2, AlertCircle, AlertTriangle, Info } from 'lucide-react'
import { cn } from '../../lib/utils'

type ToastVariant = 'success' | 'error' | 'warning' | 'info'

interface ToastItem {
  id: string
  title: string
  description?: string
  variant: ToastVariant
}

interface ToastContextValue {
  toast: (title: string, variant?: ToastVariant, description?: string) => void
}

const ToastContext = createContext<ToastContextValue>({ toast: () => undefined })

export function useToast() {
  return useContext(ToastContext)
}

const variantConfig: Record<ToastVariant, { icon: typeof CheckCircle2; classes: string }> = {
  success: { icon: CheckCircle2, classes: 'border-green-200  bg-green-50  text-green-900' },
  error:   { icon: AlertCircle,  classes: 'border-red-200    bg-red-50    text-red-900' },
  warning: { icon: AlertTriangle,classes: 'border-amber-200  bg-amber-50  text-amber-900' },
  info:    { icon: Info,         classes: 'border-blue-200   bg-blue-50   text-blue-900' },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const toast = useCallback((title: string, variant: ToastVariant = 'info', description?: string) => {
    const id = Math.random().toString(36).slice(2)
    setToasts(prev => [...prev, { id, title, description, variant }])
  }, [])

  const dismiss = (id: string) => setToasts(prev => prev.filter(t => t.id !== id))

  return (
    <ToastContext.Provider value={{ toast }}>
      <RadixToast.Provider swipeDirection="right">
        {children}
        {toasts.map(t => {
          const { icon: Icon, classes } = variantConfig[t.variant]
          return (
            <RadixToast.Root
              key={t.id}
              open
              onOpenChange={open => { if (!open) dismiss(t.id) }}
              duration={4000}
              className={cn(
                'group pointer-events-auto relative flex w-full max-w-sm items-start gap-3 overflow-hidden rounded-xl border p-4 shadow-lg',
                'data-[state=open]:animate-in data-[state=closed]:animate-out',
                'data-[state=closed]:fade-out-80 data-[state=open]:fade-in-0',
                'data-[state=closed]:slide-out-to-right-full data-[state=open]:slide-in-from-right-full',
                classes
              )}
            >
              <Icon className="h-5 w-5 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <RadixToast.Title className="text-sm font-semibold">{t.title}</RadixToast.Title>
                {t.description && (
                  <RadixToast.Description className="text-xs mt-0.5 opacity-80">
                    {t.description}
                  </RadixToast.Description>
                )}
              </div>
              <RadixToast.Close asChild>
                <button
                  className="shrink-0 rounded p-1 opacity-60 hover:opacity-100 transition-opacity"
                  aria-label="Dismiss"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </RadixToast.Close>
            </RadixToast.Root>
          )
        })}
        <RadixToast.Viewport className="fixed bottom-4 right-4 z-[100] flex max-h-screen w-full max-w-sm flex-col gap-2 p-2" />
      </RadixToast.Provider>
    </ToastContext.Provider>
  )
}
"""


def _generate_ui_tooltip() -> str:
    """Generate src/components/ui/Tooltip.tsx — Radix Tooltip wrapping any child."""
    return """\
// Auto-generated by AetherOS p05_frontend — Radix Tooltip
import { ReactNode } from 'react'
import * as RadixTooltip from '@radix-ui/react-tooltip'
import { cn } from '../../lib/utils'

interface TooltipProps {
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
  className?: string
  delayDuration?: number
}

export function Tooltip({ content, children, side = 'top', className, delayDuration = 300 }: TooltipProps) {
  return (
    <RadixTooltip.Provider delayDuration={delayDuration}>
      <RadixTooltip.Root>
        <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content
            side={side}
            sideOffset={6}
            className={cn(
              'z-50 rounded-lg border border-gray-200 bg-gray-900 px-3 py-1.5 text-xs font-medium text-white shadow-md',
              'animate-in fade-in-0 zoom-in-95',
              'data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95',
              `data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2
               data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2`,
              className
            )}
          >
            {content}
            <RadixTooltip.Arrow className="fill-gray-900" />
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  )
}
"""


def _generate_ui_table() -> str:
    """Generate src/components/ui/Table.tsx — sortable table with hover, empty state, mobile card stack."""
    return """\
// Auto-generated by AetherOS p05_frontend — premium Table component
// On mobile (<768px) each row renders as a card instead of a table row.
import { useState, ReactNode } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'
import { cn } from '../../lib/utils'

export interface TableColumn<T> {
  key: keyof T | string
  header: string
  cell?: (row: T, index: number) => ReactNode
  /** Whether this column is hidden on mobile */
  mobileHidden?: boolean
  sortable?: boolean
  className?: string
}

interface TableProps<T> {
  data: T[]
  columns: TableColumn<T>[]
  isLoading?: boolean
  emptyState?: ReactNode
  keyExtractor?: (row: T, index: number) => string | number
  className?: string
}

type SortDir = 'asc' | 'desc' | null

export function Table<T>({ data, columns, isLoading, emptyState, keyExtractor, className }: TableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)

  const handleSort = (key: string) => {
    if (sortKey !== key) { setSortKey(key); setSortDir('asc'); return }
    if (sortDir === 'asc') { setSortDir('desc'); return }
    setSortKey(null); setSortDir(null)
  }

  const sorted = [...data].sort((a, b) => {
    if (!sortKey || !sortDir) return 0
    const av = (a as Record<string, unknown>)[sortKey]
    const bv = (b as Record<string, unknown>)[sortKey]
    const cmp = String(av ?? '').localeCompare(String(bv ?? ''), undefined, { numeric: true })
    return sortDir === 'asc' ? cmp : -cmp
  })

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-0 rounded-xl border border-gray-100 overflow-hidden" role="status">
        <div className="flex gap-4 bg-gray-50 px-4 py-3 border-b border-gray-100">
          {columns.map((_, j) => (
            <div key={j} className="h-3 bg-gray-300 rounded w-20" />
          ))}
        </div>
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} className="flex gap-4 px-4 py-3.5 border-b border-gray-50">
            {columns.map((_, j) => (
              <div key={j} className="h-4 bg-gray-100 rounded flex-1" style={{ animationDelay: `${i * 50 + j * 15}ms` }} />
            ))}
          </div>
        ))}
        <span className="sr-only">Loading…</span>
      </div>
    )
  }

  if (!data.length) {
    return (
      <div className="flex flex-col items-center justify-center py-16 rounded-xl border-2 border-dashed border-gray-200 text-center" role="status">
        {emptyState ?? (
          <>
            <div className="text-4xl mb-3">📋</div>
            <p className="text-sm font-medium text-gray-500">No records found</p>
          </>
        )}
      </div>
    )
  }

  const SortIcon = ({ col }: { col: TableColumn<T> }) => {
    if (!col.sortable) return null
    const key = String(col.key)
    if (sortKey !== key) return <ChevronsUpDown className="h-3.5 w-3.5 text-gray-300" />
    if (sortDir === 'asc') return <ChevronUp className="h-3.5 w-3.5 text-brand-500" />
    return <ChevronDown className="h-3.5 w-3.5 text-brand-500" />
  }

  return (
    <div className={cn('w-full', className)}>
      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto rounded-xl border border-gray-100 shadow-sm">
        <table className="w-full text-sm" aria-label="Data table">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {columns.map(col => (
                <th
                  key={String(col.key)}
                  onClick={() => col.sortable && handleSort(String(col.key))}
                  className={cn(
                    'px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap',
                    col.sortable && 'cursor-pointer select-none hover:text-gray-900',
                    col.className
                  )}
                  aria-sort={sortKey === String(col.key) ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                >
                  <span className="flex items-center gap-1">
                    {col.header}
                    <SortIcon col={col} />
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {sorted.map((row, i) => (
              <tr
                key={keyExtractor ? keyExtractor(row, i) : i}
                className="hover:bg-gray-50 transition-colors group"
              >
                {columns.map(col => (
                  <td key={String(col.key)} className={cn('px-4 py-3 text-gray-700', col.className)}>
                    {col.cell
                      ? col.cell(row, i)
                      : String((row as Record<string, unknown>)[String(col.key)] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile card stack */}
      <div className="md:hidden space-y-3">
        {sorted.map((row, i) => {
          const visibleCols = columns.filter(c => !c.mobileHidden)
          const [first, ...rest] = visibleCols
          return (
            <div key={keyExtractor ? keyExtractor(row, i) : i}
              className="rounded-xl border border-gray-100 bg-white shadow-sm p-4 space-y-2">
              {first && (
                <div className="font-semibold text-gray-900 text-sm">
                  {first.cell ? first.cell(row, i) : String((row as Record<string, unknown>)[String(first.key)] ?? '—')}
                </div>
              )}
              {rest.map(col => (
                <div key={String(col.key)} className="flex items-center justify-between text-xs">
                  <span className="text-gray-400 uppercase tracking-wide font-medium">{col.header}</span>
                  <span className="text-gray-700">
                    {col.cell ? col.cell(row, i) : String((row as Record<string, unknown>)[String(col.key)] ?? '—')}
                  </span>
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
"""


def _generate_domain_dashboard(domain: str, entities: List[dict]) -> str:
    """Generate a premium domain-specific Dashboard with Recharts charts and Framer Motion."""
    _label = lambda t: " ".join(p.capitalize() for p in t.replace("_", " ").split())

    # Domain-specific KPI configurations
    _domain_kpis = {
        "healthcare": [
            ("Total Patients", "patients", "Users", "teal"),
            ("Appointments Today", "appointments", "Calendar", "blue"),
            ("Critical Alerts", "records", "AlertCircle", "red"),
        ],
        "ecommerce": [
            ("Total Revenue", "orders", "DollarSign", "green"),
            ("Products", "products", "Package", "blue"),
            ("Orders Today", "orders", "ShoppingCart", "purple"),
        ],
        "fintech": [
            ("Account Balance", "accounts", "DollarSign", "yellow"),
            ("Transactions", "transactions", "ArrowRightLeft", "blue"),
            ("Pending", "transactions", "Clock", "orange"),
        ],
        "saas": [
            ("Active Users", "users", "Users", "blue"),
            ("MRR", "subscriptions", "TrendingUp", "green"),
            ("Open Tickets", "tickets", "MessageSquare", "orange"),
        ],
    }
    kpis = _domain_kpis.get(domain, _domain_kpis["saas"])

    # Use the first 3 entities for KPIs if domain not in map
    if domain not in _domain_kpis:
        kpis = [
            (_label(entities[i]["table"]) if i < len(entities) else f"Metric {i+1}",
             entities[i]["table"] if i < len(entities) else "items",
             ["Users", "TrendingUp", "Activity", "Package"][i % 4],
             ["blue", "green", "purple", "orange"][i % 4])
            for i in range(3)
        ]

    kpi_queries = "\n".join(
        f"  const {{ data: {e}Data }} = useQuery({{\n"
        f"    queryKey: ['{e}'],\n"
        f"    queryFn: () => apiClient.get('/{e}').then(r => r.data).catch(() => ({{}})),\n"
        f"    staleTime: 60_000,\n"
        f"  }})"
        for (_, e, __, ___) in kpis
    )

    kpi_cards = "\n".join(
        f"""      <motion.div
        initial={{{{ opacity: 0, y: 8 }}}}
        animate={{{{ opacity: 1, y: 0 }}}}
        transition={{{{ duration: 0.18, ease: 'easeOut', delay: {i} * 0.06 }}}}
        className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 hover:shadow-md transition-shadow"
      >
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold text-gray-500 uppercase tracking-wide">{label}</p>
          <div className="p-2 bg-{color}-50 rounded-lg">
            <{icon} size={{18}} className="text-{color}-600" />
          </div>
        </div>
        <p className="text-4xl font-bold text-gray-900">
          {{{e}Data ? (Array.isArray({e}Data) ? {e}Data.length : ({e}Data?.total ?? {e}Data?.count ?? '—')) : '—'}}
        </p>
        <p className="text-xs text-gray-400 mt-1">Updated just now</p>
      </motion.div>"""
        for i, (label, e, icon, color) in enumerate(kpis)
    )

    # Icon imports
    icon_names = sorted(set([icon for (_, _, icon, __) in kpis] + ["TrendingUp", "Activity"]))
    icons_import = ", ".join(icon_names)

    entity_links = "\n".join(
        f"""        <a href="/{e['table'].replace('_', '-')}" className="flex items-center justify-between p-4 rounded-xl border border-gray-100 hover:border-brand-200 hover:bg-brand-50 transition-all group">
          <div>
            <p className="text-sm font-semibold text-gray-900 group-hover:text-brand-700">{_label(e['table'])}</p>
            <p className="text-xs text-gray-400 mt-0.5">Manage {_label(e['table']).lower()}</p>
          </div>
          <span className="text-gray-300 group-hover:text-brand-400 text-lg transition-colors">→</span>
        </a>"""
        for e in entities[:6]
    )

    return f"""\
// Auto-generated by AetherOS p05_frontend — premium domain dashboard (domain: {domain})
import {{ useQuery }} from '@tanstack/react-query'
import {{ motion }} from 'framer-motion'
import {{ {icons_import} }} from 'lucide-react'
import {{ apiClient }} from '../lib/api'
import {{
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip,
  ResponsiveContainer, Legend
}} from 'recharts'

// SAMPLE data for the charts (labelled as such on screen): replace with a real analytics endpoint
const TREND_DATA = [
  {{ day: 'Mon', value: 42, prev: 38 }},
  {{ day: 'Tue', value: 58, prev: 45 }},
  {{ day: 'Wed', value: 51, prev: 52 }},
  {{ day: 'Thu', value: 74, prev: 61 }},
  {{ day: 'Fri', value: 63, prev: 58 }},
  {{ day: 'Sat', value: 89, prev: 71 }},
  {{ day: 'Sun', value: 95, prev: 82 }},
]

export default function Dashboard() {{
{kpi_queries}

  return (
    <motion.div
      initial={{{{ opacity: 0, y: 8 }}}}
      animate={{{{ opacity: 1, y: 0 }}}}
      transition={{{{ duration: 0.18, ease: 'easeOut' }}}}
      className="p-4 sm:p-6 md:p-8 max-w-7xl mx-auto space-y-8"
    >
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 tracking-tight">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1 font-medium">Welcome back. Here's what's happening.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-50 border border-green-200 text-green-700 text-xs font-semibold">
            <Activity size={{12}} /> Sample chart data
          </span>
        </div>
      </div>

      {{/* KPI Cards */}}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
{kpi_cards}
      </div>

      {{/* Charts row */}}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {{/* Area chart — 7-day trend */}}
        <motion.div
          initial={{{{ opacity: 0, y: 8 }}}}
          animate={{{{ opacity: 1, y: 0 }}}}
          transition={{{{ duration: 0.18, ease: 'easeOut', delay: 0.2 }}}}
          className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6"
        >
          <div className="mb-4">
            <h2 className="text-base font-semibold text-gray-900 tracking-tight">7-Day Activity (sample data)</h2>
            <p className="text-xs text-gray-400 mt-0.5">Illustrative values, not your data: connect an analytics endpoint</p>
          </div>
          <ResponsiveContainer width="100%" height={{220}}>
            <AreaChart data={{TREND_DATA}} margin={{{{ top: 4, right: 4, left: -20, bottom: 0 }}}}>
              <defs>
                <linearGradient id="gradCurrent" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#6366f1" stopOpacity={{0.15}} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={{0}} />
                </linearGradient>
                <linearGradient id="gradPrev" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#94a3b8" stopOpacity={{0.1}} />
                  <stop offset="95%" stopColor="#94a3b8" stopOpacity={{0}} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={{false}} />
              <XAxis dataKey="day" tick={{{{ fontSize: 11, fill: '#94a3b8' }}}} axisLine={{false}} tickLine={{false}} />
              <YAxis tick={{{{ fontSize: 11, fill: '#94a3b8' }}}} axisLine={{false}} tickLine={{false}} />
              <RechartsTooltip
                contentStyle={{{{ borderRadius: '12px', border: '1px solid #e2e8f0', fontSize: 12 }}}}
              />
              <Legend wrapperStyle={{{{ fontSize: 12, paddingTop: 8 }}}} />
              <Area type="monotone" dataKey="value" name="This week" stroke="#6366f1" strokeWidth={{2}} fill="url(#gradCurrent)" dot={{false}} />
              <Area type="monotone" dataKey="prev"  name="Last week" stroke="#94a3b8" strokeWidth={{1.5}} fill="url(#gradPrev)" dot={{false}} strokeDasharray="4 4" />
            </AreaChart>
          </ResponsiveContainer>
        </motion.div>

        {{/* Bar chart — 30-day summary */}}
        <motion.div
          initial={{{{ opacity: 0, y: 8 }}}}
          animate={{{{ opacity: 1, y: 0 }}}}
          transition={{{{ duration: 0.18, ease: 'easeOut', delay: 0.25 }}}}
          className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6"
        >
          <div className="mb-4">
            <h2 className="text-base font-semibold text-gray-900 tracking-tight">Weekly Breakdown (sample data)</h2>
            <p className="text-xs text-gray-400 mt-0.5">Illustrative values, not your data</p>
          </div>
          <ResponsiveContainer width="100%" height={{220}}>
            <BarChart data={{TREND_DATA}} margin={{{{ top: 4, right: 4, left: -20, bottom: 0 }}}}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={{false}} />
              <XAxis dataKey="day" tick={{{{ fontSize: 11, fill: '#94a3b8' }}}} axisLine={{false}} tickLine={{false}} />
              <YAxis tick={{{{ fontSize: 11, fill: '#94a3b8' }}}} axisLine={{false}} tickLine={{false}} />
              <RechartsTooltip
                contentStyle={{{{ borderRadius: '12px', border: '1px solid #e2e8f0', fontSize: 12 }}}}
                cursor={{{{ fill: 'rgba(99,102,241,0.05)' }}}}
              />
              <Bar dataKey="value" name="Volume" fill="#6366f1" radius={{[6, 6, 0, 0]}} maxBarSize={{40}} />
            </BarChart>
          </ResponsiveContainer>
        </motion.div>
      </div>

      {{/* Quick access */}}
      <motion.div
        initial={{{{ opacity: 0, y: 8 }}}}
        animate={{{{ opacity: 1, y: 0 }}}}
        transition={{{{ duration: 0.18, ease: 'easeOut', delay: 0.3 }}}}
        className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6"
      >
        <h2 className="text-base font-semibold text-gray-900 tracking-tight mb-4">Quick Access</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
{entity_links}
        </div>
      </motion.div>
    </motion.div>
  )
}}
"""


def _generate_mobile_first_layout(entities: List[dict], project_name: str) -> str:
    """Generate Layout.tsx with mobile-first sidebar that collapses to bottom tab bar on <768px."""
    icons_needed = {"LayoutDashboard", "LogOut"}
    for ent in entities:
        icons_needed.add(entity_icon(ent["table"]))

    nav_items: List[str] = [
        "  { to: '/' as const, label: 'Dashboard', icon: 'LayoutDashboard' },",
    ]
    for ent in entities[:4]:  # Bottom nav shows max 4 items + more
        table = ent["table"]
        label = to_label(table)
        icon = entity_icon(table)
        route_path = f"/{table.replace('_', '-')}"
        nav_items.append(f"  {{ to: '{route_path}' as const, label: '{label}', icon: '{icon}' }},")

    all_nav_items: List[str] = [
        "  { to: '/' as const, label: 'Dashboard', icon: 'LayoutDashboard' },",
    ]
    for ent in entities:
        table = ent["table"]
        label = to_label(table)
        icon = entity_icon(table)
        route_path = f"/{table.replace('_', '-')}"
        all_nav_items.append(f"  {{ to: '{route_path}' as const, label: '{label}', icon: '{icon}' }},")

    icons_str = ", ".join(sorted(icons_needed | {"Menu", "Moon", "Sun", "X"}))
    nav_str = "\n".join(nav_items)
    all_nav_str = "\n".join(all_nav_items)

    return f"""\
// Auto-generated by AetherOS p05_frontend — mobile-first layout
// Desktop: persistent sidebar. Mobile (<768px): collapsible bottom tab bar.
import {{ useState, useEffect }} from 'react'
import {{ Link, useRouter, Outlet }} from '@tanstack/react-router'
import {{ clearToken }} from '../lib/auth'
import {{ motion, AnimatePresence }} from 'framer-motion'
import {{ {icons_str} }} from 'lucide-react'

const _ICON_MAP: Record<string, React.FC<{{size?: number; className?: string}}>> = {{
  {", ".join(f"'{i}': {i}" for i in sorted(icons_needed))}
}}

// Bottom tab bar: dashboard + first 3 entities
const BOTTOM_NAV = [
{nav_str}
]

// Sidebar: all entities
const SIDEBAR_NAV = [
{all_nav_str}
]

export function Layout() {{
  const router = useRouter()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [darkMode, setDarkMode] = useState<boolean>(() => {{
    if (typeof window === 'undefined') return false
    const stored = localStorage.getItem('theme')
    if (stored) return stored === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  }})

  useEffect(() => {{
    if (darkMode) {{
      document.documentElement.classList.add('dark')
      localStorage.setItem('theme', 'dark')
    }} else {{
      document.documentElement.classList.remove('dark')
      localStorage.setItem('theme', 'light')
    }}
  }}, [darkMode])

  const handleLogout = () => {{
    clearToken()
    router.navigate({{ to: '/login' }})
  }}

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900 overflow-hidden">
      {{/* ── Desktop sidebar ── */}}
      <aside className="hidden md:flex w-64 bg-gray-900 dark:bg-gray-950 text-white flex-col border-r border-gray-800 shrink-0">
        <div className="p-6 border-b border-gray-800 flex items-center justify-between">
          <h1 className="text-lg font-bold text-white tracking-tight">{project_name}</h1>
          <button
            onClick={{() => setDarkMode(d => !d)}}
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
            aria-label="Toggle dark mode"
          >
            {{darkMode ? <Sun size={{15}} /> : <Moon size={{15}} />}}
          </button>
        </div>
        <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
          {{SIDEBAR_NAV.map(item => {{
            const Icon = _ICON_MAP[item.icon]
            return (
              <Link key={{item.to}} to={{item.to}}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-300 hover:bg-gray-800 hover:text-white transition-colors text-sm font-medium [&.active]:bg-brand-600 [&.active]:text-white">
                {{Icon && <Icon size={{16}} />}}
                {{item.label}}
              </Link>
            )
          }})}}
        </nav>
        <div className="p-3 border-t border-gray-800">
          <button onClick={{handleLogout}}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white transition-colors text-sm">
            <LogOut size={{16}} /> Logout
          </button>
        </div>
      </aside>

      {{/* ── Main content ── */}}
      <div className="flex-1 flex flex-col overflow-hidden">
        {{/* Mobile top bar */}}
        <header className="md:hidden sticky top-0 z-40 bg-white dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800 px-4 h-14 flex items-center justify-between shadow-sm">
          <span className="text-base font-bold text-gray-900 dark:text-white tracking-tight">{project_name}</span>
          <button onClick={{() => setSidebarOpen(true)}}
            className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            aria-label="Open menu">
            <Menu size={{20}} />
          </button>
        </header>

        <main className="flex-1 overflow-y-auto pb-20 md:pb-0 bg-gray-50 dark:bg-gray-900">
          <Outlet />
        </main>

        {{/* ── Mobile bottom tab bar ── */}}
        <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-800 shadow-[0_-4px_16px_rgba(0,0,0,0.06)]"
          aria-label="Bottom navigation">
          <div className="flex items-stretch h-16">
            {{BOTTOM_NAV.map(item => {{
              const Icon = _ICON_MAP[item.icon]
              return (
                <Link key={{item.to}} to={{item.to}}
                  className="flex-1 flex flex-col items-center justify-center gap-1 text-gray-400 hover:text-brand-600 [&.active]:text-brand-600 transition-colors py-2">
                  {{Icon && <Icon size={{20}} />}}
                  <span className="text-[10px] font-medium leading-none">{{item.label}}</span>
                </Link>
              )
            }})}}
          </div>
        </nav>
      </div>

      {{/* ── Mobile slide-in menu overlay ── */}}
      <AnimatePresence>
        {{sidebarOpen && (
          <>
            <motion.div
              initial={{{{ opacity: 0 }}}} animate={{{{ opacity: 1 }}}} exit={{{{ opacity: 0 }}}}
              className="fixed inset-0 z-50 bg-black/50 md:hidden"
              onClick={{() => setSidebarOpen(false)}}
            />
            <motion.aside
              initial={{{{ x: -280 }}}} animate={{{{ x: 0 }}}} exit={{{{ x: -280 }}}}
              transition={{{{ type: 'spring', stiffness: 300, damping: 30 }}}}
              className="fixed left-0 top-0 bottom-0 z-50 w-72 bg-gray-900 text-white flex flex-col md:hidden"
            >
              <div className="p-5 border-b border-gray-800 flex items-center justify-between">
                <span className="text-lg font-bold text-white">{project_name}</span>
                <button onClick={{() => setSidebarOpen(false)}}
                  className="p-2 rounded-lg text-gray-400 hover:bg-gray-800" aria-label="Close menu">
                  <X size={{18}} />
                </button>
              </div>
              <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
                {{SIDEBAR_NAV.map(item => {{
                  const Icon = _ICON_MAP[item.icon]
                  return (
                    <Link key={{item.to}} to={{item.to}} onClick={{() => setSidebarOpen(false)}}
                      className="flex items-center gap-3 px-3 py-3 rounded-lg text-gray-300 hover:bg-gray-800 hover:text-white transition-colors text-sm font-medium [&.active]:bg-brand-600 [&.active]:text-white">
                      {{Icon && <Icon size={{16}} />}} {{item.label}}
                    </Link>
                  )
                }})}}
              </nav>
              <div className="p-3 border-t border-gray-800">
                <button onClick={{handleLogout}}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-400 hover:bg-gray-800 text-sm">
                  <LogOut size={{16}} /> Logout
                </button>
              </div>
            </motion.aside>
          </>
        )}}
      </AnimatePresence>
    </div>
  )
}}
"""


def _generate_page_with_motion(entity_page_code: str) -> str:
    """Wrap a generated entity page component with Framer Motion page transition.

    Inserts a motion.div wrapper around the outermost div in the return statement.
    Falls back to returning the original code unchanged if the pattern isn't found.
    """
    import re as _re
    # Find the return statement's first JSX div and wrap it
    # Pattern: return (\n    <div ...)
    pattern = r'(  return \(\n)(    <div )'
    replacement = (
        r'\1    <motion.div\n'
        r'      initial={{ opacity: 0, y: 8 }}\n'
        r'      animate={{ opacity: 1, y: 0 }}\n'
        r'      transition={{ duration: 0.18, ease: "easeOut" }}\n'
        r'    >\n'
        r'    <div '
    )
    new_code = _re.sub(pattern, replacement, entity_page_code, count=1)
    if new_code == entity_page_code:
        # Pattern didn't match — return unchanged
        return entity_page_code

    # Close the motion.div before the last closing paren
    # Replace the final `  )` with `    </motion.div>\n  )`
    new_code = _re.sub(r'\n  \)\n}$', '\n    </motion.div>\n  )\n}', new_code)

    # Add framer-motion import if not already present
    if 'framer-motion' not in new_code:
        new_code = new_code.replace(
            "// Auto-generated by AetherOS p05_frontend\n",
            "// Auto-generated by AetherOS p05_frontend\nimport { motion } from 'framer-motion'\n",
            1
        )
    return new_code


def _generate_kanban_component(entity_name: str, status_field: str = "status") -> str:
    """Generate a Kanban board component for an entity with a status field.

    Uses the HTML5 drag-and-drop API — no external library required.
    Calls PATCH /{entity_name}/{id} on drop to persist the new status.
    Supports dark mode via Tailwind dark: variants.
    """
    pascal = to_pascal_case(entity_name)
    camel = entity_name[0].lower() + pascal[1:]
    label = to_label(entity_name)
    singular = to_singular(label)

    return f"""\
// Auto-generated by AetherOS p05_frontend — Kanban board for {pascal}
import {{ useState, useCallback }} from 'react'
import {{ useQuery, useMutation, useQueryClient }} from '@tanstack/react-query'
import {{ {camel}Api }} from '../lib/api'
import {{ useToast }} from '../components/Toaster'
import {{ Plus }} from 'lucide-react'

const COLUMNS = ['todo', 'in_progress', 'done'] as const
type Status = typeof COLUMNS[number]

const COLUMN_LABELS: Record<Status, string> = {{
  todo: 'To Do',
  in_progress: 'In Progress',
  done: 'Done',
}}

const COLUMN_COLORS: Record<Status, string> = {{
  todo: 'border-t-gray-400',
  in_progress: 'border-t-blue-500',
  done: 'border-t-green-500',
}}

interface KanbanItem {{
  id: number
  name?: string
  title?: string
  {status_field}: Status
  [key: string]: unknown
}}

function getTitle(item: KanbanItem): string {{
  return String(item.name ?? item.title ?? `Item ${{item.id}}`)
}}

export default function {pascal}KanbanPage() {{
  const qc = useQueryClient()
  const {{ toast }} = useToast()
  const [draggingId, setDraggingId] = useState<number | null>(null)

  const {{ data: rawData = [], isLoading }} = useQuery({{
    queryKey: ['{entity_name}', 'kanban'],
    queryFn: async () => {{
      const res = await {camel}Api.list(1, 200)
      return (Array.isArray(res) ? res : ((res as any)?.items ?? [])) as KanbanItem[]
    }},
  }})

  const patch = useMutation({{
    mutationFn: ({{ id, status }}: {{ id: number; status: Status }}) =>
      {camel}Api.update(id, {{ {status_field}: status }} as any),
    onSuccess: () => {{
      qc.invalidateQueries({{ queryKey: ['{entity_name}'] }})
      toast('{singular} updated', 'success')
    }},
    onError: () => {{ toast('Failed to update {singular}', 'error') }},
  }})

  const itemsByStatus = useCallback(
    (status: Status) => rawData.filter(item => item.{status_field} === status),
    [rawData]
  )

  const handleDragStart = (id: number) => setDraggingId(id)

  const handleDrop = (status: Status) => {{
    if (draggingId === null) return
    const item = rawData.find(i => i.id === draggingId)
    if (item && item.{status_field} !== status) {{
      patch.mutate({{ id: draggingId, status }})
    }}
    setDraggingId(null)
  }}

  if (isLoading) {{
    return (
      <div className="p-8 text-gray-500 dark:text-gray-400 text-sm">Loading board...</div>
    )
  }}

  return (
    <div className="p-4 sm:p-8 bg-white dark:bg-gray-900 min-h-full">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{label} Board</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Drag cards between columns to update status
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {{COLUMNS.map(col => (
          <div
            key={{col}}
            onDragOver={{e => e.preventDefault()}}
            onDrop={{() => handleDrop(col)}}
            className={{`flex flex-col gap-3 min-h-[200px] rounded-xl border-2 border-t-4 ${{COLUMN_COLORS[col]}} border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3`}}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
                {{COLUMN_LABELS[col]}}
              </span>
              <span className="text-xs font-medium bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded-full px-2 py-0.5">
                {{itemsByStatus(col).length}}
              </span>
            </div>

            {{itemsByStatus(col).map(item => (
              <div
                key={{item.id}}
                draggable
                onDragStart={{() => handleDragStart(item.id)}}
                onDragEnd={{() => setDraggingId(null)}}
                className={{`rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 p-3 shadow-sm cursor-grab active:cursor-grabbing transition-opacity ${{draggingId === item.id ? 'opacity-40' : 'opacity-100'}}`}}
              >
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {{getTitle(item)}}
                </p>
              </div>
            ))}}

            {{itemsByStatus(col).length === 0 && (
              <div className="flex-1 flex items-center justify-center">
                <p className="text-xs text-gray-400 dark:text-gray-600">Drop items here</p>
              </div>
            )}}
          </div>
        ))}}
      </div>
    </div>
  )
}}
"""


def _generate_calendar_component(entity_name: str, date_field: str = "date") -> str:
    """Generate a monthly calendar view component for an entity with a date field.

    Navigates prev/next month. Clicking a day opens a modal listing items for that day.
    No external calendar library — pure React + Tailwind.
    Supports dark mode.
    """
    pascal = to_pascal_case(entity_name)
    camel = entity_name[0].lower() + pascal[1:]
    label = to_label(entity_name)

    return f"""\
// Auto-generated by AetherOS p05_frontend — Calendar view for {pascal}
import {{ useState, useMemo }} from 'react'
import {{ useQuery }} from '@tanstack/react-query'
import {{ {camel}Api }} from '../lib/api'
import {{ ChevronLeft, ChevronRight, X }} from 'lucide-react'

interface CalItem {{
  id: number
  {date_field}?: string | null
  name?: string
  title?: string
  [key: string]: unknown
}}

function getLabel(item: CalItem): string {{
  return String(item.name ?? item.title ?? `Item ${{item.id}}`)
}}

function toYMD(d: Date): string {{
  return d.toISOString().slice(0, 10)
}}

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export default function {pascal}CalendarPage() {{
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth())
  const [selectedDay, setSelectedDay] = useState<string | null>(null)

  const {{ data: rawData = [] }} = useQuery({{
    queryKey: ['{entity_name}', 'calendar', year, month],
    queryFn: async () => {{
      const res = await {camel}Api.list(1, 200)
      return (Array.isArray(res) ? res : ((res as any)?.items ?? [])) as CalItem[]
    }},
  }})

  // Build a map of YYYY-MM-DD -> items
  const itemsByDay = useMemo(() => {{
    const map: Record<string, CalItem[]> = {{}}
    for (const item of rawData) {{
      const raw = item.{date_field}
      if (!raw) continue
      const day = String(raw).slice(0, 10)
      if (!map[day]) map[day] = []
      map[day].push(item)
    }}
    return map
  }}, [rawData])

  const prevMonth = () => {{
    if (month === 0) {{ setMonth(11); setYear(y => y - 1) }}
    else setMonth(m => m - 1)
  }}

  const nextMonth = () => {{
    if (month === 11) {{ setMonth(0); setYear(y => y + 1) }}
    else setMonth(m => m + 1)
  }}

  // Generate calendar grid
  const firstDay = new Date(year, month, 1)
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const startWeekday = firstDay.getDay()
  const totalCells = Math.ceil((startWeekday + daysInMonth) / 7) * 7
  const monthName = firstDay.toLocaleString('default', {{ month: 'long' }})

  const todayYMD = toYMD(today)
  const selectedItems = selectedDay ? (itemsByDay[selectedDay] ?? []) : []

  return (
    <div className="p-4 sm:p-8 bg-white dark:bg-gray-900 min-h-full">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{label} Calendar</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={{prevMonth}}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400"
            aria-label="Previous month"
          >
            <ChevronLeft size={{18}} />
          </button>
          <span className="text-base font-semibold text-gray-800 dark:text-gray-200 min-w-[140px] text-center">
            {{monthName}} {{year}}
          </span>
          <button
            onClick={{nextMonth}}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400"
            aria-label="Next month"
          >
            <ChevronRight size={{18}} />
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        {{/* Weekday headers */}}
        <div className="grid grid-cols-7 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
          {{DAY_NAMES.map(d => (
            <div key={{d}} className="py-2 text-center text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              {{d}}
            </div>
          ))}}
        </div>

        {{/* Day cells */}}
        <div className="grid grid-cols-7">
          {{Array.from({{ length: totalCells }}).map((_, i) => {{
            const dayNum = i - startWeekday + 1
            const isValid = dayNum >= 1 && dayNum <= daysInMonth
            if (!isValid) {{
              return <div key={{i}} className="min-h-[80px] bg-gray-50 dark:bg-gray-800/50 border-b border-r border-gray-100 dark:border-gray-800" />
            }}
            const dateObj = new Date(year, month, dayNum)
            const ymd = toYMD(dateObj)
            const dayItems = itemsByDay[ymd] ?? []
            const isToday = ymd === todayYMD
            const isSelected = ymd === selectedDay
            return (
              <button
                key={{i}}
                onClick={{() => setSelectedDay(ymd === selectedDay ? null : ymd)}}
                className={{`min-h-[80px] text-left p-1.5 border-b border-r border-gray-100 dark:border-gray-800 hover:bg-brand-50 dark:hover:bg-brand-900/20 transition-colors ${{isSelected ? 'bg-brand-50 dark:bg-brand-900/30' : ''}} ${{isToday ? 'ring-1 ring-inset ring-brand-400' : ''}}`}}
              >
                <span className={{`text-xs font-medium ${{isToday ? 'bg-brand-600 text-white rounded-full w-5 h-5 flex items-center justify-center' : 'text-gray-600 dark:text-gray-400'}}`}}>
                  {{dayNum}}
                </span>
                <div className="mt-1 space-y-0.5">
                  {{dayItems.slice(0, 2).map(item => (
                    <div key={{item.id}} className="text-xs bg-brand-100 dark:bg-brand-900/50 text-brand-700 dark:text-brand-300 rounded px-1 truncate">
                      {{getLabel(item)}}
                    </div>
                  ))}}
                  {{dayItems.length > 2 && (
                    <div className="text-xs text-gray-400 dark:text-gray-500 pl-1">
                      +{{dayItems.length - 2}} more
                    </div>
                  )}}
                </div>
              </button>
            )
          }})}}
        </div>
      </div>

      {{/* Day detail modal */}}
      {{selectedDay && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-xl w-full max-w-md mx-4 max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
              <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                {{new Date(selectedDay + 'T00:00:00').toLocaleDateString('default', {{ weekday: 'long', month: 'long', day: 'numeric' }})}}
              </h2>
              <button
                onClick={{() => setSelectedDay(null)}}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 p-1"
                aria-label="Close"
              >
                <X size={{18}} />
              </button>
            </div>
            <div className="overflow-y-auto p-4 space-y-2">
              {{selectedItems.length === 0 ? (
                <p className="text-sm text-gray-500 dark:text-gray-400">No items on this day.</p>
              ) : selectedItems.map(item => (
                <div key={{item.id}} className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 bg-gray-50 dark:bg-gray-800">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{{getLabel(item)}}</p>
                </div>
              ))}}
            </div>
          </div>
        </div>
      )}}
    </div>
  )
}}
"""


def _generate_command_palette(entities: List[str]) -> str:
    """Generate a Cmd+K command palette component that searches across all entity types.

    Opens on Ctrl+K / Cmd+K. Searches all entities, groups results by type.
    Arrow-key navigation, Enter to navigate, Escape to close.
    Full-screen overlay with dark mode support.
    Wire into root App component as a persistent global component.
    """
    # Build per-entity search hooks
    entity_list_ts = ", ".join(f"'{e}'" for e in entities)
    entity_labels = {e: to_label(e) for e in entities}
    entity_labels_ts = "{\n" + "".join(
        f"  '{e}': '{entity_labels[e]}',\n" for e in entities
    ) + "}"
    camel_map = {e: (e[0].lower() + to_pascal_case(e)[1:]) for e in entities}
    api_imports = ", ".join(f"{camel_map[e]}Api" for e in entities)

    return f"""\
// Auto-generated by AetherOS p05_frontend — Cmd+K Command Palette
// Wire into App.tsx: render <CommandPalette /> inside the router root.
import {{ useState, useEffect, useRef, useCallback }} from 'react'
import {{ useNavigate }} from '@tanstack/react-router'
import {{ {api_imports} }} from '../lib/api'
import {{ Search, X }} from 'lucide-react'

const ENTITIES = [{entity_list_ts}] as const
type EntityKey = typeof ENTITIES[number]

const ENTITY_LABELS: Record<EntityKey, string> = {entity_labels_ts}

interface Result {{
  id: number
  label: string
  entity: EntityKey
  href: string
}}

async function searchEntity(entity: EntityKey, query: string): Promise<Result[]> {{
  // Map entity keys to their API objects
  const apiMap: Record<EntityKey, {{ list: (page: number, size: number) => Promise<unknown> }}> = {{
    {chr(10).join(f"    '{e}': {camel_map[e]}Api," for e in entities)}
  }}
  try {{
    const res = await apiMap[entity].list(1, 100)
    const items: unknown[] = Array.isArray(res) ? res : ((res as any)?.items ?? [])
    const q = query.toLowerCase()
    return (items as any[])
      .filter((item: any) => {{
        const label = String(item.name ?? item.title ?? item.email ?? item.id ?? '')
        return label.toLowerCase().includes(q)
      }})
      .slice(0, 5)
      .map((item: any) => ({{
        id: item.id,
        label: String(item.name ?? item.title ?? item.email ?? `ID ${{item.id}}`),
        entity,
        href: `/${{entity}}/${{item.id}}`,
      }}))
  }} catch {{
    return []
  }}
}}

export function CommandPalette() {{
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Result[]>([])
  const [activeIdx, setActiveIdx] = useState(0)
  const [searching, setSearching] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  // Open on Ctrl+K / Cmd+K
  useEffect(() => {{
    const handler = (e: KeyboardEvent) => {{
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {{
        e.preventDefault()
        setOpen(prev => !prev)
      }}
    }}
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }}, [])

  // Focus input when opened
  useEffect(() => {{
    if (open) {{
      setQuery('')
      setResults([])
      setActiveIdx(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }}
  }}, [open])

  // Search across all entities when query changes
  useEffect(() => {{
    if (!query.trim()) {{
      setResults([])
      return
    }}
    setSearching(true)
    Promise.all(ENTITIES.map(e => searchEntity(e, query.trim())))
      .then(arrays => {{
        setResults(arrays.flat())
        setActiveIdx(0)
      }})
      .finally(() => setSearching(false))
  }}, [query])

  const close = useCallback(() => setOpen(false), [])

  const handleKeyDown = (e: React.KeyboardEvent) => {{
    if (e.key === 'Escape') {{ close(); return }}
    if (e.key === 'ArrowDown') {{
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, results.length - 1))
    }} else if (e.key === 'ArrowUp') {{
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    }} else if (e.key === 'Enter' && results[activeIdx]) {{
      void navigate({{ to: results[activeIdx].href }})
      close()
    }}
  }}

  if (!open) return null

  // Group results by entity
  const grouped = ENTITIES.reduce<Record<string, Result[]>>((acc, ent) => {{
    const group = results.filter(r => r.entity === ent)
    if (group.length) acc[ent] = group
    return acc
  }}, {{}})

  let globalIdx = 0

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] bg-black/60 backdrop-blur-sm"
      onClick={{e => {{ if (e.target === e.currentTarget) close() }}}}
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <div className="w-full max-w-xl mx-4 bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        {{/* Search input */}}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <Search size={{18}} className="text-gray-400 dark:text-gray-500 shrink-0" />
          <input
            ref={{inputRef}}
            value={{query}}
            onChange={{e => setQuery(e.target.value)}}
            onKeyDown={{handleKeyDown}}
            placeholder="Search across all records..."
            className="flex-1 bg-transparent text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-600 text-sm outline-none"
          />
          {{query && (
            <button onClick={{() => setQuery('')}} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
              <X size={{16}} />
            </button>
          )}}
          <kbd className="hidden sm:inline-flex items-center gap-1 text-xs text-gray-400 dark:text-gray-500 border border-gray-200 dark:border-gray-700 rounded px-1.5 py-0.5">
            ESC
          </kbd>
        </div>

        {{/* Results */}}
        <div className="max-h-[50vh] overflow-y-auto py-2">
          {{searching && (
            <div className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500">Searching...</div>
          )}}
          {{!searching && query && results.length === 0 && (
            <div className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500">No results for "{{query}}"</div>
          )}}
          {{!query && (
            <div className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500">
              Type to search across {{ENTITIES.map(e => ENTITY_LABELS[e]).join(', ')}}
            </div>
          )}}
          {{Object.entries(grouped).map(([ent, items]) => (
            <div key={{ent}}>
              <div className="px-4 py-1.5 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide">
                {{ENTITY_LABELS[ent as EntityKey]}}
              </div>
              {{items.map(item => {{
                const idx = globalIdx++
                const isActive = idx === activeIdx
                return (
                  <button
                    key={{`${{ent}}-${{item.id}}`}}
                    onClick={{() => {{ void navigate({{ to: item.href }}); close() }}}}
                    onMouseEnter={{() => setActiveIdx(idx)}}
                    className={{`w-full text-left px-4 py-2 text-sm flex items-center gap-3 transition-colors ${{
                      isActive
                        ? 'bg-brand-50 dark:bg-brand-900/30 text-brand-700 dark:text-brand-300'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
                    }}`}}
                  >
                    <span className="flex-1 truncate">{{item.label}}</span>
                    {{isActive && (
                      <kbd className="text-xs text-gray-400 dark:text-gray-500 border border-current rounded px-1">↵</kbd>
                    )}}
                  </button>
                )
              }})}}
            </div>
          ))}}
        </div>
      </div>
    </div>
  )
}}
"""


# Public aliases for functions that task_agent.py imports by name.
# These were accidentally made private during a refactor; restoring public names here
# keeps task_agent.py's import list intact without renaming 28 internal call sites.
generate_eslint_config = _generate_eslint_config
generate_vite_config = _generate_vite_config
generate_tsconfig = _generate_tsconfig
generate_tailwind_config = _generate_tailwind_config
generate_postcss_config = _generate_postcss_config
generate_index_html = _generate_index_html
generate_nginx_conf = _generate_nginx_conf
generate_dockerfile = _generate_dockerfile
generate_env_example = _generate_env_example
generate_headers_file = _generate_headers_file
generate_index_css = _generate_index_css
generate_main_tsx = _generate_main_tsx
generate_auth_ts = _generate_auth_ts
generate_types = _generate_types
generate_api = _generate_api
generate_app = _generate_app
generate_admin_layout = _generate_admin_layout
generate_customer_layout = _generate_customer_layout
generate_customer_home = _generate_customer_home
generate_layout = _generate_layout
generate_data_table = _generate_data_table
generate_crud_modal = _generate_crud_modal
generate_toaster = _generate_toaster
generate_vitest_config = _generate_vitest_config
generate_test_setup = _generate_test_setup
generate_login_test = _generate_login_test
generate_dashboard_test = _generate_dashboard_test
generate_error_boundary = _generate_error_boundary
generate_not_found_page = _generate_not_found_page
generate_frontend_readme = _generate_frontend_readme
generate_login_page = _generate_login_page
generate_dashboard = _generate_dashboard
generate_storefront_home = _generate_storefront_home
generate_entity_page = _generate_entity_page
generate_product_grid_page = _generate_product_grid_page
generate_docker_compose = _generate_docker_compose
generate_use_sse_hook = _generate_use_sse_hook
is_product_entity = _is_product_entity

# New premium UI generators
generate_lib_utils = _generate_lib_utils
generate_ui_button = _generate_ui_button
generate_ui_input = _generate_ui_input
generate_ui_card = _generate_ui_card
generate_ui_badge = _generate_ui_badge
generate_ui_skeleton = _generate_ui_skeleton
generate_ui_modal = _generate_ui_modal
generate_ui_select = _generate_ui_select
generate_ui_toast = _generate_ui_toast
generate_ui_tooltip = _generate_ui_tooltip
generate_ui_table = _generate_ui_table
generate_domain_dashboard = _generate_domain_dashboard
generate_mobile_first_layout = _generate_mobile_first_layout
generate_page_with_motion = _generate_page_with_motion
generate_use_websocket_hook = _generate_use_websocket_hook

# New interactive view generators (Items 4-6)
generate_kanban_component = _generate_kanban_component
generate_calendar_component = _generate_calendar_component
generate_command_palette = _generate_command_palette
