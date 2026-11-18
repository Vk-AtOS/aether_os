"""A live axe-core result for the frontend critic (KAN-177).

s05 critiques the frontend before the a11y phase (p07c, stage s06) has run, so the critic had no axe
number. When a build (dist/ with index.html) exists and the browser sandbox is available, this runs axe
now, in that sandbox (core/sandbox/browser_job.py: Chromium never runs on the host); otherwise it says
why it did not. "Did not run" is None plus a note, never zero violations.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Sequence, Tuple

from aether_os.core.run_app import safe_fs
from aether_os.core.sandbox import phase_exec
from aether_os.core.sandbox.browser_job import run_browser_job
from aether_os.core.sandbox.runner import SandboxUnavailable, sandbox_dirs

logger = logging.getLogger(__name__)
_PORT = 4173   # the browser sandbox's own loopback
_TAGS = ("wcag2a", "wcag2aa", "wcag21a", "wcag21aa")


async def live_axe_violations(frontend_dir: Path, tags: Sequence[str] = _TAGS) -> Tuple[Optional[int], str]:
    """(violation count or None, note). None = axe did not run; the note says why."""
    frontend_dir = Path(frontend_dir)
    dist = frontend_dir / "dist"
    root = phase_exec.project_root(frontend_dir)
    try:
        rel = dist.relative_to(root)
    except ValueError:
        return None, "axe-core did not run: the frontend is outside the run directory"
    if safe_fs.stat_or_none(root, rel / "index.html") is None:
        return None, "axe-core did not run: no build (dist/index.html)"
    out = Path(sandbox_dirs(root)["TMPDIR"]) / "axe_live.json"
    job = {"action": "axe", "tags": list(tags), "out": str(out),
           "serve": {"dir": str(dist), "port": _PORT}, "url": f"http://127.0.0.1:{_PORT}/"}
    try:
        reply = await run_browser_job(job, project=frontend_dir, timeout=60)
    except SandboxUnavailable as exc:
        return None, f"axe-core did not run: browser sandbox unavailable ({exc})"
    except Exception as exc:
        logger.warning("axe_live: job failed: %s", exc)
        return None, "axe-core did not run: the browser job failed"
    if not reply.get("ok") or not isinstance(reply.get("violations"), int):
        return None, f"axe-core did not run: {reply.get('error') or 'no result'}"
    return reply["violations"], ""
