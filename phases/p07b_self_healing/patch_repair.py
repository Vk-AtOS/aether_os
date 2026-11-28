"""P07b: repair of the failing backend file by small verified patches (KAN-212).

`_get_fix` asked for the whole failing file back: slow, easily truncated, and it silently dropped code. The model now
sees the numbered source around each traceback location and returns find/replace patches; each is applied only when
`find` is unique and the file still compiles. A whole-file rewrite is the fallback for files under 3000 chars only,
behind the same guards as #59 (compiles, keeps its names, not under half the size).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from aether_os.core.codegen.patching import (
    apply_verified, build_prompt, error_context, reject_rewrite, request_patches,
)

logger = logging.getLogger(__name__)
TAG = "[p07b_self_healing]"

_RULES = (
    "Rules: use flat absolute imports (`import models`, `from database import get_db`), never relative imports; "
    "use `result.scalars().all()` for async SQLAlchemy lists; import every name you use. Never edit tests. "
    "If you touch routers/crud.py keep `all_routers = [...]` at the end of the file."
)


def flatten_imports(code: str) -> str:
    """The generated app runs from src/, so sibling modules are importable directly: `from .foo` -> `from foo`."""
    code = re.sub(r"from\s*\.+\s*(\w)", r"from \1", code)
    return re.sub(r"import\s*\.+\s*(\w)", r"import \1", code)


def ensure_all_routers(code: str, file: Path) -> str:
    """crud.py must always export all_routers; add it from the APIRouter variables when a fix dropped it."""
    if file.name != "crud.py" or "all_routers" in code:
        return code
    router_vars = re.findall(r"^(\w+_router)\s*=\s*APIRouter", code, re.MULTILINE)
    if not router_vars:
        return code
    logger.info("%s Auto-injected all_routers: %s", TAG, router_vars)
    return code.rstrip() + f"\n\nall_routers = [{', '.join(router_vars)}]\n"


def may_heal(project_dir: Path):
    """Application source under the project's src/ only. Rewriting a test makes it pass without fixing the app, so
    test_*/conftest*/tests/ and anything outside src/ are never allowed."""
    root = project_dir.resolve()

    def allowed(target: Path) -> bool:
        rel = target.relative_to(root).parts if target.is_relative_to(root) else ()
        return bool(rel) and "src" in rel[:-1] and target.suffix == ".py" and not target.name.startswith(
            ("test_", "conftest")) and not any(p in ("tests", "test") for p in rel)
    return allowed


def _context(project_dir: Path, failing_file: Path, output: str) -> str:
    source = error_context(project_dir, output)
    if failing_file.name not in source:   # no traceback location: show the file's head so `find` can be copied
        try:
            lines = failing_file.read_text().splitlines()[:80]
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("%s cannot read %s: %s", TAG, failing_file, exc)
            lines = []
        rel = failing_file.relative_to(project_dir) if failing_file.is_relative_to(project_dir) else failing_file.name
        source += f"\n--- {rel} (lines 1-{len(lines)})\n" + "\n".join(f"{n}| {ln[:300]}" for n, ln in enumerate(lines, 1))
    return source


async def heal_file(
    failing_file: Path,
    project_dir: Path,
    test_file: Path,
    output: str,
    quality_details: Optional[Dict[str, Any]],
    council_feedback: str,
    attempt: int,
    rewrite: Callable[..., Awaitable[Optional[str]]],
) -> bool:
    """Try to fix `failing_file`; True when the file on disk changed. `rewrite` is the whole-file fallback (_get_fix)."""
    extra = _RULES
    low = [f"{k}: {v}%" for k, v in (quality_details or {}).items()
           if k != "total" and isinstance(v, (int, float)) and v < 80]
    if low:
        extra += "\nQuality metrics below 80% (fix these too): " + ", ".join(low)
    if council_feedback:
        extra += f"\nBackend audit council issues (also fix): {council_feedback[:1500]}"
    rel = failing_file.relative_to(project_dir) if failing_file.is_relative_to(project_dir) else Path(failing_file.name)
    prompt = build_prompt("You are a senior FastAPI backend engineer. The generated tests fail.", output[:2000],
                          _context(project_dir, failing_file, output), example=str(rel), extra=extra)
    patches = [dict(p, replace=flatten_imports(p["replace"])) if isinstance(p, dict) and isinstance(p.get("replace"), str)
               else p for p in await request_patches(prompt, TAG)]
    report = await apply_verified(project_dir, patches, may_heal(project_dir), TAG)
    report.log(TAG, attempt)
    if report.applied:
        try:
            text = failing_file.read_text()
            fixed = ensure_all_routers(text, failing_file)
            if fixed != text:
                failing_file.write_text(fixed)
        except OSError as exc:
            logger.warning("%s post-patch check of %s failed: %s", TAG, failing_file, exc)
        return True

    # No patch applied: a whole-file rewrite only for a tiny file the repair may change, and only behind the guards.
    # The patches went through may_heal but this rewrite did not: run da281716 rewrote a vendored sqlalchemy file.
    if not may_heal(project_dir)(failing_file.resolve()):
        logger.warning("%s %s is not a file this repair may change; no whole-file rewrite", TAG, rel)
        return False
    try:
        original = failing_file.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("%s cannot read %s: %s", TAG, failing_file, exc)
        return False
    if len(original) >= 3000:
        logger.warning("%s no patch applied and %s is too large (%d chars) for a rewrite; leaving it unchanged",
                       TAG, failing_file.name, len(original))
        return False
    fix = await rewrite(failing_file, test_file, output, quality_details, council_feedback)
    if not fix:
        return False
    fix = ensure_all_routers(flatten_imports(fix), failing_file)
    why = reject_rewrite(fix, original, failing_file)
    if why:
        logger.warning("%s whole-file rewrite of %s rejected (%s); keeping the original", TAG, failing_file.name, why)
        return False
    failing_file.write_text(fix)
    logger.info("%s rewrote %s (%d -> %d chars)", TAG, failing_file.name, len(original), len(fix))
    return True
