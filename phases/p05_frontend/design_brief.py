"""LLM-first design brief for the generated frontend (KAN-176 / KAN-188).

One model call turns the product description and the IR's entities into a design brief: a palette,
a font pairing, corner radius, density and a description of the dashboard widget. It replaces the
per-domain lookup tables (stat labels, colour hints, widget descriptions) that made every CRM look
like every other CRM. The answer is validated; anything unusable returns None and the caller keeps
the token system of design_system.py. Tests run it against a fake model with fixtures
(tests/fixtures/design_briefs), so only the model key is missing in production.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from aether_os.core.llm.json_enforcer import extract_first_json

logger = logging.getLogger(__name__)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
RADII = {"none", "sm", "md", "lg", "xl", "2xl", "full"}
DENSITIES = {"compact", "comfortable", "spacious"}
COLOUR_KEYS = ("primary_hex", "secondary_hex", "background_hex", "surface_hex")

_PROMPT = """You are the art director for a new web product. Design its look from what it is, not from a template.

Product: {name}
Domain: {domain}
What it must do:
{requirements}
Main records (entities): {entities}

Answer with ONE JSON object and nothing else, with exactly these keys:
- "primary_hex", "secondary_hex", "background_hex", "surface_hex": colours as #RRGGBB. Page background and
  card surface must contrast with each other and with a dark or light text colour; choose a palette that fits
  this product's audience and mood.
- "font_pairing": a short phrase, e.g. "Inter / Source Serif".
- "border_radius": one of {radii}.
- "density": one of {densities}.
- "widget_description": 1-3 sentences describing ONE dashboard widget that is specific to this product and uses
  its own records and vocabulary (static mock data only, no API calls).
"""


def entity_widget_brief(domain: str, entities: List[dict]) -> str:
    """Widget description built from the IR's own entities, used when the model gave none."""
    names = [str(e.get("name") or e.get("table") or "").strip() for e in (entities or [])][:4]
    names = [n for n in names if n]
    if not names:
        return f"a compact overview card for a {domain} application with a headline number and a short activity list"
    return (f"an overview card for a {domain} application that shows a headline count and a short recent-activity "
            f"list for its main records: {', '.join(names)}")


def _parse(text: str) -> Optional[dict]:
    try:
        return extract_first_json(text, expect=dict)
    except ValueError as e:
        logger.warning("p05 design_brief: no JSON object in model reply: %s", e)
        return None


def validate_brief(raw: dict) -> Optional[Dict[str, str]]:
    """The brief with every field checked, or None. Colours must be #RRGGBB: they end up in generated CSS."""
    if not isinstance(raw, dict):
        return None
    brief: Dict[str, str] = {}
    for key in COLOUR_KEYS:
        value = str(raw.get(key) or "").strip()
        if not _HEX.match(value):
            return None
        brief[key] = value.lower()
    radius, density = str(raw.get("border_radius") or "").lower(), str(raw.get("density") or "").lower()
    if radius not in RADII or density not in DENSITIES:
        return None
    widget = re.sub(r"\s+", " ", str(raw.get("widget_description") or "")).strip()
    font = re.sub(r"[^A-Za-z0-9 /,&+.-]", "", str(raw.get("font_pairing") or "")).strip()[:60]
    if not 20 <= len(widget) <= 600 or not font:
        return None
    brief.update(border_radius=radius, density=density, widget_description=widget, font_pairing=font)
    return brief


async def get_design_brief(
    llm: Any, project_name: str, requirements: str, domain: str, entities: List[dict],
) -> Optional[Dict[str, str]]:
    """Ask the model for the brief; None when there is no model, the call fails or the answer is not valid."""
    if os.environ.get("ENVIRONMENT") == "test" or llm is None:        # like the other p05 model calls
        return None
    names = ", ".join(str(e.get("name") or e.get("table") or "") for e in (entities or [])[:12]) or "(none)"
    prompt = _PROMPT.format(name=project_name, domain=domain, requirements=(requirements or "")[:1500] or "(not given)",
                            entities=names, radii=sorted(RADII), densities=sorted(DENSITIES))
    try:
        answer = await llm.call(prompt, task_type="design", max_tokens=700)
    except Exception as exc:
        logger.warning("p05 design brief: model call failed, using the token system: %s", exc)
        return None
    brief = validate_brief(_parse(answer or "") or {})
    if brief is None:
        logger.warning("p05 design brief: answer was not a valid brief, using the token system")
    return brief


def brand_scale(primary_hex: str) -> Dict[int, str]:
    """50..900 shades of the brand colour (tints mix towards white, shades towards black); 600 is the colour itself."""
    r, g, b = (int(primary_hex[i:i + 2], 16) for i in (1, 3, 5))

    def mix(target: int, amount: float) -> str:
        return "#" + "".join(f"{round(c + (target - c) * amount):02x}" for c in (r, g, b))
    tints = {50: 0.92, 100: 0.82, 200: 0.65, 300: 0.45, 400: 0.22, 500: 0.08}
    shades = {700: 0.18, 800: 0.36, 900: 0.52}
    scale = {k: mix(255, v) for k, v in tints.items()}
    scale[600] = primary_hex.lower()
    scale.update({k: mix(0, v) for k, v in shades.items()})
    return dict(sorted(scale.items()))


def apply_brand_to_tailwind(config_js: str, primary_hex: str) -> str:
    """Replace the brand palette of a generated tailwind.config.js by the shades of primary_hex."""
    block = "        brand: {\n" + "".join(f"          {k}: '{v}',\n" for k, v in brand_scale(primary_hex).items()) + "        },"
    new, n = re.subn(r"        brand: \{.*?\n        \},", lambda _m: block, config_js, count=1, flags=re.S)
    return new if n else config_js
