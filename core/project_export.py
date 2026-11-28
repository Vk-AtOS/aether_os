"""The ONE clean export of a run (KAN-268): a deployable project tree built from the run workspace.

The run workspace is the pipeline's scratch space: stage folders (p03_..p13_), three copies of ``src``, preview
state (``preview_credentials.json``, ``run_app.log``, a ``private_key.pem`` the app generated on first start,
``.env`` files with real keys) and the preview's rewrites of the generated code (``_FRONTEND_DIST`` host path in
main.py, ``/app-preview`` base paths in the frontend). None of that belongs in a download, a GitHub repository or a
delivery archive. Every consumer calls ``exported_tree`` / ``build_export_zip`` here instead of walking the workspace:

  * the download endpoint (gateway/routers/run_deploy_router.py),
  * the GitHub push (core/github_push.py via gateway/routers/run_preview_router.py),
  * stage s11 (stages/s11_handoff), which runs it to prove the run is exportable.

The assembled tree is scanned (``scan_tree``) before anything leaves this module; a private key, a ``.env``, a
password-looking value or a preview-only host path fails the export (``ExportError``) instead of shipping.
Findings name the file and the rule, never the secret value.
"""
from __future__ import annotations

import ast
import contextlib
import fnmatch
import hashlib
import io
import json
import logging
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from aether_os.core.project_export_templates import (
    backend_dockerfile, ci_workflow, compose, env_example, env_vars_from_example, frontend_dockerfile,
    frontend_nginx_conf, readme,
)
from aether_os.core.run_app import safe_fs

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 5 * 1024 * 1024
STAGE_DIR = re.compile(r"^[ps]\d\d")           # p03_scaffolding, p04b_..., s11_handoff
# Directories that never ship: dependencies, build output, caches, VCS, the sandbox's own folders.
SKIP_DIRS = {
    "node_modules", "__pycache__", "dist", "build", ".git", ".venv", "venv", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".aetheros", ".sandbox_home", ".sandbox_tmp", "_preview_stub", "_preview_ui", ".ssh", ".aws",
    ".vite", "coverage",
}
# Files that are a secret or machine state, by name. .env.example is NOT here: the export writes its own.
SECRET_FILE_PATTERNS = (
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.crt", "*.cer", "id_rsa*", "id_ed25519*",
    "credentials*.json", "*credentials*.json", "secrets.json", "secrets.yml", "secrets.yaml", "secrets.toml",
    ".npmrc", ".pypirc", ".netrc",
)
STATE_FILE_PATTERNS = ("*.db", "*.db-shm", "*.db-wal", "*.sqlite", "*.sqlite3", "*.log", "*.pyc", "*.pyo")
JUNK_FILE_PATTERNS = STATE_FILE_PATTERNS + (
    "*.gpickle", "*.bak", "gate_result.json", "run_app_state.json", "run_preview.py", "_preview_requirements.txt", "pytest_output.txt",
    "npm_build.log", ".DS_Store", "consolidated.json",
)
# Extra material the pipeline writes outside backend/ and frontend/; (stage folder, sub path, export folder).
EXTRA_SOURCES = (
    ("p10_docs_delivery", "docs", "docs"),
    ("p14_client_portal", "", "client_portal"),
    ("p15_handoff", "", "handoff"),
)
_PREVIEW_MARKER = "# AetherOS: serve the Vite-built frontend for all non-API paths"
_TEXT_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".html"}
_CONFIG_EXT = {".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".conf", ".properties"}
_PLACEHOLDER_VALUE = re.compile(r"^(?:$|\$|\{\{|<|CHANGE_ME|null$|none$|true$|false$|required$)", re.I)


class ExportError(Exception):
    """The run cannot be exported (nothing to export, or the assembled tree failed the secret scan)."""

    def __init__(self, message: str, findings: Optional[List["Finding"]] = None):
        super().__init__(message)
        self.findings = findings or []


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    line: int = 0

    def __str__(self) -> str:
        return f"{self.path}{':' + str(self.line) if self.line else ''} [{self.rule}]"


# ── What to copy ──────────────────────────────────────────────────────────────

def _matches(name: str, patterns: Tuple[str, ...]) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, p.lower()) for p in patterns)


def skip_reason(name: str) -> Optional[str]:
    """Why a file by this name never ships, or None."""
    if name == ".env.example":
        return "replaced by the generated .env.example"
    if _matches(name, SECRET_FILE_PATTERNS):
        return "secret"
    if _matches(name, JUNK_FILE_PATTERNS):
        return "machine state"
    return None


