"""P05 Frontend: add the named exports model-written pages import from a local module that exists but lacks them.

The generator's own `components/ui/Table.tsx` exports `Table` only, while pages written by the model import the
shadcn family (`TableHeader`, `TableRow`...) from it, so `vite build` fails with `"TableHeader" is not exported by
...`. For each missing name this module renders an APPEND-ONLY patch: the matching ui_primitives implementation
(minimal dependency closure, helpers renamed so nothing clashes with the file) or a forwarding stub. Existing
exports are never renamed or removed. Pure text functions only; file access and containment live in missing_modules.
"""
from __future__ import annotations

import re

from aether_os.phases.p05_frontend.ui_primitives import UI_PRIMITIVES

APPENDED_MARK = "// aether:appended-exports"

_EXPORT_DECL = re.compile(r"^\s*export\s+(?:declare\s+)?(?:default\s+)?(?:async\s+)?(?:abstract\s+)?"
                          r"(?:const|let|var|function\*?|class|interface|type|enum)\s+(\w+)", re.M)
_EXPORT_LIST = re.compile(r"^\s*export\s+(?:type\s+)?\{([^}]*)\}", re.M)
_EXPORT_STAR = re.compile(r"^\s*export\s+\*\s+from\s", re.M)
_EXPORT_STAR_AS = re.compile(r"^\s*export\s+\*\s+as\s+(\w+)\s+from\s", re.M)
_BLOCK_HEAD = re.compile(r"^(?:export\s+)?(?:const|function|interface|type|class)\s+(\w+)")
_REACT_BINDING = re.compile(r"^\s*import\s+(?:type\s+)?(?:\*\s+as\s+React\b|React\b)", re.M)


def parse_exports(text: str) -> tuple[set[str], bool]:
    """(exported names, opaque). opaque = the module has `export * from`, so it may export anything: the caller
    must assume the name could be there and leave the file alone."""
    names = set(_EXPORT_DECL.findall(text)) | set(_EXPORT_STAR_AS.findall(text))
    for body in _EXPORT_LIST.findall(text):
        for part in body.split(","):
            tokens = part.split()
            if tokens and tokens[0] == "type" and len(tokens) > 1:
                tokens = tokens[1:]
            if tokens:
                names.add(tokens[-1])  # `a as b` exports b
    if re.search(r"^\s*export\s+default\b", text, re.M):
        names.add("default")
    return names, bool(_EXPORT_STAR.search(text))


def _blocks(source: str) -> list[tuple[str, str]]:
    """Top-level declaration blocks of a primitive: [(declared name, text)]; imports are dropped and trailing
    statements (`X.displayName = ...`) stay with the block above."""
    out: list[tuple[str, list[str]]] = []
    for line in source.splitlines():
        if line.startswith("import "):
            continue
        m = _BLOCK_HEAD.match(line)
        if m:
            out.append((m.group(1), [line]))
        elif out:
            out[-1][1].append(line)
    return [(n, "\n".join(ls).rstrip() + "\n") for n, ls in out]


def _build_name_map() -> dict[str, str]:
    owner: dict[str, str] = {}
    for key, (src, _main) in UI_PRIMITIVES.items():
        for line in src.splitlines():
            m = re.match(r"^export\s+(?:const|function|interface|type)\s+(\w+)", line)
            if m:
                owner.setdefault(m.group(1), key)
    return owner


_OWNER = _build_name_map()


def known_primitive_names() -> set[str]:
    return set(_OWNER)


def _primitive_patch(key: str, wanted: set[str], file_text: str) -> str:
    """Declarations (renamed helpers, wanted names exported) that implement `wanted` from primitive `key`."""
    blocks = _blocks(UI_PRIMITIVES[key][0])
    by_name = dict(blocks)
    need, todo = set(wanted), list(wanted)
    while todo:  # dependency closure: helpers (cx, Ctx, DivProps...) and sibling components the wanted ones use
        body = by_name[todo.pop()]
        for other in by_name:
            if other not in need and re.search(rf"\b{other}\b", body):
                need.add(other)
                todo.append(other)
    helpers = {n for n in need if n not in wanted}
    suffix = f"__p_{key}"
    out = []
    for name, body in blocks:
        if name not in need:
            continue
        for h in helpers:  # helper names get a per-primitive suffix so they cannot clash with the file's own names
            body = re.sub(rf"\b{h}\b", h + suffix, body)
        if name in helpers:
            if re.search(rf"\b(?:const|function|interface|type|class)\s+{name}{suffix}\b", file_text):
                continue  # an earlier append already declared this helper
            body = re.sub(r"^export\s+", "", body)
        out.append(body)
    return "\n".join(out)


def _locally_declared(name: str, text: str) -> str | None:
    """'type' / 'value' when the file declares `name` without exporting it, else None."""
    m = re.search(rf"^(?:declare\s+)?(const|let|var|function|class|enum|interface|type)\s+{name}\b", text, re.M)
    if not m:
        return None
    return "type" if m.group(1) in ("interface", "type") else "value"


def render_patch(file_text: str, values: set[str], types: set[str], jsx: bool) -> tuple[str, list[str]]:
    """(text to append, names added) so every imported name is exported. Empty when nothing is missing or the module
    may export anything through `export *`."""
    have, opaque = parse_exports(file_text)
    if opaque:
        return "", []
    missing_v, missing_t = sorted(values - have), sorted(types - values - have)
    if not (missing_v or missing_t):
        return "", []
    parts: list[str] = []
    added: list[str] = []
    prim: dict[str, set[str]] = {}
    for n in missing_v + missing_t:
        kind = _locally_declared(n, file_text)
        if kind:  # declared but not exported: exporting it is the whole fix
            parts.append(f"export {'type ' if kind == 'type' else ''}{{ {n} }}\n")
        elif jsx and n in _OWNER and n in values:
            prim.setdefault(_OWNER[n], set()).add(n)
        elif n in types and n not in values:
            parts.append(f"export type {n} = any\n")
        elif n[:1].isupper() and jsx:
            parts.append(f"export const {n} = (props: any) => <div {{...props}} />\n")
        else:
            parts.append(f"export const {n}: any = (..._args: any[]): any => undefined\n")
        added.append(n)
    snippets = [_primitive_patch(k, ws, file_text) for k, ws in sorted(prim.items())]
    need_react = bool(prim) or any("<div" in p for p in parts)
    head = ""
    if need_react and not _REACT_BINDING.search(file_text):
        head = "import * as React from 'react'\n"
    return f"\n{APPENDED_MARK}\n{head}" + "\n".join(snippets + parts), sorted(added)
