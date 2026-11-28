"""KAN-266: checks of the downloaded export (zip bytes): clean of secrets and pipeline junk, buildable, scannable.

Works on the zip in memory; nothing is extracted unless a local build is asked for, and then only after every member
name is proven to stay inside the target folder (the zip is untrusted data).
"""
from __future__ import annotations

import fnmatch
import importlib
import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

from acceptance.suite_checks import CheckResult, fail, ok, skip

SECRET_NAMES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "credentials*.json",
                "*credentials*.json", "secrets.json", "secrets.y*ml", ".npmrc", ".pypirc", "*.db", "*.sqlite*", "*.log")
STAGE_DIR = re.compile(r"^(?:p\d{2}_|s\d{2}_)")
# Content that is a credential whatever the file is called. Built from parts so this file never contains one.
SECRET_CONTENT = [
    ("private key", re.compile("-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE" + " KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("API key", re.compile(r"\b(?:sk-ant-|sk-|ghp_|xox[bp]-)[A-Za-z0-9_\-]{20,}")),
]
TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yml", ".yaml", ".toml", ".md", ".txt", ".html", ".cfg", ".ini", ".env"}


def open_zip(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


def check_export_clean(data: bytes) -> CheckResult:
    try:
        zf = open_zip(data)
    except zipfile.BadZipFile as e:
        return fail("export_clean", f"the download is not a zip: {e}")
    names = [n for n in zf.namelist() if not n.endswith("/")]
    problems: List[str] = []
    for n in names:
        parts = PurePosixPath(n).parts
        base = parts[-1]
        if n.startswith("/") or ".." in parts:
            problems.append(f"unsafe path {n}")
        if base != ".env.example" and any(fnmatch.fnmatch(base, pat) for pat in SECRET_NAMES):
            problems.append(f"secret/state file {n}")
        if base == "preview_credentials.json" or (parts and STAGE_DIR.match(parts[0])):
            problems.append(f"pipeline workspace leaked: {n}")
        if "node_modules" in parts or "__pycache__" in parts:
            problems.append(f"build junk {n}")
        if PurePosixPath(n).suffix in TEXT_EXT and zf.getinfo(n).file_size < 2_000_000:
            text = zf.read(n).decode("utf-8", "ignore")
            problems += [f"{label} in {n}" for label, rx in SECRET_CONTENT if rx.search(text)]
    if not any(n.startswith("backend/") for n in names):
        problems.append("no backend/ folder in the export")
    if "MANIFEST.json" not in names:
        problems.append("no MANIFEST.json")
    if problems:
        return fail("export_clean", f"{len(problems)} problem(s): " + "; ".join(problems[:8]), count=len(problems))
    return ok("export_clean", f"{len(names)} files, no secrets, no stage folders")


def check_forbidden_patterns(data: bytes, patterns: List[str]) -> CheckResult:
    """Tools bounded: the agent's backend source must not contain any of the forbidden constructs (shell, eval ...)."""
    rxs = [re.compile(p) for p in patterns]
    zf, hits = open_zip(data), []
    for n in zf.namelist():
        if n.startswith("backend/") and n.endswith(".py") and "/tests/" not in n and "/test_" not in n:
            text = zf.read(n).decode("utf-8", "ignore")
            hits += [f"{n}: /{rx.pattern}/" for rx in rxs if rx.search(text)]
    return fail("tools_bounded", "forbidden constructs in the generated backend: " + "; ".join(hits[:6])) if hits \
        else ok("tools_bounded", f"none of {len(patterns)} forbidden patterns appear in backend/")


def safe_extract(data: bytes, dest: Path) -> None:
    root = dest.resolve()
    with open_zip(data) as zf:
        for m in zf.infolist():
            target = (root / m.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"zip member escapes the target folder: {m.filename}")
        zf.extractall(root)


def _run(cmd: List[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)  # noqa: S603


def local_frontend_build(data: bytes, timeout: int = 900) -> Dict[str, Any]:
    """npm install, tsc --noEmit and vite build on the exported frontend/. {ok, reason} or {skipped}."""
    if not shutil.which("npm"):
        return {"skipped": "npm is not installed on this machine, so the export's frontend could not be built"}
    with tempfile.TemporaryDirectory(prefix="accept-fe-") as tmp:
        try:
            safe_extract(data, Path(tmp))
            fe = Path(tmp) / "frontend"
            if not fe.is_dir():
                return {"ok": False, "reason": "the export has no frontend/ folder"}
            for label, cmd in (("npm install", ["npm", "install", "--no-audit", "--no-fund"]),
                               ("tsc --noEmit", ["npx", "--no-install", "tsc", "--noEmit"]),
                               ("vite build", ["npm", "run", "build"])):
                r = _run(cmd, fe, timeout)
                if r.returncode != 0:
                    return {"ok": False, "reason": f"{label} failed: " + (r.stdout + r.stderr).strip()[-400:]}
            return {"ok": True}
        except (ValueError, OSError, subprocess.SubprocessError) as e:
            return {"ok": False, "reason": f"frontend build could not run: {e}"}


def check_rulepacks(data: bytes) -> CheckResult:
    """Zero blocking findings from core/rulepacks/report.py, when that module exists (it may not be on main yet)."""
    for modname in ("aether_os.core.rulepacks.report", "core.rulepacks.report"):
        try:
            mod = importlib.import_module(modname)
            break
        except ImportError:
            mod = None
    if mod is None:
        return skip("rulepacks_zero_blocking", "core/rulepacks/report.py is not present in this checkout")
    fn = next((getattr(mod, n) for n in ("scan_tree", "scan_directory", "scan", "run") if callable(getattr(mod, n, None))), None)
    if fn is None:
        return skip("rulepacks_zero_blocking", f"{mod.__name__} has no scan_tree/scan_directory/scan/run function this suite knows")
    with tempfile.TemporaryDirectory(prefix="accept-rp-") as tmp:
        safe_extract(data, Path(tmp))
        res = fn(Path(tmp))
    findings = res.get("findings", []) if isinstance(res, dict) else getattr(res, "findings", res)
    blocking = [f for f in (findings or []) if (f.get("blocking") if isinstance(f, dict) else getattr(f, "blocking", False))]
    return fail("rulepacks_zero_blocking", f"{len(blocking)} blocking finding(s): " + "; ".join(str(f)[:120] for f in blocking[:4])) \
        if blocking else ok("rulepacks_zero_blocking", "0 blocking findings")