def unpreview(rel: str, text: str) -> str:
    """Undo the run-preview's rewrites of generated code (they hard-code the preview host, not the app)."""
    if rel.endswith(".py"):
        start = text.find(_PREVIEW_MARKER)
        if start >= 0:
            end = text.rfind("return _spa_index()\n", start)
            end = len(text) if end < 0 else end + len("return _spa_index()\n")
            return text[:start].rstrip() + "\n" + text[end:].lstrip("\n")
        return text
    if Path(rel).suffix not in _TEXT_EXT:
        return text
    text = re.sub(r"^[ \t]*base:\s*['\"]/app-preview/['\"],?[ \t]*\n", "", text, flags=re.M)
    text = re.sub(r"[ \t]*['\"]/app-preview/api['\"]:\s*\{[^{}]*\},?[ \t]*\n", "", text)
    text = text.replace("/app-preview/api", "/api")
    text = re.sub(r"\s+basename=(['\"])/app-preview\1", "", text)
    return re.sub(r",\s*basepath:\s*['\"]/app-preview['\"]", "", text)


def _first_dir(ws: Path, candidates: List[str], marker: str) -> Optional[str]:
    for rel in candidates:
        if safe_fs.stat_or_none(ws, f"{rel}/{marker}" if rel else marker) is not None:
            return rel
    return None


def locate_backend(ws: Path) -> Optional[str]:
    cands = ["p04_backend/backend_codegen", "p04a_backend_codegen"]
    cands += [f"p03_scaffolding/{n}" for n, is_dir in safe_fs.list_dir(ws, "p03_scaffolding") if is_dir]
    cands.append("")
    return _first_dir(ws, cands, "src/main.py") or _first_dir(ws, cands, "main.py")


def locate_frontend(ws: Path) -> Optional[str]:
    # The repaired, built copy s04 writes to <run>/frontend wins over the first draft in p05_frontend.
    return _first_dir(ws, ["frontend", "p05_frontend/frontend"], "package.json")


class _Tree:
    """The export under construction: writes files, keeps the manifest bookkeeping."""

    def __init__(self, dest: Path):
        self.dest = dest
        self.skipped: Dict[str, int] = {}
        self.rewritten: List[str] = []
        self.total = 0
        self.max_total = int(float(os.environ.get("AETHER_EXPORT_MAX_MB", "200")) * 1024 * 1024)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def write(self, rel: str, data: bytes) -> None:
        self.total += len(data)
        if self.total > self.max_total:
            raise ExportError(f"the export is larger than {self.max_total // (1024 * 1024)} MB (AETHER_EXPORT_MAX_MB)")
        out = self.dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)

    def copy_dir(self, ws: Path, src_rel: str, out_prefix: str, transform: bool) -> int:
        # Stage folders and the frontend are skipped by prefix so a backend found at the workspace root is just src/.
        skip_prefixes = tuple(f"{c}{n:02d}" for c in "ps" for n in range(30)) if not src_rel else ()
        n = 0
        for rel in safe_fs.walk_files(ws, src_rel, skip_dirs=SKIP_DIRS, skip_prefixes=skip_prefixes):
            inner = rel.relative_to(src_rel).as_posix() if src_rel else rel.as_posix()
            if not src_rel and inner.split("/")[0] == "frontend":
                continue
            reason = skip_reason(rel.name)
            if reason:
                self.skip(reason)
                continue
            data = safe_fs.read_bytes_or_none(ws, rel, max_bytes=MAX_FILE_BYTES)
            if data is None:    # a link, a special file, vanished, or over the size limit
                self.skip("unreadable or over 5 MB")
                continue
            if transform:
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = None
                if text is not None:
                    new = unpreview(inner, text)
                    if new != text:
                        self.rewritten.append(f"{out_prefix}{inner}")
                        data = new.encode("utf-8")
            self.write(f"{out_prefix}{inner}", data)
            n += 1
        return n


# ── Scan ──────────────────────────────────────────────────────────────────────

_CONTENT_RULES = (
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:ghp_|gho_|ghs_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}")),
    ("slack-token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}")),
    ("preview-host-path", re.compile(r"/app-preview|_FRONTEND_DIST|\.aether_os/projects|/Users/[A-Za-z0-9_.-]+/|/private/tmp/")),
)
_ASSIGN = re.compile(
    r"""(?ix)\b([\w.-]*(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)[\w.-]*)["']?\s*[:=]\s*["']?([^\s"'#,}]*)""")
# A name that says the value is a location, a setting or a duration is not a secret (RSA_PRIVATE_KEY_PATH, TOKEN_TTL).
_NOT_A_SECRET_NAME = re.compile(r"(path|file|dir|url|name|header|length|expire|minutes|days|hours|ttl|algorithm|type)", re.I)
_URL_CREDS = re.compile(r"://[^/\s:@$]+:[^/\s@$]+@")


