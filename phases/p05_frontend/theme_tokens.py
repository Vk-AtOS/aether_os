"""The design token set of one run (KAN-243): generated once from the spec, written as the app's theme, and quoted in
every model page prompt.

    theme = build_run_theme(data, project_name, domain, primary_hex)   # once per run, after the design brief
    theme.tailwind_config()    -> tailwind.config.js: every color, font, radius and shadow reads a CSS variable
    theme.index_css(**opts)    -> src/index.css: the :root / .dark variables (core/rulepacks tokens), then the motion CSS
    theme.page_rules()         -> DESIGN RULES + SECURITY RULES for a page prompt (bounded, see spec_rules.MAX_RULES_CHARS)
    current_theme()            -> the run's theme (a ContextVar, so the page writers need no new parameter)

It replaces the per-domain palettes (19 hard-coded Tailwind color sets in design_system.py, 17 hex brand ramps in
tailwind.config.js) that made every CRM look like every other CRM and could not pass a contrast check. The tokens come
from core/rulepacks/design_tokens.py: deterministic, WCAG AA text contrast enforced, light and dark sets.
"""
from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from aether_os.core.rulepacks import design_prompt_rules, generate_tokens
from aether_os.core.rulepacks.color import to_hex
from aether_os.core.rulepacks.design_catalog import MOODS, canonical_site_type
from aether_os.core.rulepacks.design_tokens import DesignTokens
from aether_os.core.rulepacks.spec_rules import MAX_RULES_CHARS, security_rules_for

logger = logging.getLogger(__name__)

# The run's domain -> rule-pack site type. A spec that names its shape (site_type / app_shape) wins.
SITE_BY_DOMAIN = {
    "ecommerce": "ecommerce", "marketplace": "ecommerce", "retail": "ecommerce", "shop": "ecommerce",
    "restaurant": "booking", "hospitality": "booking", "healthcare": "booking", "fitness": "booking",
    "gym_fitness": "booking", "real_estate": "booking", "salon": "booking", "booking": "booking",
    "events": "booking", "travel": "booking",
    "blog": "content", "news": "content", "media": "content", "publishing": "content", "education": "content",
    "portfolio": "portfolio", "agency": "portfolio",
    "erp": "internal_tool", "hrm": "internal_tool", "logistics": "internal_tool", "inventory": "internal_tool",
    "iot": "internal_tool", "security": "internal_tool", "manufacturing": "internal_tool",
    "ai_agent": "agent_chat", "chatbot": "agent_chat",
}
# Mood words implied by a domain when the description names none (keys of design_catalog.MOODS).
DOMAIN_MOODS = {
    "healthcare": "medical", "fintech": "finance", "restaurant": "food", "food": "food", "fitness": "sport",
    "gym_fitness": "sport", "sports": "sport", "education": "friendly", "legal": "legal", "hospitality": "warm",
    "real_estate": "trust", "crm": "professional", "hrm": "professional", "analytics": "professional",
    "security": "serious", "iot": "tech", "logistics": "professional", "library": "editorial",
}
DENSITY_MOODS = {"compact": "professional", "spacious": "calm"}
_SEMANTIC = {   # what the page prompts and templates use instead of a palette
    "bg_page": "bg-background", "bg_card": "bg-card", "bg_dark": "bg-foreground", "text_primary": "text-foreground",
    "text_muted": "text-muted-foreground", "text_inverse": "text-primary-foreground", "accent": "primary",
    "accent_light": "accent", "border": "border-border", "ring": "ring-ring", "font": "font-sans",
    "radius": "rounded-lg", "shadow": "shadow-sm", "gradient": "none (solid bg-primary)",
}
# Soft tints for status surfaces (alerts, badges). Tailwind v3 cannot put an opacity modifier on a var() color,
# so the tint is mixed in CSS; text on it uses the strong token.
_SOFT = {f"{k}-soft": f"color-mix(in oklch, var(--{k}) 14%, var(--background))"
         for k in ("primary", "destructive", "success", "warning")}

_RUN: ContextVar[Optional["RunTheme"]] = ContextVar("p05_run_theme", default=None)


def site_type_for(data: dict, domain: str) -> str:
    for key in ("site_type", "app_shape"):
        named = str((data or {}).get(key) or "").strip()
        if named:
            try:
                return canonical_site_type("landing" if named.lower() in ("website", "marketing_site") else named)
            except ValueError as e:
                logger.warning("p05 theme: %s=%r is not a site type, using the domain: %s", key, named, e)
    return SITE_BY_DOMAIN.get((domain or "").lower(), "saas_dashboard")


def moods_for(data: dict, domain: str, density: str = "") -> list[str]:
    """Mood words named in the description and tagline, then the brief's density, then the domain's default."""
    data = data or {}
    text = " ".join(str(data.get(k) or "") for k in ("raw_input", "app_tagline")).lower()
    named = [w for w in re.findall(r"[a-z]+", text) if w in MOODS]
    extra = [m for m in (str(((data.get("designer_spec") or {}).get("design") or {}).get("mood") or "").lower(),
                         DENSITY_MOODS.get(density or ""), DOMAIN_MOODS.get((domain or "").lower())) if m in MOODS]
    return list(dict.fromkeys(named + extra))[:4]


