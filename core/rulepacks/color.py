"""Color math for the token generator: sRGB <-> OKLCH, WCAG 2.x relative luminance and contrast ratio.

OKLab conversion uses the published OKLab matrices (B. Ottosson, 2020). WCAG math follows the WCAG 2.x
definition of relative luminance and contrast ratio: (L1 + 0.05) / (L2 + 0.05).
"""
from __future__ import annotations

import math
import re

RGB = tuple[float, float, float]  # sRGB channels in 0..1
OKLCH = tuple[float, float, float]  # L 0..1, C >= 0, H degrees

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_hex(value: str) -> RGB | None:
    m = _HEX.match(value.strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def to_hex(rgb: RGB) -> str:
    return "#" + "".join(f"{round(min(1.0, max(0.0, c)) * 255):02x}" for c in rgb)


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def relative_luminance(rgb: RGB) -> float:
    """WCAG relative luminance of an sRGB color (channels 0..1)."""
    r, g, b = (_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB | str, b: RGB | str) -> float:
    """WCAG contrast ratio, 1.0 .. 21.0. Accepts RGB tuples or hex strings."""
    ra = parse_hex(a) if isinstance(a, str) else a
    rb = parse_hex(b) if isinstance(b, str) else b
    if ra is None or rb is None:
        raise ValueError(f"not a color: {a!r} / {b!r}")
    la, lb = relative_luminance(ra), relative_luminance(rb)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def srgb_to_oklch(rgb: RGB) -> OKLCH:
    r, g, b = (_to_linear(c) for c in rgb)
    lms = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
           0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
           0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    l_, m_, s_ = (_cbrt(v) for v in lms)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    A = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    C = math.hypot(A, B)
    H = math.degrees(math.atan2(B, A)) % 360 if C > 1e-6 else 0.0
    return (L, C, H)


def _oklch_to_linear(lch: OKLCH) -> RGB:
    L, C, H = lch
    A, B = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
    l_ = L + 0.3963377774 * A + 0.2158037573 * B
    m_ = L - 0.1055613458 * A - 0.0638541728 * B
    s_ = L - 0.0894841775 * A - 1.2914855480 * B
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def _in_gamut(lin: RGB) -> bool:
    return all(-1e-7 <= c <= 1 + 1e-7 for c in lin)


def oklch_to_srgb(lch: OKLCH) -> RGB:
    """Convert to sRGB, reducing chroma (hue and lightness kept) until the color fits the sRGB gamut."""
    L = min(1.0, max(0.0, lch[0]))
    lo, hi = 0.0, max(0.0, lch[1])
    if _in_gamut(_oklch_to_linear((L, hi, lch[2]))):
        lo = hi
    else:
        for _ in range(30):  # bisection on chroma; 30 steps is far below 1/255 precision
            mid = (lo + hi) / 2
            if _in_gamut(_oklch_to_linear((L, mid, lch[2]))):
                lo = mid
            else:
                hi = mid
    lin = _oklch_to_linear((L, lo, lch[2]))
    return tuple(_from_linear(min(1.0, max(0.0, c))) for c in lin)  # type: ignore[return-value]


def oklch_css(rgb: RGB) -> str:
    L, C, H = srgb_to_oklch(rgb)
    return f"oklch({L:.4f} {C:.4f} {H:.2f})" if C >= 0.0005 else f"oklch({L:.4f} 0 0)"


_OKLCH_CSS = re.compile(r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)")


def parse_oklch_css(value: str) -> RGB | None:
    m = _OKLCH_CSS.search(value)
    return oklch_to_srgb((float(m.group(1)), float(m.group(2)), float(m.group(3)))) if m else None


BLACK: RGB = (0.0, 0.0, 0.0)
WHITE: RGB = (1.0, 1.0, 1.0)


def fit_contrast(fg: RGB, bg: RGB, minimum: float, margin: float = 0.08) -> RGB:
    """Return fg, moved in OKLCH lightness away from bg until contrast >= minimum + margin.

    The hue is kept; chroma shrinks only where the gamut forces it. When no lightness of this hue reaches the
    target, the better of black and white is returned (one of the two always clears 4.58:1 against any color).
    The margin absorbs rounding when the color is later printed as a CSS oklch() value.
    """
    target = minimum + margin
    if contrast_ratio(fg, bg) >= target:
        return fg
    L0, C, H = srgb_to_oklch(fg)
    # Walk lighter and darker in parallel; the first lightness that passes is the smallest visible change.
    for i in range(1, 101):
        for L in (L0 - i * 0.01, L0 + i * 0.01):
            if 0.0 <= L <= 1.0:
                cand = oklch_to_srgb((L, C, H))
                if contrast_ratio(cand, bg) >= target:
                    return cand
    return max((BLACK, WHITE), key=lambda c: contrast_ratio(c, bg))