def _is_config(path: Path) -> bool:
    n = path.name
    return path.suffix in _CONFIG_EXT or n == "Dockerfile" or n.startswith(".env") or n.endswith(".env")


def scan_tree(root: Path) -> List[Finding]:
    """Everything in the assembled tree that must never ship. Reports file + rule, never the value."""
    out: List[Finding] = []
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for d in dirs:
            rel = (base / d).relative_to(root).as_posix()
            if d in SKIP_DIRS or (base == root and STAGE_DIR.match(d)):
                out.append(Finding(rel, "pipeline-folder"))
        for name in files:
            path, rel = base / name, (base / name).relative_to(root).as_posix()
            if path.is_symlink():
                out.append(Finding(rel, "symlink"))
                continue
            if name != ".env.example" and (_matches(name, SECRET_FILE_PATTERNS) or _matches(name, STATE_FILE_PATTERNS)):
                out.append(Finding(rel, "secret-or-state-file"))
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), 1):
                for rule, rx in _CONTENT_RULES:
                    if rx.search(line):
                        out.append(Finding(rel, rule, lineno))
                if _is_config(path):
                    plain = re.sub(r"\$\{[^}]*\}", "$X", line)   # ${VAR:?msg} is a reference, not a value
                    if _URL_CREDS.search(plain):
                        out.append(Finding(rel, "credentials-in-url", lineno))
                    for m in _ASSIGN.finditer(plain):
                        name, value = m.group(1), m.group(2)
                        if not (_PLACEHOLDER_VALUE.match(value) or _NOT_A_SECRET_NAME.search(name) or value.isdigit()):
                            out.append(Finding(rel, "password-like-value", lineno))
    return out


def workflow_path_problems(root: Path) -> List[str]:
    """Every path a GitHub Actions workflow in the tree references that does not exist in the tree (KAN-271 D6)."""
    import yaml
    problems: List[str] = []
    wf_dir = root / ".github" / "workflows"
    for wf in sorted(wf_dir.glob("*.y*ml")) if wf_dir.is_dir() else []:
        doc = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            job_wd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
            for step in job.get("steps") or []:
                wd = step.get("working-directory", job_wd)
                refs = [(wd, "working-directory")]
                with_ = step.get("with") or {}
                refs += [(with_[k], k) for k in ("cache-dependency-path", "context", "file") if k in with_]
                for rel, _ in refs:
                    if not (root / str(rel)).exists():
                        problems.append(f"{wf.name}:{job_name}: {rel} does not exist")
                for line in str(step.get("run", "")).splitlines():
                    for rx, base in ((r"pip install -r (\S+)", wd), (r"npm (?:ci|install)\b", None),
                                     (r"docker build\b.* (\S+)$", ".")):
                        m = re.search(rx, line)
                        if m and m.groups() and not (root / base / m.group(1)).exists():
                            problems.append(f"{wf.name}:{job_name}: {m.group(1)} does not exist (from {base})")
                    m = re.search(r"^\s*(?:PYTHONPATH=\S+ )?pytest (\S+)|python -m compileall -q (\S+)", line)
                    target = (m.group(1) or m.group(2)) if m else None
                    if target and not (root / wd / target).exists():
                        problems.append(f"{wf.name}:{job_name}: {target} does not exist (from {wd})")
                if re.search(r"\bnpm (?:ci|install|run)\b", str(step.get("run", ""))) and not (root / wd / "package.json").exists():
                    problems.append(f"{wf.name}:{job_name}: no package.json in {wd}")
    return problems


def _syntax_warnings(backend: Path) -> List[str]:
    """Backend files that do not parse. Recorded, not fatal: the owner should still get the code to fix it."""
    out: List[str] = []
    for p in sorted(backend.rglob("*.py")):
        try:
            ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError as e:
            out.append(f"{p.relative_to(backend.parent).as_posix()}:{e.lineno}: {e.msg}")
    return out


# ── Assemble ──────────────────────────────────────────────────────────────────

