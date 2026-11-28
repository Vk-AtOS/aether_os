"""P05 Frontend: the design tokens the page prompts quote (KAN-243).

This module held 19 hard-coded per-domain Tailwind palettes (bg-teal-50, text-indigo-900, from-indigo-600 to-violet-600,
...). The model copied them into every page, so pages ignored the app's theme, failed contrast in dark mode and all
shared the same violet gradient. The run now generates one token set from the spec (theme_tokens.py, backed by
core/rulepacks): pages get semantic classes (bg-background, bg-card, text-foreground, bg-primary, ...) plus the design and
security rules of the run, and the colors live in CSS variables only.

  get_design_tokens(domain) -> {"bg_page": "bg-background", ..., "rules": "<DESIGN RULES + SECURITY RULES>"}
"""
from __future__ import annotations

from aether_os.phases.p05_frontend.theme_tokens import current_theme


def get_design_tokens(domain: str = "") -> dict:
    """The run's semantic token classes and prompt rules. `domain` is kept for callers; the run theme decides."""
    return current_theme().prompt_tokens()
