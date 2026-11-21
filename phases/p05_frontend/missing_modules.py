"""P05 Frontend: write the local modules model-written pages import but the generator never produced.

Scans src/**/*.{ts,tsx,js,jsx} for relative / `@/` imports that resolve to no file. `components/ui/<name>` gets a
dependency-free shadcn-style primitive; any other missing module gets a minimal stub exporting the imported names
(with a warning). Existing files are never touched. Runs before npm install/build.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from aether_os.core.errors import SandboxViolation
from aether_os.core.run_app.safe_fs import safe_makedirs, safe_write_text
from aether_os.phases.p05_frontend.ui_primitives import UI_PRIMITIVES, UTIL_MODULES

logger = logging.getLogger(__name__)

_SRC_EXT = (".ts", ".tsx", ".js", ".jsx")
_RESOLVE_EXT = _SRC_EXT + (".json", ".css", ".mjs")
_FROM_RE = re.compile(r"""(?:import|export)\s+(?P<clause>(?:type\s+)?[^'";]*?)\s*from\s*['"](?P<spec>[^'"]+)['"]""", re.S)
_SIDE_RE = re.compile(r"""import\s*['"](?P<spec>[^'"]+)['"]""")
_DYN_RE = re.compile(r"""import\(\s*['"](?P<spec>[^'"]+)['"]\s*\)""")
GENERATED_MARK = "// aether:generated-module"
_EXPORT_NAME_RE = re.compile(r"^export (?:const|function|interface|type) (\w+)", re.M)


def _parse_clause(clause: str) -> tuple[set[str], set[str], bool]:
    """Return (value names, type names, wants_default) from an import/export clause."""
    values: set[str] = set()
    types: set[str] = set()
    default = False
    clause = clause.strip()
    whole_type = clause.startswith("type ")
    if whole_type:
        clause = clause[5:].strip()
    brace = re.search(r"\{(.*)\}", clause, re.S)
    head = clause[:brace.start()] if brace else clause
    if brace:
        for part in brace.group(1).split(","):
            tokens = part.strip().split()
            if not tokens:
                continue
            is_type = whole_type or tokens[0] == "type"
            if tokens[0] == "type" and len(tokens) > 1:
                tokens = tokens[1:]
            name = tokens[0]
            if name == "default":
                default = True
            elif re.fullmatch(r"\w+", name):
                (types if is_type else values).add(name)
    words = head.replace(",", " ").split()
    if words and re.fullmatch(r"\w+", words[0]):
        default = True
    return values, types, default


def _resolve(spec: str, importer: Path, src: Path) -> Path | None:
    """Base path (no extension) a local specifier points to, or None when it is not a local import.
    Specifiers come from model-written code: the result must stay inside src after resolving symlinks and `..`
    (otherwise PermissionError is raised for the caller to log and skip)."""
    if spec.startswith("@/"):
        if ".." in spec[2:].split("/"):
            raise PermissionError("'..' in alias import")
        base = src / spec[2:]
    elif spec.startswith("."):
        base = importer.parent / spec
    else:
        return None
    resolved = base.resolve()
    if resolved != src and not resolved.is_relative_to(src):
        raise PermissionError("import resolves outside src")
    return resolved


def _has(path: Path) -> bool:
    """File exists with this exact spelling: Linux builds are case-sensitive, a macOS dev disk is not, so
    `ui/card` must not count as present just because `ui/Card.tsx` is (that is how this bug hid locally)."""
    try:
        if path.name not in {p.name for p in path.parent.iterdir() if p.is_file()}:
            return False
    except OSError:
        return False
    for parent in path.parents:  # directory casing too: `Components/UI` must not resolve to `components/ui` on macOS
        try:
            if parent.parent != parent and parent.name not in {p.name for p in parent.parent.iterdir()}:
                return False
        except OSError:
            break
    return True


def _exists(base: Path) -> bool:
    if _has(base) or any(_has(Path(str(base) + e)) for e in _RESOLVE_EXT):
        return True
    return any(_has(base / ("index" + e)) for e in _SRC_EXT)


def _ci_entry(directory: Path, name: str, want_dir: bool = False) -> str | None:
    """Entry of `directory` whose name equals `name` ignoring case (exact spelling preferred)."""
    try:
        names = [p.name for p in directory.iterdir() if (p.is_dir() if want_dir else p.is_file())]
    except OSError:
        return None
    if name in names:
        return name
    return next((n for n in sorted(names) if n.lower() == name.lower()), None)


def _case_corrected_spec(spec: str, importer: Path, src: Path) -> str | None:
    """The specifier respelled to the casing of the file it points to on disk, or None when no file matches even
    ignoring case. The generator writes ui/Card.tsx while model pages import ui/card: on Linux that is a missing
    module and creating card.tsx next to Card.tsx makes tsc fail with TS1261 (same file, two casings)."""
    segs = spec.split("/")
    cur = src if spec.startswith("@/") else importer.parent
    out = ["@"] if spec.startswith("@/") else []
    rest = segs[1:] if spec.startswith("@/") else segs
    for i, seg in enumerate(rest):
        if seg in (".", "..", ""):
            cur = (cur / seg).resolve() if seg else cur
            out.append(seg)
            continue
        if i < len(rest) - 1:
            d = _ci_entry(cur, seg, want_dir=True)
            if d is None:
                return None
            cur = cur / d
            out.append(d)
            continue
        for ext in ("",) + _RESOLVE_EXT:
            f = _ci_entry(cur, seg + ext)
            if f is not None:
                out.append(f[: len(f) - len(ext)])
                return "/".join(out)
        d = _ci_entry(cur, seg, want_dir=True)
        if d is not None and any(_ci_entry(cur / d, "index" + e) for e in _SRC_EXT):
            out.append(d)
            return "/".join(out)
        return None
    return None


def _drop_generated_case_duplicates(src: Path) -> list[Path]:
    """Remove stubs/primitives an earlier run generated beside a differently-cased real file (TS1261)."""
    removed: list[Path] = []
    for f in sorted(src.rglob("*")):
        if f.suffix not in _SRC_EXT or not f.is_file() or not f.read_text(errors="replace").startswith(GENERATED_MARK):
            continue
        twin = next((p for p in f.parent.iterdir() if p.is_file() and p.name != f.name and p.name.lower() == f.name.lower()
                     and not p.read_text(errors="replace").startswith(GENERATED_MARK)), None)
        if twin is not None:
            f.unlink()
            removed.append(f)
            logger.warning("p05 missing_modules: removed generated duplicate %s (differs only by case from %s)", f.name, twin.name)
    return removed


def _forward_exports(values: set[str], types: set[str], taken: set[str]) -> str:
    out = []
    for n in sorted(values - taken):
        if n[:1].isupper():
            out.append(f"export const {n} = (props: any) => <div {{...props}} />\n")
        else:
            out.append(f"export const {n}: any = (..._args: any[]): any => undefined\n")
    for n in sorted(types - values - taken):
        out.append(f"export type {n} = any\n")
    return "".join(out)


def _render(base: Path, src: Path, values: set[str], types: set[str], default: bool) -> tuple[Path, str, bool]:
    """(file path, source, is_known_primitive) for a missing module."""
    rel = base.relative_to(src).as_posix()
    ui = re.fullmatch(r"components/ui/([\w-]+)", rel)
    if ui and ui.group(1).lower() in UI_PRIMITIVES:
        text, main = UI_PRIMITIVES[ui.group(1).lower()]
        taken = set(_EXPORT_NAME_RE.findall(text))
        if default:
            text += f"\nexport default {main}\n"
        return Path(str(base) + ".tsx"), text + "\n" + _forward_exports(values, types, taken), True
    if rel in UTIL_MODULES:
        text = UTIL_MODULES[rel]
        taken = set(_EXPORT_NAME_RE.findall(text))
        return Path(str(base) + ".ts"), text + _forward_exports(values, types, taken), True
    text = "import * as React from 'react'\n\n" + _forward_exports(values, types, set())
    if default:
        text += "\nconst Stub = (props: any) => <div {...props} />\nexport default Stub\n"
    return Path(str(base) + ".tsx"), text, False


def ensure_local_modules(frontend_dir: Path) -> list[str]:
    """Create every missing local module the sources import. Returns the written paths relative to frontend_dir."""
    src = (frontend_dir / "src").resolve()
    if not src.is_dir():
        return []
    _drop_generated_case_duplicates(src)
    missing: dict[Path, list] = {}  # target base -> [values, types, default]
    respell: list[tuple[Path, str, str]] = []  # (importer, old specifier, specifier in the on-disk casing)
    for f in sorted(src.rglob("*")):
        if f.suffix not in _SRC_EXT or not f.is_file():
            continue
        try:
            text = f.read_text(errors="replace")
        except Exception as exc:
            logger.warning("p05 missing_modules: read %s failed: %s", f, exc)
            continue
        found: list[tuple[str, set, set, bool]] = []
        for m in _FROM_RE.finditer(text):
            found.append((m.group("spec"), *_parse_clause(m.group("clause"))))
        for m in _SIDE_RE.finditer(text):
            found.append((m.group("spec"), set(), set(), False))
        for m in _DYN_RE.finditer(text):
            found.append((m.group("spec"), set(), set(), True))  # React.lazy needs a default export
        for spec, values, types, default in found:
            try:
                base = _resolve(spec, f, src)
            except PermissionError as exc:
                logger.warning("p05 missing_modules: %s imports %r: %s; skipped", f.name, spec, exc)
                continue
            if base is None or _exists(base):
                continue
            fixed = _case_corrected_spec(spec, f, src)
            if fixed is not None and fixed != spec:
                respell.append((f, spec, fixed))
                continue
            ext = Path(spec).suffix
            if ext and ext not in _SRC_EXT:
                logger.warning("p05 missing_modules: %s imports missing asset %r; not generated", f.name, spec)
                continue
            if ext in _SRC_EXT:
                base = base.with_suffix("")
            entry = missing.setdefault(base, [set(), set(), False])
            entry[0] |= values
            entry[1] |= types
            entry[2] = entry[2] or default
    for f, old, new in respell:
        try:
            text = f.read_text(errors="replace")
            for q in ("'", '"'):
                text = text.replace(f"{q}{old}{q}", f"{q}{new}{q}")
            f.write_text(text)
            logger.info("p05 missing_modules: %s import %r respelled to %r (case differs from the file on disk)", f.name, old, new)
        except OSError as exc:
            logger.warning("p05 missing_modules: could not respell import in %s: %s", f, exc)
    written: list[str] = []
    for base, (values, types, default) in sorted(missing.items()):
        path, text, known = _render(base, src, values, types, default)
        if _has(path):
            continue
        if path.exists():  # case-insensitive disk with a differently-cased file: writing would overwrite it
            logger.warning("p05 missing_modules: %s differs only by case from an existing file; skipped", path)
            continue
        # Containment is re-checked here with the extension added; safe_fs refuses planted symlinks on the way.
        try:
            if not path.resolve().is_relative_to(src):
                raise SandboxViolation(f"{path} is outside src")
            safe_makedirs(src, path.parent)
            safe_write_text(src, path, GENERATED_MARK + "\n" + text)
        except (SandboxViolation, OSError) as exc:
            logger.warning("p05 missing_modules: refused to write %s: %s", path, exc)
            continue
        written.append(path.relative_to(frontend_dir.resolve()).as_posix())
        if known:
            logger.info("p05 missing_modules: wrote UI primitive %s", written[-1])
        else:
            logger.warning("p05 missing_modules: generated stub %s for imported names %s",
                           written[-1], sorted(values | types) or "(default)")
    return written