def assemble_export(ws: Path, dest: Path, project_name: str = "app") -> dict:
    """Build the clean tree for run workspace `ws` into the empty folder `dest`; returns the manifest.

    Raises ExportError when there is no backend, or when the assembled tree fails the secret scan.
    """
    ws = Path(ws)
    backend, frontend = locate_backend(ws), locate_frontend(ws)
    if backend is None:
        raise ExportError("no backend (src/main.py or main.py) found in the run workspace")
    tree = _Tree(dest)
    be_files = tree.copy_dir(ws, backend, "backend/", transform=True)
    if safe_fs.stat_or_none(ws, f"{backend}/requirements.txt" if backend else "requirements.txt") is None:
        raise ExportError("the generated backend has no requirements.txt, so it cannot be built")
    fe_files = tree.copy_dir(ws, frontend, "frontend/", transform=True) if frontend is not None else 0
    for stage, sub, folder in EXTRA_SOURCES:
        src = f"{stage}/{sub}" if sub else stage
        if safe_fs.is_real_dir(ws, src):
            tree.copy_dir(ws, src, f"{folder}/", transform=False)
    if be_files == 0:
        raise ExportError("the backend folder had no exportable files")

    be_example = (safe_fs.read_text_or_none(ws, f"{backend}/.env.example" if backend else ".env.example") or "")
    extra_vars = env_vars_from_example(be_example)
    reqs = (dest / "backend" / "requirements.txt").read_text(encoding="utf-8", errors="ignore").lower()
    use_postgres = "asyncpg" in reqs
    module = "src.main" if (dest / "backend" / "src" / "main.py").exists() else "main"
    has_fe = fe_files > 0
    has_lock = (dest / "frontend" / "package-lock.json").exists()
    has_tests = (dest / "backend" / "tests").is_dir()
    scripts: List[str] = []
    if has_fe:
        try:
            scripts = list(json.loads((dest / "frontend" / "package.json").read_text("utf-8")).get("scripts", {}))
        except (ValueError, OSError) as e:
            raise ExportError(f"frontend/package.json is not valid JSON: {e}") from e
        tree.write("frontend/Dockerfile", frontend_dockerfile(has_lock).encode())
        tree.write("frontend/nginx.conf", frontend_nginx_conf().encode())
    tree.write("backend/Dockerfile", backend_dockerfile(module).encode())
    tree.write("docker-compose.yml", compose(use_postgres, has_fe, extra_vars).encode())
    tree.write(".env.example", env_example(use_postgres, extra_vars).encode())
    tree.write("README.md", readme(project_name, has_fe, use_postgres, has_tests).encode())
    tree.write(".gitignore", b".env\n*.pem\n*.db\n*.log\nnode_modules/\ndist/\n__pycache__/\n")
    tree.write(".github/workflows/ci.yml",
               ci_workflow(has_fe, has_tests, has_lock, scripts, "src" if module == "src.main" else "main.py").encode())

    warnings = _syntax_warnings(dest / "backend")
    findings = scan_tree(dest)
    problems = workflow_path_problems(dest)
    if findings or problems:
        raise ExportError(
            "export refused: " + "; ".join([str(f) for f in findings[:20]] + problems[:10])
            + (f" (+{len(findings) - 20} more)" if len(findings) > 20 else ""), findings)
    files = []
    for p in sorted(x for x in dest.rglob("*") if x.is_file()):
        files.append({"path": p.relative_to(dest).as_posix(), "size": p.stat().st_size,
                      "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    manifest = {
        "project": project_name, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "layout": {"backend": backend or ".", "frontend": frontend, "database": "postgres" if use_postgres else "sqlite"},
        "warnings": warnings, "file_count": len(files), "files": files, "excluded": tree.skipped, "rewritten": sorted(tree.rewritten),
        "scan": {"ok": True, "rules": [r for r, _ in _CONTENT_RULES] + ["secret-or-state-file", "password-like-value"]},
    }
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("project_export: %d files for %s (excluded %s)", len(files), project_name, tree.skipped)
    return manifest


@contextlib.contextmanager
def exported_tree(ws: Path, project_name: str = "app") -> Iterator[Tuple[Path, dict]]:
    """The assembled export in a temp folder that is removed on exit: (root, manifest)."""
    with tempfile.TemporaryDirectory(prefix="aether_export_") as tmp:
        root = Path(tmp) / "export"
        root.mkdir()
        yield root, assemble_export(ws, root, project_name)


def iter_files(root: Path) -> Iterator[Tuple[str, bytes]]:
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        yield p.relative_to(root).as_posix(), p.read_bytes()


def build_export_zip(ws: Path, project_name: str = "app") -> Tuple[io.BytesIO, dict]:
    """The export as an in-memory ZIP (every entry under one top-level folder is NOT used: unzip gives the project)."""
    buf = io.BytesIO()
    with exported_tree(ws, project_name) as (root, manifest), zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, data in iter_files(root):
            zf.writestr(rel, data)
    buf.seek(0)
    return buf, manifest


def export_files(ws: Path, project_name: str = "app") -> Tuple[List[Tuple[str, bytes]], dict]:
    """Every file of the clean export as (path, bytes) plus the manifest (for the GitHub push)."""
    with exported_tree(ws, project_name) as (root, manifest):
        return list(iter_files(root)), manifest
