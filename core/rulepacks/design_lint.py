"""Deterministic design linter for generated React (.tsx/.jsx) and CSS. Rule ids DES-001..DES-016.

Regex + a small JSX tag scanner; no browser, no npm. Each rule prefers missing a case to flagging correct code,
because every finding goes back to the model as an instruction.
"""
from __future__ import annotations

import re

from aether_os.core.rulepacks.base import Finding, Project, line_of, make
from aether_os.core.rulepacks.jsx import children, has_text, iter_tags, strip_block_comments, strip_comments

PACK = "design"
MAX_FONT_FAMILIES = 2  # plus one monospace family

_HEX = re.compile(r"(?<=[\"'`\[(\s:,=])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])")
_NAV_PREFIX = re.compile(r"(href|to|navigate\(|hash|scrollTo|querySelector\(|getElementById\()\s*=?\s*\{?\s*[\"'`(]*$")
_PALETTE = re.compile(r"(?<![\w-])(?:[a-z]+:)*(?:bg|text|border|ring|from|via|to|fill|stroke|outline|divide|"
                      r"placeholder|decoration|accent|caret)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|"
                      r"yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-"
                      r"(?:50|[1-9]00|950)(?:/\d+)?(?![\w-])")
_SPACING = re.compile(r"(?<![\w-])-?(?:p|px|py|pt|pr|pb|pl|ps|pe|m|mx|my|mt|mr|mb|ml|ms|me|gap|gap-x|gap-y|"
                      r"space-x|space-y|inset|inset-x|inset-y|top|right|bottom|left)-\[(\d+(?:\.\d+)?)px\]")
_MONO = re.compile(r"mono|code|courier|consolas|menlo", re.I)
_GENERIC_FONTS = {"sans-serif", "serif", "monospace", "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace",
                  "inherit", "initial", "cursive", "-apple-system", "blinkmacsystemfont", "emoji"}
_PAGE_PATH = re.compile(r"(^|/)(pages|routes|views|screens|app)/|(Page|View|Screen)\.(t|j)sx$")
_FETCH = re.compile(r"\buse(?:Suspense)?(?:Infinite)?Query\(|\buseSWR\(|\bfetch\(|\baxios\.|\bapi\.(?:get|post)\(")
_LOADING = re.compile(r"isLoading|isPending|isFetching|\bloading\b|Skeleton|Spinner|Loader")
_ERROR = re.compile(r"isError|\berror\b|Error\b|\bfailed\b", re.I)
_EMPTY = re.compile(r"\.length\s*(?:===?|!==?|<=?|>=?)\s*0|!\s*[\w.?\[\]]+\.length|\.length\s*\?|\.length\s*&&|"
                    r"EmptyState|isEmpty|\bNo \w+(?: \w+)? (?:yet|found)|nothing (?:here|yet)", re.I)
_LOREM = re.compile(r"lorem ipsum|dolor sit amet", re.I)
_STOCK_NAMES = re.compile(r"\b(?:John Doe|Jane Doe|Acme(?: Corp| Inc)?|Feature (?:One|Two|Three|[123])|"
                          r"Your Company(?: Name)?|Company Name|Product Name|Your Logo)\b")
_EXAMPLE_LINK = re.compile(r"(?:href|src)=[\"'{`]+https?://(?:www\.)?example\.com")
_SLOP_COPY = re.compile(r"\b(?:revolutioni[sz]e|seamless(?:ly)?|unlock the (?:full )?power|elevate your|"
                        r"all-in-one (?:platform|solution)|supercharge|game[- ]chang\w*|cutting[- ]edge|"
                        r"next[- ]level|unleash)\b", re.I)
_ANIM = re.compile(r"(?<![\w-])animate-(?!spin\b|pulse\b|none\b)[a-z][\w-]*|<motion\.\w+")
_REDUCED = re.compile(r"prefers-reduced-motion|motion-reduce:|motion-safe:|useReducedMotion")


