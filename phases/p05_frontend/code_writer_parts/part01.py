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
    """tailwind.config.js of the run's design tokens (KAN-243). It held 17 hard-coded hex brand palettes picked by
    domain or ui_theme; every color, font, radius and shadow now reads a CSS variable that index.css defines."""
    from aether_os.phases.p05_frontend.theme_tokens import current_theme   # lazy: theme_tokens imports this module
    return current_theme().tailwind_config(ui_theme)


def _generate_postcss_config() -> str:
    return """\
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} }
}
"""


def _generate_index_html(project_name: str, description: str = "", domain: str = "saas", theme_color: str = "") -> str:
    # Both values come from the spec: escaped for HTML text/attributes, and JSON-encoded (with `<` neutralised, so
    # `</script>` cannot end the block) inside the JSON-LD script. `x</title><script>` used to run as a script.
    _desc = description or f"{project_name} — the modern platform built for your business."
    _ld_name = json.dumps(project_name).replace("<", "\\u003c")
    _ld_desc = json.dumps(_desc).replace("<", "\\u003c")
    project_name = html.escape(project_name, quote=True)
    _desc = html.escape(_desc, quote=True)
    # The browser UI color is the token primary (passed in by the run theme), never a fixed hex.
    _theme_meta = f'  <meta name="theme-color" content="{html.escape(theme_color, quote=True)}" />\n' if theme_color else ""
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
{_theme_meta}
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

  <!-- Fonts: src/index.css imports the pair the design tokens chose -->

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
