"""Shared types for the rule packs: a Finding, severities, and a cached view of a generated project tree.

Every checker in this package is deterministic (regex / Python `ast`), reads files only, and never executes
anything from the scanned project.
"""
from __future__ import annotations

import ast
import logging
import os
import re
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SEVERITIES = ("info", "low", "medium", "high", "critical")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}
BLOCKING = {"high", "critical"}

SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", "env", ".next", "coverage",
             ".pytest_cache", ".mypy_cache", ".ruff_cache", ".turbo", ".cache", "site-packages"}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".scss", ".html", ".json", ".yml",
                 ".yaml", ".toml", ".ini", ".cfg", ".conf", ".txt", ".md", ".sh", ".env", ".example", ".sql",
                 ".pem", ".key", ".tf"}
TEXT_NAMES = {"Dockerfile", "Makefile", "Procfile", ".env", ".gitignore", ".dockerignore", "id_rsa", "id_ed25519",
              "id_ecdsa", "id_dsa"}
MAX_BYTES = 512 * 1024  # generated source files are small; anything larger is a bundle or a data dump


def _inside(p: Path, root: Path) -> bool:
    try:
        return p.resolve().is_relative_to(root)
    except (OSError, RuntimeError) as e:
        logger.warning("rulepacks: cannot resolve %s: %s", p, e)
        return False


# Rules whose matched line can hold a credential value: their snippet is redacted before it is stored, so the
# value never reaches Report.to_json(), logs or a repair prompt sent to a model.
SECRET_RULES = {"SEC-001", "SEC-002", "SEC-003", "SEC-021", "PRD-006"}
_VALUE_START = re.compile(r"""[=:]\s*['"`]?|['"`]""")


def redact(line: str) -> str:
    """Keep the key name and the first 4 characters of the value, then '***'."""
    m = _VALUE_START.search(line)
    head, rest = (line[:m.end()], line[m.end():]) if m else ("", line)
    return f"{head}{rest[:4]}***" if rest else head + "***"


@dataclass(frozen=True)
class Finding:
    rule_id: str
    pack: str
    severity: str
    file: str
    line: int
    message: str
    fix_hint: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return ("tests" in parts[:-1] or "test" in parts[:-1] or "__tests__" in parts[:-1] or name.startswith("test_")
            or name.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".test.js"))
            or name == "conftest.py")


@dataclass
class Project:
    """Read-only, cached view of a project directory. Paths are POSIX strings relative to the root."""

    root: Path
    files: list[str] = field(default_factory=list)
    _text: dict[str, str] = field(default_factory=dict)
    _ast: dict[str, ast.AST | None] = field(default_factory=dict)
    _listed_set: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, root: str | os.PathLike) -> "Project":
        """List text files under root. Symlinks (files and dirs) are skipped and every path must resolve inside
        root: a generated project is untrusted and must not make the scanner read files outside it."""
        root = Path(root).resolve()
        files: list[str] = []
        for dp, dn, fn in os.walk(root):  # followlinks=False: symlinked dirs are listed but never entered
            dn[:] = sorted(d for d in dn if d not in SKIP_DIRS and not d.endswith(".egg-info")
                           and not (Path(dp) / d).is_symlink())
            for f in sorted(fn):
                p = Path(dp) / f
                if p.suffix in TEXT_SUFFIXES or f in TEXT_NAMES or f.startswith((".env", "Dockerfile", "requirements")):
                    try:
                        st = p.lstat()
                        if stat.S_ISREG(st.st_mode) and st.st_size <= MAX_BYTES and _inside(p, root):
                            files.append(p.relative_to(root).as_posix())
                    except OSError as e:
                        logger.warning("rulepacks: cannot stat %s: %s", p, e)
        return cls(root=root, files=files)

    def text(self, rel: str) -> str:
        """File contents, '' for anything not listed by load() or no longer a regular file inside root."""
        if rel not in self._text:
            self._text[rel] = ""
            p = self.root / rel
            try:
                if rel in self._listed() and not p.is_symlink() and _inside(p, self.root):
                    with open(p, "rb") as fh:
                        data = fh.read(MAX_BYTES + 1)  # capped read: the file may have grown since load()
                    if len(data) <= MAX_BYTES:
                        self._text[rel] = data.decode("utf-8", errors="replace")
            except OSError as e:
                logger.warning("rulepacks: cannot read %s: %s", rel, e)
        return self._text[rel]

    def _listed(self) -> set[str]:
        if len(self._listed_set) != len(self.files):
            self._listed_set = set(self.files)
        return self._listed_set

    def tree(self, rel: str) -> ast.AST | None:
        """Parsed module, or None when the file is not valid Python (a syntax error is another gate's job)."""
        if rel not in self._ast:
            try:
                self._ast[rel] = ast.parse(self.text(rel), filename=rel)
            except (SyntaxError, ValueError) as e:
                logger.warning("rulepacks: cannot parse %s: %s", rel, e)
                self._ast[rel] = None
        return self._ast[rel]

    def by_suffix(self, *suffixes: str, include_tests: bool = False) -> list[str]:
        return [f for f in self.files if f.endswith(suffixes) and (include_tests or not is_test_path(f))]

    def python_files(self, include_tests: bool = False) -> list[str]:
        return self.by_suffix(".py", include_tests=include_tests)

    def web_files(self, include_tests: bool = False) -> list[str]:
        return self.by_suffix(".ts", ".tsx", ".js", ".jsx", include_tests=include_tests)

    def named(self, pattern: str) -> list[str]:
        rx = re.compile(pattern)
        return [f for f in self.files if rx.search(f.rsplit("/", 1)[-1])]

    def line(self, rel: str, lineno: int) -> str:
        lines = self.text(rel).splitlines()
        return lines[lineno - 1].strip()[:160] if 0 < lineno <= len(lines) else ""


def make(pack: str, project: Project | None, rule_id: str, severity: str, rel: str, line: int, message: str,
         fix_hint: str) -> Finding:
    snippet = project.line(rel, line) if project is not None and line else ""
    if snippet and rule_id in SECRET_RULES:
        snippet = redact(snippet)
    return Finding(rule_id, pack, severity, rel, line, message, fix_hint, snippet)


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def dotted(node: ast.AST) -> str:
    """`a.b.c` for Name/Attribute chains, '' otherwise."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    if isinstance(node, ast.Call):
        inner = dotted(node.func)
        return f"{inner}()." + ".".join(reversed(parts)) if inner and parts else ""
    return ""


def call_name(node: ast.Call) -> str:
    return dotted(node.func)


def kw(node: ast.Call, name: str) -> ast.AST | None:
    for k in node.keywords:
        if k.arg == name:
            return k.value
    return None


def is_true(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None
