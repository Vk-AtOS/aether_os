"""Velaris API — read-only view of the operations platform for the unified dashboard.

Velaris is a separate codebase. Its code is never imported into this process:
the inventory is produced by a short-lived subprocess run inside VELARIS_HOME,
with a fixed command and no caller-supplied input.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException

from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/velaris", tags=["velaris"])

_INVENTORY_CODE = (
    "import json; from velaris.agents.inventory import inventory; print(json.dumps(inventory()))"
)
_CACHE_SECONDS = 60
_cache: Optional[Tuple[float, Dict[str, Any]]] = None


def _home() -> Path:
    home = os.environ.get("VELARIS_HOME", "")
    if not home or not (Path(home) / "velaris").is_dir():
        raise HTTPException(
            status_code=503,
            detail="Velaris is not connected. Set VELARIS_HOME to the Velaris repository path.",
        )
    return Path(home)


async def _run_inventory(home: Path) -> Dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", _INVENTORY_CODE, cwd=str(home),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError as e:
        proc.kill()
        raise HTTPException(status_code=504, detail="Velaris inventory timed out") from e
    if proc.returncode != 0:
        logger.warning("velaris inventory failed: %s", err.decode(errors="replace")[-500:])
        raise HTTPException(status_code=502, detail="Velaris inventory failed; see server log")
    return json.loads(out.decode().strip().splitlines()[-1])


@router.get("/inventory")
async def inventory(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Agents per department with an honest status: real, rule_based or not_implemented."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    raw = await _run_inventory(_home())
    departments = []
    totals = {"real": 0, "rule_based": 0, "not_implemented": 0}
    for name in sorted(raw):
        by_status = raw[name]
        counts = {s: len(by_status.get(s, [])) for s in totals}
        for s, n in counts.items():
            totals[s] += n
        departments.append({
            "name": name, "counts": counts, "total": sum(counts.values()),
            "agents": sorted(
                ({"name": a, "status": s} for s in totals for a in by_status.get(s, [])),
                key=lambda a: a["name"],
            ),
        })
    result = {"departments": departments, "totals": totals, "total": sum(totals.values())}
    _cache = (time.monotonic(), result)
    return result
