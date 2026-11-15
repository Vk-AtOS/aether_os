"""P05 Frontend — npm build helpers and concurrency limiter.

Caps concurrent Vite builds at 2 to prevent CPU saturation on shared hosts.
Semaphore is created lazily inside the running event loop.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Optional

from aether_os.core.sandbox import phase_exec

# ── npm build concurrency limiter ─────────────────────────────────────────────
_NPM_SEMAPHORE: Optional[asyncio.Semaphore] = None

# The generated app builds for the root ("/") by default. The AetherOS preview serves it under /app-preview/,
# so builds made for the preview pass this base through the environment (vite.config.ts reads VITE_BASE_PATH).
PREVIEW_BUILD_ENV = {"VITE_BASE_PATH": os.environ.get("AETHER_PREVIEW_BASE_PATH", "/app-preview/")}

_NPM_SHARED_CACHE = Path.home() / ".aether_os" / "npm_cache"
_NM_STAMP_FILE = ".nm_hash"


def _get_npm_semaphore() -> asyncio.Semaphore:
    global _NPM_SEMAPHORE
    if _NPM_SEMAPHORE is None:
        _NPM_SEMAPHORE = asyncio.Semaphore(2)
    return _NPM_SEMAPHORE


# Public alias used by task_agent.py
get_npm_semaphore = _get_npm_semaphore


def _pkg_hash(frontend_dir: Path) -> str:
    """MD5 of package.json — used as node_modules cache key."""
    p = frontend_dir / "package.json"
    return hashlib.md5(p.read_bytes(), usedforsecurity=False).hexdigest() if p.exists() else ""


def _node_modules_fresh(frontend_dir: Path, hash_val: str) -> bool:
    """True if node_modules exists and its stamp matches the current package.json hash."""
    nm = frontend_dir / "node_modules"
    stamp = frontend_dir / _NM_STAMP_FILE
    return bool(hash_val) and nm.exists() and stamp.exists() and stamp.read_text().strip() == hash_val


def _stamp_node_modules(frontend_dir: Path, hash_val: str) -> None:
    if hash_val:
        (frontend_dir / _NM_STAMP_FILE).write_text(hash_val)


# Public aliases used by task_agent.py
def pkg_hash(frontend_dir: Path) -> str:
    """MD5 of package.json — used as node_modules cache key."""
    return _pkg_hash(frontend_dir)


def node_modules_fresh(frontend_dir: Path, hash_val: str) -> bool:
    """True if node_modules exists and its stamp matches the current package.json hash."""
    return _node_modules_fresh(frontend_dir, hash_val)


def stamp_node_modules(frontend_dir: Path, hash_val: str) -> None:
    _stamp_node_modules(frontend_dir, hash_val)


async def run_npm_build(frontend_dir: Path) -> bool:
    """Run npm install (with cache) + npm run build, semaphore-limited. True when both exited 0."""
    async with _get_npm_semaphore():
        h = _pkg_hash(frontend_dir)
        if not _node_modules_fresh(frontend_dir, h):
            # Install = the sandbox's install egress profile; the npm cache lives in the run's own HOME.
            install = await phase_exec.run(["npm", "install"], cwd=frontend_dir, timeout=300, network=True)
            if install.returncode != 0:
                return False
            _stamp_node_modules(frontend_dir, h)
        build = await phase_exec.run(["npm", "run", "build"], cwd=frontend_dir, timeout=600, env=PREVIEW_BUILD_ENV)
        return build.returncode == 0
