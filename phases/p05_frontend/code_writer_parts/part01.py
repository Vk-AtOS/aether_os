from __future__ import annotations

import html
import json


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
