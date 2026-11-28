"""Deterministic design-token generator (no model call).

    tokens = generate_tokens("booking", brand_name="Juniper Dental", moods=["calm"], primary="#2a7f8f")
    tokens.to_css()        # :root and .dark blocks, shadcn variable names, OKLCH values
    tokens.to_tailwind()   # theme.extend snippet for tailwind.config (v3)

Every text pair (x / x-foreground) is held to WCAG AA 4.5:1 and every UI pair (ring, input, primary on the
page, chart colors) to 3:1. A pair that misses is adjusted, never emitted as is; `tokens.adjustments`
records what moved.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from aether_os.core.rulepacks import color as C
from aether_os.core.rulepacks.design_catalog import (PROFILES, FontPair, canonical_site_type, pick_fonts, pick_hue)

STEPS = (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950)
_BRAND_L = (0.975, 0.945, 0.885, 0.805, 0.715, 0.625, 0.545, 0.465, 0.385, 0.305, 0.235)
_BRAND_C = (0.12, 0.25, 0.5, 0.75, 0.92, 1.0, 0.95, 0.85, 0.72, 0.58, 0.45)
_NEUTRAL_L = (0.985, 0.967, 0.922, 0.87, 0.708, 0.556, 0.439, 0.371, 0.269, 0.205, 0.145)
SPACING_PX = (0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 56, 64, 80, 96, 112, 128)  # 4px grid only
TYPE_STEPS = (("xs", -2), ("sm", -1), ("base", 0), ("lg", 1), ("xl", 2), ("2xl", 3), ("3xl", 4), ("4xl", 5),
              ("5xl", 6), ("6xl", 7))
TEXT_MIN, UI_MIN = 4.5, 3.0

# (foreground, background, minimum). Checked in this order, so a background is final before its text is fitted.
PAIRS = (
    ("primary", "background", UI_MIN), ("ring", "background", UI_MIN), ("input", "background", UI_MIN),
    ("foreground", "background", TEXT_MIN), ("card-foreground", "card", TEXT_MIN),
    ("popover-foreground", "popover", TEXT_MIN), ("primary-foreground", "primary", TEXT_MIN),
    ("secondary-foreground", "secondary", TEXT_MIN), ("muted-foreground", "muted", TEXT_MIN),
    ("muted-foreground", "background", TEXT_MIN), ("accent-foreground", "accent", TEXT_MIN),
    ("destructive", "background", UI_MIN), ("destructive-foreground", "destructive", TEXT_MIN),
    ("success-foreground", "success", TEXT_MIN), ("warning-foreground", "warning", TEXT_MIN),
    ("sidebar-foreground", "sidebar", TEXT_MIN), ("sidebar-primary-foreground", "sidebar-primary", TEXT_MIN),
    ("sidebar-accent-foreground", "sidebar-accent", TEXT_MIN),
    *((f"chart-{i}", "background", UI_MIN) for i in range(1, 6)),
)
# Backgrounds that must keep the brand color: when their text cannot be fitted, the background moves instead.
_MOVE_BG = {"primary-foreground", "destructive-foreground", "success-foreground", "warning-foreground",
            "sidebar-primary-foreground"}


def _ramp(hue: float, chroma: float, lightness=_BRAND_L, shape=_BRAND_C) -> dict[int, C.RGB]:
    return {s: C.oklch_to_srgb((L, chroma * k, hue)) for s, L, k in zip(STEPS, lightness, shape)}


@dataclass
class DesignTokens:
    site_type: str
    brand_name: str
    fonts: FontPair
    ramps: dict[str, dict[int, C.RGB]]
    light: dict[str, C.RGB]
    dark: dict[str, C.RGB]
    type_scale: dict[str, dict[str, str]]
    spacing: dict[str, str]
    radius: dict[str, str]
    shadows: dict[str, str]
    motion: dict[str, str]
    adjustments: list[str] = field(default_factory=list)

    def contrast_report(self) -> list[tuple[str, str, str, float, float]]:
        """(mode, fg, bg, ratio, minimum) for every checked pair."""
        return [(mode, fg, bg, C.contrast_ratio(t[fg], t[bg]), mn)
                for mode, t in (("light", self.light), ("dark", self.dark)) for fg, bg, mn in PAIRS]

    def failing_pairs(self) -> list[tuple[str, str, str, float, float]]:
        return [r for r in self.contrast_report() if r[3] < r[4]]

    def font_import_url(self) -> str:
        """Google Fonts css2 URL, display=swap, at most 4 weights per family."""
        fams: dict[str, set[int]] = {}
        fams.setdefault(self.fonts.heading, set()).update(self.fonts.heading_weights)
        fams.setdefault(self.fonts.body, set()).update(self.fonts.body_weights)
        parts = [f"family={n.replace(' ', '+')}:wght@{';'.join(str(w) for w in sorted(ws)[:4])}" for n, ws in fams.items()]
        return "https://fonts.googleapis.com/css2?" + "&".join(parts) + "&display=swap"

    def to_css(self) -> str:
        def block(sel: str, t: dict[str, C.RGB], extra: bool) -> list[str]:
            out = [f"{sel} {{"]
            out += [f"  --{k}: {C.oklch_css(v)};" for k, v in t.items()]
            if extra:
                out += [f"  --radius: {self.radius['md']};",
                        f"  --font-heading: '{self.fonts.heading}', ui-serif, Georgia, serif;"
                        if self._heading_is_serif() else f"  --font-heading: '{self.fonts.heading}', ui-sans-serif, system-ui, sans-serif;",
                        f"  --font-body: '{self.fonts.body}', ui-sans-serif, system-ui, sans-serif;",
                        f"  --font-mono: '{self.fonts.mono}', ui-monospace, monospace;"]
                out += [f"  --space-{k}: {v};" for k, v in self.spacing.items()]
                out += [f"  --text-{k}: {v['size']};" for k, v in self.type_scale.items()]
                out += [f"  --shadow-{k}: {v};" for k, v in self.shadows.items()]
                out += [f"  --duration-{k}: {v};" for k, v in self.motion.items() if k != "ease"]
                out += [f"  --ease-standard: {self.motion['ease']};"]
                for name, ramp in self.ramps.items():
                    out += [f"  --{name}-{s}: {C.oklch_css(v)};" for s, v in ramp.items()]
            return out + ["}"]

        lines = [f"/* Design tokens for {self.brand_name} ({self.site_type}). Generated by aether_os.core.rulepacks; "
                 "edit the brief, not this file. */",
                 f"@import url('{self.font_import_url()}');", ""]
        lines += block(":root", self.light, True) + [""] + block(".dark", self.dark, False)
        lines += ["", "body {", "  background: var(--background);", "  color: var(--foreground);",
                  "  font-family: var(--font-body);", f"  font-size: {self.type_scale['base']['size']};",
                  "  line-height: 1.5;", "}",
                  "h1, h2, h3, h4 { font-family: var(--font-heading); line-height: 1.15; text-wrap: balance; }",
                  "@media (prefers-reduced-motion: reduce) {",
                  "  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }",
                  "}", ""]
        return "\n".join(lines)

    def _heading_is_serif(self) -> bool:
        return any(w in self.fonts.heading for w in ("Serif", "Fraunces", "Playfair", "Lora", "Newsreader",
                                                     "Baskerville", "Cormorant", "Spectral"))

    def to_tailwind(self) -> str:
        """Theme extension for tailwind.config.js (Tailwind v3): semantic colors read the CSS variables."""
        # Flat keys give the same class names as nested ones (bg-primary, text-primary-foreground).
        colors = {k: f"var(--{k})" for k in self.light}
        theme = {
            "colors": colors,
            "fontFamily": {"heading": ["var(--font-heading)"], "sans": ["var(--font-body)"],
                           "mono": ["var(--font-mono)"]},
            "borderRadius": {"lg": "var(--radius)", "md": "calc(var(--radius) - 2px)",
                             "sm": "calc(var(--radius) - 4px)", "xl": self.radius["lg"]},
            "boxShadow": {k: f"var(--shadow-{k})" for k in self.shadows},
            "transitionDuration": {k: v for k, v in self.motion.items() if k != "ease"},
        }
        return "// Paste into tailwind.config.js -> theme.extend\nmodule.exports.themeExtend = " + json.dumps(theme, indent=2) + ";\n"

    def to_dict(self) -> dict:
        return {
            "site_type": self.site_type, "brand_name": self.brand_name,
            "fonts": {"heading": self.fonts.heading, "body": self.fonts.body, "mono": self.fonts.mono,
                      "import_url": self.font_import_url()},
            "light": {k: C.to_hex(v) for k, v in self.light.items()},
            "dark": {k: C.to_hex(v) for k, v in self.dark.items()},
            "type_scale": self.type_scale, "spacing": self.spacing, "radius": self.radius,
            "shadows": self.shadows, "motion": self.motion, "adjustments": self.adjustments,
        }


def _type_scale(ratio: float, base_px: int, fluid: bool) -> dict[str, dict[str, str]]:
    out = {}
    for name, step in TYPE_STEPS:
        px = base_px * ratio ** step
        size = f"{px / 16:.3f}rem".replace(".000rem", "rem")
        if fluid and step >= 5:
            # Linear from 70% of the size at a 375px viewport to the full size at 1280px.
            lo, hi = px * 0.7, px
            slope = (hi - lo) / (1280 - 375)
            size = f"clamp({lo / 16:.3f}rem, {(lo - slope * 375) / 16:.3f}rem + {slope * 100:.3f}vw, {hi / 16:.3f}rem)"
        lh = "1.5" if step <= 1 else ("1.3" if step <= 3 else "1.15")
        tracking = "-0.02em" if step >= 5 else ("-0.01em" if step >= 3 else "0")
        out[name] = {"size": size, "line_height": lh, "tracking": tracking}
    return out


def _shadows(hue: float) -> dict[str, str]:
    tint = f"oklch(0.25 0.03 {hue:.0f}"  # shadows tinted toward the brand hue, layered for depth
    return {"sm": f"0 1px 2px {tint} / 0.06), 0 1px 1px {tint} / 0.04)",
            "md": f"0 2px 4px {tint} / 0.06), 0 6px 12px -2px {tint} / 0.08)",
            "lg": f"0 4px 8px {tint} / 0.06), 0 16px 32px -8px {tint} / 0.14)"}


def _semantic(brand, neutral, red, green, amber, charts, dark: bool, primary_rgb) -> dict[str, C.RGB]:
    n, b = neutral, brand
    if not dark:
        bg, card = C.oklch_to_srgb((0.995, 0.003, C.srgb_to_oklch(n[50])[2])), C.WHITE
        t = {"background": bg, "foreground": n[950], "card": card, "card-foreground": n[950],
             "popover": card, "popover-foreground": n[950], "primary": primary_rgb or b[600],
             "primary-foreground": C.WHITE, "secondary": n[100], "secondary-foreground": n[900],
             "muted": n[100], "muted-foreground": n[600], "accent": b[100], "accent-foreground": b[900],
             "destructive": red[600], "destructive-foreground": C.WHITE, "success": green[600],
             "success-foreground": C.WHITE, "warning": amber[400], "warning-foreground": n[950],
             "border": n[200], "input": n[400], "ring": b[500], "sidebar": n[50], "sidebar-foreground": n[900],
             "sidebar-primary": b[600], "sidebar-primary-foreground": C.WHITE, "sidebar-accent": n[100],
             "sidebar-accent-foreground": n[900], "sidebar-border": n[200], "sidebar-ring": b[500]}
        t.update({f"chart-{i + 1}": c[600] for i, c in enumerate(charts)})
    else:
        t = {"background": n[950], "foreground": n[50], "card": n[900], "card-foreground": n[50],
             "popover": n[900], "popover-foreground": n[50], "primary": b[400], "primary-foreground": n[950],
             "secondary": n[800], "secondary-foreground": n[50], "muted": n[800], "muted-foreground": n[400],
             "accent": b[900], "accent-foreground": b[100], "destructive": red[500],
             "destructive-foreground": C.WHITE, "success": green[500], "success-foreground": n[950],
             "warning": amber[400], "warning-foreground": n[950], "border": n[800], "input": n[600],
             "ring": b[400], "sidebar": n[900], "sidebar-foreground": n[50], "sidebar-primary": b[400],
             "sidebar-primary-foreground": n[950], "sidebar-accent": n[800], "sidebar-accent-foreground": n[50],
             "sidebar-border": n[800], "sidebar-ring": b[400]}
        t.update({f"chart-{i + 1}": c[400] for i, c in enumerate(charts)})
    return t


def _enforce(t: dict[str, C.RGB], mode: str, log: list[str]) -> None:
    for fg, bg, mn in PAIRS:
        before = C.contrast_ratio(t[fg], t[bg])
        if before >= mn:
            continue
        if fg in _MOVE_BG:
            moved = C.fit_contrast(t[bg], t[fg], mn)
            # Keep the brand background unless moving it would also break it against the page.
            if C.contrast_ratio(moved, t["background"]) >= UI_MIN or bg not in ("primary", "destructive"):
                t[bg] = moved
                if bg == "primary":
                    t["sidebar-primary"] = moved
            else:
                t[fg] = C.fit_contrast(t[fg], t[bg], mn)
        else:
            t[fg] = C.fit_contrast(t[fg], t[bg], mn)
        log.append(f"{mode}: {fg} on {bg} was {before:.2f}:1, adjusted to {C.contrast_ratio(t[fg], t[bg]):.2f}:1")


def generate_tokens(site_type: str, brand_name: str = "", moods: list[str] | None = None,
                    primary: str | None = None) -> DesignTokens:
    """Build the full token set. Same inputs -> byte-identical output."""
    st = canonical_site_type(site_type)
    prof = PROFILES[st]
    moods = [m.strip().lower() for m in (moods or []) if m.strip()]
    seed = f"{brand_name.strip().lower()}|{st}"
    primary_rgb = C.parse_hex(primary) if primary else None
    if primary and primary_rgb is None:
        raise ValueError(f"primary color must be #rgb or #rrggbb, got {primary!r}")
    if primary_rgb:
        _, pc, hue = C.srgb_to_oklch(primary_rgb)
        chroma = max(0.02, min(pc, 0.25))
    else:
        hue, mult = pick_hue(st, moods, seed)
        chroma = prof.chroma * mult
    brand = _ramp(hue, chroma)
    neutral = _ramp(hue, 0.012, _NEUTRAL_L, (1,) * len(STEPS))  # neutrals tinted toward the brand hue
    red, green, amber = _ramp(27.0, 0.2), _ramp(150.0, 0.15), _ramp(75.0, 0.16)
    charts = [brand] + [_ramp((hue + off) % 360, 0.14) for off in (72, 144, 216, 288)]
    light = _semantic(brand, neutral, red, green, amber, charts, False, primary_rgb)
    dark = _semantic(brand, neutral, red, green, amber, charts, True, None)
    log: list[str] = []
    _enforce(light, "light", log)
    _enforce(dark, "dark", log)
    sm, md, lg = prof.radius
    return DesignTokens(
        site_type=st, brand_name=brand_name or st, fonts=pick_fonts(st, moods, seed),
        ramps={"brand": brand, "neutral": neutral}, light=light, dark=dark,
        type_scale=_type_scale(prof.type_ratio, prof.base_px, prof.fluid_display),
        spacing={str(px // 4): f"{px / 16:g}rem" for px in SPACING_PX},  # keys follow Tailwind units (1 = 4px)
        radius={"sm": f"{sm}px", "md": f"{md}px", "lg": f"{lg}px", "full": "9999px"},
        shadows=_shadows(hue),
        motion={"fast": "100ms", "base": "150ms", "slow": "200ms", "slower": "300ms",
                "ease": "cubic-bezier(0.2, 0, 0, 1)"},
        adjustments=log,
    )
