"""Curated tables behind the design token generator: site types, mood words, font pairs.

All rows were chosen for AetherOS (see NOTICE.md for the public ideas that informed the structure).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

SITE_TYPES = ("landing", "saas_dashboard", "ecommerce", "booking", "content", "portfolio", "internal_tool",
              "agent_chat")

# Free-text names the planner or the user may give, mapped to a canonical site type.
SITE_ALIASES = {
    "landing": "landing", "marketing": "landing", "landing_page": "landing", "homepage": "landing",
    "saas": "saas_dashboard", "dashboard": "saas_dashboard", "saas_dashboard": "saas_dashboard",
    "saas_app": "saas_dashboard", "admin": "saas_dashboard", "web_app": "saas_dashboard",
    "ecommerce": "ecommerce", "e-commerce": "ecommerce", "shop": "ecommerce", "store": "ecommerce",
    "booking": "booking", "service": "booking", "service_business": "booking", "appointments": "booking",
    "content": "content", "blog": "content", "docs": "content", "news": "content", "magazine": "content",
    "portfolio": "portfolio", "personal": "portfolio", "agency": "portfolio",
    "internal_tool": "internal_tool", "internal": "internal_tool", "backoffice": "internal_tool",
    "crud": "internal_tool", "agent_chat": "agent_chat", "agent": "agent_chat", "chat": "agent_chat",
    "chatbot": "agent_chat", "assistant": "agent_chat",
}


@dataclass(frozen=True)
class SiteProfile:
    type_ratio: float        # modular scale ratio for the type ladder
    base_px: int             # body text size
    radius: tuple[int, int, int]  # sm / md / lg in px
    default_hue: float       # OKLCH hue when no brand color or mood decides it
    chroma: float            # brand chroma before mood adjustment
    motion: str              # motion budget, rendered into the prompt pack
    fluid_display: bool      # large steps use clamp() so heroes scale with the viewport


PROFILES = {
    "landing": SiteProfile(1.333, 16, (6, 10, 16), 235.0, 0.16, "at most 2 animated elements per view", True),
    "saas_dashboard": SiteProfile(1.2, 14, (4, 8, 12), 250.0, 0.14, "no decorative motion; 150ms state changes", False),
    "ecommerce": SiteProfile(1.25, 16, (4, 8, 14), 35.0, 0.15, "hover feedback only; no scroll reveals", False),
    "booking": SiteProfile(1.25, 16, (8, 12, 20), 175.0, 0.11, "subtle 200ms transitions only", False),
    "content": SiteProfile(1.25, 18, (2, 4, 8), 25.0, 0.10, "none beyond link and focus transitions", False),
    "portfolio": SiteProfile(1.333, 16, (0, 4, 8), 15.0, 0.13, "one signature transition, used consistently", True),
    "internal_tool": SiteProfile(1.2, 14, (4, 6, 8), 245.0, 0.10, "none; instant feedback", False),
    "agent_chat": SiteProfile(1.2, 15, (8, 14, 20), 200.0, 0.12, "typing indicator and message fade only", False),
}

# mood word -> (hue or None to keep the site default, chroma multiplier)
MOODS = {
    "calm": (210.0, 0.8), "trust": (250.0, 0.9), "trustworthy": (250.0, 0.9), "professional": (245.0, 0.8),
    "serious": (240.0, 0.7), "warm": (45.0, 1.0), "friendly": (55.0, 1.0), "cozy": (40.0, 0.9),
    "energetic": (30.0, 1.25), "bold": (20.0, 1.25), "playful": (340.0, 1.15), "fun": (330.0, 1.15),
    "nature": (145.0, 0.9), "organic": (130.0, 0.85), "eco": (150.0, 0.9), "fresh": (165.0, 1.0),
    "health": (170.0, 0.85), "medical": (215.0, 0.8), "luxury": (70.0, 0.6), "elegant": (60.0, 0.55),
    "premium": (75.0, 0.6), "minimal": (None, 0.45), "clean": (None, 0.6), "tech": (260.0, 1.0),
    "futuristic": (200.0, 1.2), "creative": (350.0, 1.1), "editorial": (25.0, 0.7), "finance": (155.0, 0.8),
    "food": (35.0, 1.1), "sport": (25.0, 1.2), "kids": (90.0, 1.2), "legal": (255.0, 0.6),
}


@dataclass(frozen=True)
class FontPair:
    heading: str
    body: str
    mono: str
    moods: frozenset[str]
    site_types: frozenset[str]
    heading_weights: tuple[int, ...] = (600, 700)
    body_weights: tuple[int, ...] = (400, 500)


def _fp(heading, body, mono, moods, types, hw=(600, 700), bw=(400, 500)) -> FontPair:
    return FontPair(heading, body, mono, frozenset(moods.split()), frozenset(types.split()), hw, bw)


# Google Fonts families. Pairs mix categories (serif+sans, display+sans) or use one well-built family.
# Inter appears only for internal tools, where neutrality is the goal.
FONT_PAIRS = (
    _fp("Fraunces", "Manrope", "JetBrains Mono", "warm friendly organic editorial cozy food", "landing content booking"),
    _fp("Playfair Display", "Source Sans 3", "Source Code Pro", "elegant luxury premium classic", "ecommerce portfolio booking"),
    _fp("Space Grotesk", "IBM Plex Sans", "IBM Plex Mono", "tech bold futuristic modern", "landing saas_dashboard agent_chat"),
    _fp("DM Serif Display", "DM Sans", "DM Mono", "elegant friendly warm trust", "landing booking ecommerce", hw=(400,)),
    _fp("Sora", "Nunito Sans", "JetBrains Mono", "friendly playful modern fresh", "landing agent_chat ecommerce"),
    _fp("Bricolage Grotesque", "Figtree", "JetBrains Mono", "bold playful creative fun", "landing portfolio ecommerce"),
    _fp("Instrument Serif", "Instrument Sans", "JetBrains Mono", "editorial minimal elegant creative", "portfolio content landing", hw=(400,)),
    _fp("Newsreader", "Public Sans", "IBM Plex Mono", "editorial serious trust legal", "content booking"),
    _fp("Lora", "Work Sans", "Fira Code", "calm warm health cozy", "content booking"),
    _fp("Outfit", "Karla", "Fira Code", "clean modern fresh minimal", "ecommerce saas_dashboard landing"),
    _fp("Plus Jakarta Sans", "Plus Jakarta Sans", "JetBrains Mono", "professional clean trust finance", "saas_dashboard landing agent_chat"),
    _fp("Geist", "Geist", "Geist Mono", "minimal tech clean", "saas_dashboard agent_chat internal_tool"),
    _fp("IBM Plex Sans", "IBM Plex Sans", "IBM Plex Mono", "professional serious tech", "internal_tool saas_dashboard"),
    _fp("Inter", "Inter", "JetBrains Mono", "minimal clean professional", "internal_tool"),
    _fp("Syne", "Manrope", "Space Mono", "creative bold futuristic", "portfolio landing", hw=(700, 800)),
    _fp("Cormorant Garamond", "Montserrat", "Source Code Pro", "luxury elegant premium", "ecommerce booking portfolio"),
    _fp("Libre Baskerville", "Nunito Sans", "Source Code Pro", "trust legal medical serious classic", "booking content", hw=(400, 700)),
    _fp("Lexend", "Lexend", "JetBrains Mono", "calm health kids friendly", "booking internal_tool agent_chat"),
    _fp("Red Hat Display", "Red Hat Text", "Red Hat Mono", "professional trust finance modern", "saas_dashboard landing booking"),
    _fp("Unbounded", "Onest", "JetBrains Mono", "futuristic bold energetic sport", "landing agent_chat"),
    _fp("Spectral", "Karla", "Fira Code", "editorial calm classic", "content portfolio"),
    _fp("Rubik", "Rubik", "Fira Code", "playful fun kids food sport", "ecommerce landing"),
    _fp("Archivo", "Archivo", "JetBrains Mono", "bold serious sport energetic", "ecommerce saas_dashboard", hw=(700, 800)),
    _fp("Manrope", "Manrope", "JetBrains Mono", "clean calm modern", "saas_dashboard agent_chat booking"),
)


def stable_int(*parts: str) -> int:
    """Deterministic across processes (unlike hash()), so the same brief always yields the same tokens."""
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)


def canonical_site_type(site_type: str) -> str:
    key = site_type.strip().lower().replace(" ", "_").replace("/", "_")
    if key in SITE_ALIASES:
        return SITE_ALIASES[key]
    for alias, canon in SITE_ALIASES.items():
        if alias in key:
            return canon
    raise ValueError(f"unknown site type {site_type!r}; expected one of {', '.join(SITE_TYPES)}")


def pick_fonts(site_type: str, moods: list[str], seed: str) -> FontPair:
    """Best mood match among the pairs made for this site type; ties broken by the seed, not by table order."""
    candidates = [p for p in FONT_PAIRS if site_type in p.site_types]
    best = max(len(p.moods & set(moods)) for p in candidates)
    top = [p for p in candidates if len(p.moods & set(moods)) == best]
    return top[stable_int(seed, site_type, "fonts") % len(top)]


def pick_hue(site_type: str, moods: list[str], seed: str) -> tuple[float, float]:
    """(hue, chroma multiplier) from the first mood word that decides one, else a seeded offset of the default."""
    mult = 1.0
    for m in moods:
        if m in MOODS:
            hue, mult = MOODS[m]
            if hue is not None:
                return hue, mult
            break
    base = PROFILES[site_type].default_hue
    # Spread brands of the same site type over +-40 degrees, but keep out of the 270-320 violet band:
    # violet-to-pink is the default look of generated sites and reads as template output.
    hue = (base + (stable_int(seed, "hue") % 81) - 40) % 360
    if 270 <= hue <= 320:
        hue = (hue + 60) % 360
    return hue, mult