def _is_token_file(rel: str, text: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (name.startswith("tailwind.config") or "token" in name.lower() or "theme" in name.lower()
            or bool(re.search(r"--(?:background|primary|foreground)\s*:", text)))


def _is_primitive(rel: str) -> bool:
    """shadcn-style primitives (components/ui/*) forward props; their callers carry the label."""
    return "/components/ui/" in f"/{rel}" or "/ui/primitives/" in f"/{rel}"


def _lint_colors(p: Project, rel: str, text: str, out: list[Finding]) -> None:
    if _is_token_file(rel, text):
        return
    for m in _HEX.finditer(text):
        prefix = text[max(0, m.start() - 24):m.start()]
        if _NAV_PREFIX.search(prefix):
            continue
        ln = line_of(text, m.start())
        out.append(make(PACK, p, "DES-001", "medium", rel, ln, f"hard-coded color {m.group(0)} outside the token file",
                        "use a semantic token class (bg-primary, text-muted-foreground, border-border) or var(--token)"))
    if rel.endswith((".tsx", ".jsx")):
        hits = list(_PALETTE.finditer(text))
        if hits:
            names = sorted({h.group(0).split(":")[-1] for h in hits})
            out.append(make(PACK, p, "DES-002", "low", rel, line_of(text, hits[0].start()),
                            f"{len(hits)} raw Tailwind palette class(es) instead of semantic tokens: "
                            f"{', '.join(names[:6])}{' ...' if len(names) > 6 else ''}",
                            "map each to a token: bg-background, bg-card, text-foreground, text-muted-foreground, "
                            "bg-primary, bg-destructive, border-border"))


def _font_families(p: Project) -> list[tuple[str, str, int]]:
    """(family, file, line) for every non-mono, non-generic family the project declares."""
    found = []
    for rel in p.files:
        if not rel.endswith((".css", ".scss", ".html", ".tsx", ".jsx", ".js", ".ts", ".cjs", ".mjs")):
            continue
        text = p.text(rel)
        pats = [r"font-family\s*:\s*([^;}\n]+)", r"family=([A-Za-z0-9+]+)", r"font-\[['\"]?([A-Za-z0-9 _]+)",
                r"fontFamily\s*:\s*['\"]([^'\"]+)['\"]"]
        for pat in pats:
            for m in re.finditer(pat, text):
                first = m.group(1).split(",")[0].strip().strip("'\"").replace("+", " ").replace("_", " ").strip()
                if first and not first.startswith("var(") and first.lower() not in _GENERIC_FONTS and not _MONO.search(first):
                    found.append((first, rel, line_of(text, m.start())))
        for m in re.finditer(r"fontFamily\s*:\s*\{([^}]*)\}", text, re.S):  # tailwind.config theme block
            for fm in re.finditer(r"\[\s*['\"]([^'\"]+)['\"]", m.group(1)):
                name = fm.group(1).strip()
                if not name.startswith("var(") and name.lower() not in _GENERIC_FONTS and not _MONO.search(name):
                    found.append((name, rel, line_of(text, m.start() + fm.start())))
    return found


def _lint_fonts(p: Project, out: list[Finding]) -> None:
    seen: dict[str, tuple[str, int]] = {}
    for fam, rel, ln in _font_families(p):
        seen.setdefault(fam.lower(), (rel, ln))
    if len(seen) > MAX_FONT_FAMILIES:
        third = sorted(seen.items(), key=lambda kv: kv[1])[MAX_FONT_FAMILIES]
        out.append(make(PACK, p, "DES-003", "medium", third[1][0], third[1][1],
                        f"{len(seen)} font families declared ({', '.join(sorted(seen))}); the limit is "
                        f"{MAX_FONT_FAMILIES} plus one monospace", "keep the heading and body families from the tokens; remove the rest"))


def _lint_tsx(p: Project, rel: str, raw: str, out: list[Finding]) -> None:
    text = strip_comments(raw)
    for m in _SPACING.finditer(text):
        v = float(m.group(1))
        if v > 2 and v % 4:
            out.append(make(PACK, p, "DES-004", "low", rel, line_of(text, m.start()),
                            f"arbitrary spacing {m.group(0)} is off the 4px grid",
                            f"use the nearest scale step (e.g. {round(v / 4)} = {round(v / 4) * 4}px)"))
    primitive = _is_primitive(rel)
    for t in iter_tags(text, ("img",)):
        if not t.has("alt") and "{..." not in t.attrs:
            out.append(make(PACK, p, "DES-005", "medium", rel, t.line, "<img> without alt",
                            "add alt describing the image, or alt=\"\" when it is decorative"))
    if not primitive:
        for t in iter_tags(text, ("button", "Button", "IconButton")):
            if t.has("aria-label", "aria-labelledby", "title", "label", "children") or "{..." in t.attrs:
                continue
            if not t.self_closing and has_text(children(text, t)):
                continue
            out.append(make(PACK, p, "DES-006", "medium", rel, t.line, f"<{t.name}> has no accessible name (icon only)",
                            "add aria-label=\"<what it does>\" or visible / sr-only text inside the button"))
        for t in iter_tags(text, ("input", "Input", "textarea", "Textarea", "select")):
            typ = (t.value("type") or "").lower()
            if typ in ("hidden", "submit", "button", "reset", "image") or "{..." in t.attrs:
                continue
            if t.has("aria-label", "aria-labelledby"):
                continue
            ident = t.value("id")
            if ident is not None and (f'htmlFor="{ident}"' in text or f"htmlFor='{ident}'" in text
                                      or (t.attrs.find("id={") >= 0 and "htmlFor={" in text)):
                continue
            before = text[:t.start]
            if (len(re.findall(r"<(?:label|Label|FormLabel)\b", before)) > len(re.findall(r"</(?:label|Label|FormLabel)>", before))
                    or len(re.findall(r"<FormControl\b", before)) > len(re.findall(r"</FormControl>", before))):
                continue
            out.append(make(PACK, p, "DES-007", "medium", rel, t.line, f"<{t.name}> has no label",
                            "add <label htmlFor=\"id\"> with a matching id, or aria-label; a placeholder is not a label"))
    for t in iter_tags(text, ("div", "span", "li", "p", "section", "article", "td", "tr", "img")):
        if not t.has("onClick") or t.has("aria-hidden") or 'role="presentation"' in t.attrs:
            continue
        if "stopPropagation" in (t.value("onClick") or ""):
            continue
        if t.has("role") and t.has("onKeyDown", "onKeyUp", "onKeyPress"):
            continue
        out.append(make(PACK, p, "DES-008", "medium", rel, t.line, f"onClick on <{t.name}> without role and keyboard handler",
                        "use a <button> (or <a> for navigation); otherwise add role, tabIndex={0} and onKeyDown"))
    _lint_states(p, rel, text, out)
    for i, line in enumerate(text.splitlines(), 1):
        if "bg-clip-text" in line and "text-transparent" in line and re.search(r"bg-gradient|from-", line):
            out.append(make(PACK, p, "DES-010", "low", rel, i, "gradient text", "use solid text-foreground; keep color for one accent"))
        if (re.search(r"(?<![\w-])from-(?:purple|violet|indigo|fuchsia)-\d+", line)
                and re.search(r"(?<![\w-])(?:via|to)-(?:pink|fuchsia|purple|violet|rose)-\d+", line)):
            out.append(make(PACK, p, "DES-011", "medium", rel, i, "violet-to-pink gradient (generic generated look)",
                            "use a solid bg-primary or a subtle bg-accent surface from the tokens"))
        if line.lstrip().startswith("import "):
            continue
        if _LOREM.search(line):
            out.append(make(PACK, p, "DES-012", "medium", rel, i, "lorem ipsum placeholder text", "write the real copy for this business"))
        elif "placeholder=" not in line and (_STOCK_NAMES.search(line) or _EXAMPLE_LINK.search(line)):
            hit = (_STOCK_NAMES.search(line) or _EXAMPLE_LINK.search(line)).group(0)
            out.append(make(PACK, p, "DES-012", "low", rel, i, f"placeholder content '{hit}'", "replace with real names, links and copy"))
        m = _SLOP_COPY.search(line)
        if m:
            out.append(make(PACK, p, "DES-013", "low", rel, i, f"stock marketing phrase '{m.group(0)}'",
                            "say concretely what the product does for this customer"))
        if re.search(r"(?<![\w:-])outline-none", line) and not re.search(r"focus(?:-visible)?:(?:ring|outline|border|shadow)", line):
            out.append(make(PACK, p, "DES-014", "low", rel, i, "outline-none without a focus style",
                            "add focus-visible:ring-2 focus-visible:ring-ring"))
    anims = list(_ANIM.finditer(text))
    if len(anims) > 3:
        out.append(make(PACK, p, "DES-015", "low", rel, line_of(text, anims[3].start()),
                        f"{len(anims)} animated elements in one file (budget: 3)", "keep motion for one or two meaningful moments"))


def _lint_states(p: Project, rel: str, text: str, out: list[Finding]) -> None:
    if not _PAGE_PATH.search(rel):
        return
    fm = _FETCH.search(text)
    if not fm:
        return
    missing = []
    if not _LOADING.search(text):
        missing.append("loading")
    if not _ERROR.search(text):
        missing.append("error")
    aliases = {"data", "items", "rows", "results", "records"} | set(re.findall(r"\bdata\s*:\s*(\w+)", text))
    maps_data = re.search(r"\b(?:" + "|".join(sorted(aliases)) + r")\b[\w?.\[\]]*\.map\(", text)
    if maps_data and not _EMPTY.search(text):
        missing.append("empty")
    if missing:
        out.append(make(PACK, p, "DES-009", "medium", rel, line_of(text, fm.start()),
                        f"data view without {', '.join(missing)} state(s)",
                        "render loading (skeleton), empty (message + next action) and error (message + retry) states"))


def _lint_html(p: Project, rel: str, text: str, out: list[Finding]) -> None:
    m = re.search(r"<html\b[^>]*>", text, re.I)
    if m and "lang=" not in m.group(0):
        out.append(make(PACK, p, "DES-016", "medium", rel, line_of(text, m.start()), "<html> without lang", 'add lang="en" (or the site language)'))
    vp = re.search(r"<meta[^>]+name=[\"']viewport[\"'][^>]*>", text, re.I)
    if m and not vp:
        out.append(make(PACK, p, "DES-016", "medium", rel, 1, "no viewport meta tag",
                        '<meta name="viewport" content="width=device-width, initial-scale=1" />'))
    elif vp and re.search(r"user-scalable\s*=\s*(?:no|0)|maximum-scale\s*=\s*1(?:\.0)?\b", vp.group(0)):
        out.append(make(PACK, p, "DES-016", "medium", rel, line_of(text, vp.start()), "viewport blocks zoom",
                        "remove user-scalable=no / maximum-scale=1"))


def lint_design(p: Project) -> list[Finding]:
    out: list[Finding] = []
    for rel in p.by_suffix(".tsx", ".jsx", ".css", ".scss"):
        text = p.text(rel)
        css = rel.endswith((".css", ".scss"))
        _lint_colors(p, rel, strip_block_comments(text) if css else strip_comments(text), out)
        if rel.endswith((".tsx", ".jsx")):
            _lint_tsx(p, rel, text, out)
    for rel in p.by_suffix(".html"):
        _lint_html(p, rel, p.text(rel), out)
    _lint_fonts(p, out)
    web = p.by_suffix(".tsx", ".jsx", ".css", ".scss")
    animated = next((r for r in web if _ANIM.search(p.text(r)) or "@keyframes" in p.text(r) or "framer-motion" in p.text(r)), None)
    if animated and not any(_REDUCED.search(p.text(r)) for r in web):
        out.append(make(PACK, p, "DES-015", "low", animated, 1, "animation without a prefers-reduced-motion fallback",
                        "add a @media (prefers-reduced-motion: reduce) rule or motion-reduce: variants"))
    return out
