"""P05 build loop <-> fix memory (KAN-215): try stored fixes before a model call, remember what worked.

One RoundMemory per run_build_loop. It never raises: a memory failure must not break the build, it only disables
itself (logged), and the loop falls back to the model.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from aether_os.core import fix_memory
from aether_os.core.run_context import ACTIVE_RUN_ID

logger = logging.getLogger(__name__)
_ALL_ERRORS = 200


class RoundMemory:
    def __init__(self, org_id: Optional[str], frontend_dir: Path, apply_patch: Callable[[Path, dict], bool]):
        self.org_id, self.dir, self._apply = org_id or "", frontend_dir, apply_patch
        self.hits = 0
        self._run_id = ACTIVE_RUN_ID.get()   # provenance of every stored row
        self._candidates: list[dict] = []     # screened model patches (safe, same file, near the error line)
        self._tried: set[str] = set()
        self._pending: list[dict] = []   # applied last round, not yet judged by a rebuild: {signature, kind, patches, reused}

    @property
    def active(self) -> bool:
        return bool(self.org_id)

    def _disable(self, what: str, exc: Exception) -> None:
        logger.warning("p05 fix memory: %s failed, memory disabled for this build: %s", what, exc)
        self.org_id = ""

    async def try_known(self, output: str) -> int:
        """Apply stored fixes for the errors in `output`. Returns how many patches were applied (0: ask the model)."""
        if not self.active:
            return 0
        total = 0
        try:
            for err in fix_memory.parse_errors(output):
                sig = err["signature"]
                if sig in self._tried:
                    continue   # already tried in this build: never loop on the same stored fix
                self._tried.add(sig)
                applied = await fix_memory.apply_stored(
                    self.org_id, sig, lambda p: self._apply(self.dir, p), target_file=err["file"])
                if applied:
                    self.hits += 1
                    total += len(applied)
                    self._pending.append({"signature": sig, "kind": err["file_kind"], "patches": applied, "reused": True})
                    logger.info("p05 fix memory: hit sig=%s (%d patch(es)), model call skipped; hits so far=%d",
                                sig[:8], len(applied), self.hits)
        except Exception as exc:
            self._disable("lookup", exc)
        return total

    def screen_model_patches(self, output: str, patches: list) -> None:
        """BEFORE the patches are applied: keep only those that may be stored (memory poisoning guard, see
        fix_memory.patch_targets_error). Needs the pre-patch source to locate the `find` span."""
        self._candidates = []
        if not self.active:
            return
        for err in fix_memory.parse_errors(output):
            try:
                source = (self.dir / err["file"]).read_text()
            except Exception as exc:
                logger.debug("p05 fix memory: cannot read %s: %s", err["file"], exc)
                continue
            for p in patches:
                if isinstance(p, dict) and fix_memory.patch_targets_error(p, err, source):
                    self._candidates.append({**err, "patch": p})

    def remember_model_patches(self, applied: list[dict]) -> None:
        """AFTER applying: screened patches that were applied are stored once a rebuild confirms them."""
        for c in self._candidates:
            if c["patch"] in applied:
                self._pending.append({"signature": c["signature"], "kind": c["file_kind"], "patches": [c["patch"]],
                                      "reused": False})
        self._candidates = []

    async def settle(self, output: str) -> None:
        """After a rebuild: fixes whose error is gone are stored / confirmed; a reused fix whose error remains fails."""
        if not self.active or not self._pending:
            return
        pending, self._pending = self._pending, []
        try:
            current = {e["signature"] for e in fix_memory.parse_errors(output, limit=_ALL_ERRORS)}
            for item in pending:
                sig = item["signature"]
                if sig not in current:
                    if item["reused"]:
                        await fix_memory.mark_hit(self.org_id, sig)
                    else:
                        await fix_memory.record(self.org_id, sig, item["kind"], item["patches"], run_id=self._run_id)
                elif item["reused"] and await fix_memory.mark_failure(self.org_id, sig):
                    logger.info("p05 fix memory: sig=%s dropped after repeated failure", sig[:8])
        except Exception as exc:
            self._disable("settle", exc)