@dataclass
class RunTheme:
    tokens: DesignTokens
    site_type: str
    security: str      # the frontend SECURITY RULES for this run's features (core/rulepacks/spec_rules.py)

    def page_rules(self) -> str:
        """DESIGN RULES for this site type with the token summary, then the frontend SECURITY RULES."""
        return design_prompt_rules(self.site_type, self.tokens) + "\n\n" + self.security

    def prompt_tokens(self) -> dict:
        """The dict the page writers format into their prompts: semantic classes, never a palette."""
        return {**_SEMANTIC, "rules": self.page_rules()}

    def tailwind_config(self, _ui_theme: str = "") -> str:
        """tailwind.config.js whose theme reads the CSS variables of index.css (the ui_theme name no longer picks a
        palette: the tokens do)."""
        t = self.tokens
        colors = {k: f"var(--{k})" for k in t.light}
        colors.update(_SOFT)
        colors["brand"] = {str(s): f"var(--brand-{s})" for s in t.ramps["brand"]}
        colors["neutral"] = {str(s): f"var(--neutral-{s})" for s in t.ramps["neutral"]}
        extend = {
            "colors": colors,
            "fontFamily": {"heading": ["var(--font-heading)"], "sans": ["var(--font-body)"], "mono": ["var(--font-mono)"]},
            "fontSize": {k: [v["size"], {"lineHeight": v["line_height"], "letterSpacing": v["tracking"]}]
                         for k, v in t.type_scale.items()},
            "borderRadius": {"sm": t.radius["sm"], "md": t.radius["md"], "lg": t.radius["lg"], "xl": t.radius["lg"],
                             "2xl": t.radius["lg"], "full": t.radius["full"]},
            "boxShadow": {k: f"var(--shadow-{k})" for k in t.shadows},
            "transitionDuration": {k: v for k, v in t.motion.items() if k != "ease"},
        }
        return ("// Generated from the design tokens in src/index.css (AetherOS rule packs). Change the brief, not this file.\n"
                "export default {\n  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],\n  darkMode: 'class',\n"
                f"  theme: {{\n    extend: {json.dumps(extend, indent=2).replace(chr(10), chr(10) + '    ')}\n  }},\n"
                "  plugins: [],\n}\n")

    def index_css(self, **opts) -> str:
        """src/index.css: font import first (CSS requires @import before other rules), the Tailwind layers, the token
        variables, then the motion helpers of the designer spec."""
        from aether_os.phases.p05_frontend.code_writer_parts.part02 import _generate_index_css   # lazy: import cycle
        token_css = self.tokens.to_css().splitlines()
        imports = [ln for ln in token_css if ln.startswith("@import")]
        body = [ln for ln in token_css if not ln.startswith("@import")]
        rest = _generate_index_css(**opts).replace("@tailwind base;\n@tailwind components;\n@tailwind utilities;\n", "")
        return "\n".join(imports + ["@tailwind base;", "@tailwind components;", "@tailwind utilities;", ""] + body) + "\n" + rest

    def index_html(self, project_name: str, description: str = "", domain: str = "saas") -> str:
        from aether_os.phases.p05_frontend.code_writer_parts.part01 import _generate_index_html   # lazy: import cycle
        return _generate_index_html(project_name, description, domain, theme_color=to_hex(self.tokens.light["primary"]))


def build_run_theme(data: dict, project_name: str, domain: str, primary_hex: str = "", density: str = "") -> RunTheme:
    """Generate the run's tokens once and make them the current theme for the page writers."""
    site = site_type_for(data, domain)
    moods = moods_for(data, domain, density)
    try:
        tokens = generate_tokens(site, brand_name=project_name or site, moods=moods, primary=primary_hex or None)
    except ValueError as e:      # a brief colour the generator rejects: the tokens choose the hue instead
        logger.warning("p05 theme: primary %r rejected (%s); hue from the moods", primary_hex, e)
        tokens = generate_tokens(site, brand_name=project_name or site, moods=moods)
    theme = RunTheme(tokens=tokens, site_type=site, security=security_rules_for(data or {}, "frontend"))
    _RUN.set(theme)
    logger.info("p05 theme: site_type=%s moods=%s fonts=%s/%s contrast adjustments=%d", site, moods,
                tokens.fonts.heading, tokens.fonts.body, len(tokens.adjustments))
    return theme


def current_theme() -> RunTheme:
    """The run's theme; outside a run (a test, a single page regeneration) a default dashboard theme."""
    theme = _RUN.get()
    return theme if theme is not None else build_run_theme({}, "", "saas")


def page_rules_block() -> str:
    """The run's DESIGN + SECURITY RULES for one page prompt, capped at MAX_RULES_CHARS."""
    return current_theme().page_rules()[:MAX_RULES_CHARS]
