"""P07a: repair of routers/crud.py after a failed startup import, by small verified patches (KAN-212).

Run 13 (22 Nov 2026) got a whole-file rewrite cut off mid-call; #59 rejected it, but the repair was still a blind
rewrite of a large file. The model now sees the numbered lines around the traceback and returns find/replace patches.
"""
from __future__ import annotations

import logging
from pathlib import Path

from aether_os.core.codegen.patching import apply_verified, build_prompt, error_context, request_patches

logger = logging.getLogger(__name__)

_HINTS = ("Common causes: 1. imports of non-existent model classes 2. relative imports (use ..models, not models) "
          "3. hallucinated schema imports that do not exist in ..schemas. Keep `all_routers` at the end of the file.")


async def repair_crud(src_dir: Path, error_text: str) -> bool:
    """True when at least one verified patch was applied to crud.py (or another project file the traceback names)."""
    root = src_dir.parent
    crud = src_dir / "routers" / "crud.py"
    source = error_context(root, error_text)
    if "routers/crud.py" not in source:   # the traceback did not point at it: show its head so `find` can match
        head = "\n".join(f"{n}| {ln[:300]}" for n, ln in enumerate(crud.read_text().splitlines()[:60], 1))
        source += f"\n--- {crud.relative_to(root)} (lines 1-60)\n{head}"
    prompt = build_prompt("You are a FastAPI developer. Importing the generated app fails.", error_text, source,
                          example=str(crud.relative_to(root)), extra=_HINTS)
    report = await apply_verified(root, await request_patches(prompt, "[p07a] crud repair"), "[p07a] crud repair")
    report.log("[p07a] crud repair", 1)
    return report.applied > 0
