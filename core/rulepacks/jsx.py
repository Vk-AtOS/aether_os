"""Tiny JSX tag scanner: enough to read one element's attributes and children without a TS parser.

It understands quotes and {} nesting inside a start tag, which is what breaks naive `<img[^>]*>` regexes
(`onClick={() => a > b}`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from aether_os.core.rulepacks.base import line_of


@dataclass(frozen=True)
class Tag:
    name: str
    attrs: str
    start: int
    end: int          # index just past the closing '>' of the start tag
    self_closing: bool
    line: int

    def has(self, *attr: str) -> bool:
        return any(re.search(rf"(?<![\w-]){re.escape(a)}\s*=", self.attrs) for a in attr)

    def value(self, attr: str) -> str | None:
        m = re.search(rf"(?<![\w-]){re.escape(attr)}\s*=\s*(\"[^\"]*\"|'[^']*'|\{{[^}}]*\}})", self.attrs)
        return m.group(1)[1:-1] if m else None


def _scan_to_gt(text: str, i: int) -> int:
    """Index of the '>' that closes the start tag beginning before i, or -1."""
    depth, quote = 0, ""
    n = len(text)
    while i < n:
        c = text[i]
        if quote:
            if c == quote:
                quote = ""
        elif c in "\"'`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif c == ">" and depth == 0:
            return i
        i += 1
    return -1


def iter_tags(text: str, names: tuple[str, ...]) -> list[Tag]:
    rx = re.compile(r"<(" + "|".join(re.escape(n) for n in names) + r")(?=[\s/>])")
    out = []
    for m in rx.finditer(text):
        gt = _scan_to_gt(text, m.end())
        if gt < 0:
            continue
        attrs = text[m.end():gt]
        out.append(Tag(m.group(1), attrs.rstrip("/").strip(), m.start(), gt + 1, attrs.rstrip().endswith("/"),
                       line_of(text, m.start())))
    return out


def children(text: str, tag: Tag) -> str:
    if tag.self_closing:
        return ""
    close = text.find(f"</{tag.name}>", tag.end)
    return text[tag.end:close] if close >= 0 else ""


_INNER_TAG = re.compile(r"<[^<>]*?>")


def has_text(inner: str) -> bool:
    """True when element children may render a text label: literal text, an {expression}, or sr-only text."""
    if "{" in _INNER_TAG.sub("", inner):
        return True  # an expression may be a label; low false positives matter more than coverage
    return bool(_INNER_TAG.sub("", inner).strip())


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def strip_block_comments(text: str) -> str:
    """Blank out /* */ comments, keeping newlines so line numbers stay right."""
    return re.sub(r"/\*.*?\*/", _blank, text, flags=re.S)


def strip_comments(text: str) -> str:
    """Blank out /* */ and // comments (keeping newlines). `://` in URLs is not a comment."""
    return re.sub(r"(?<![:\"'`\\])//[^\n]*", _blank, strip_block_comments(text))
