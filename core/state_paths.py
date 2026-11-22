"""Where the platform writes runtime state: one writable directory, never the package itself.

The API image is read-only for its non-root user, so files written next to the code failed on production
(22 Nov 2026): `error_registry.json` ("Permission denied: .../core/error_registry.tmp"), and Guardian snapshots
defaulted to ./snapshots relative to the working directory (/srv/snapshots). Everything now lives under
AETHER_STATE_DIR (default ~/.aether_os, already used for run projects). Files that ship with a seed copy in the
package are copied there on first use, so learned data starts from the shipped baseline.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def state_dir() -> Path:
    return Path(os.environ.get("AETHER_STATE_DIR") or (Path.home() / ".aether_os"))


def state_file(relative: str, seed: Path | None = None) -> Path:
    """Path of a runtime file under the state directory, copied from `seed` the first time if that exists."""
    dest = state_dir() / relative
    if not dest.exists() and seed is not None and seed.is_file():
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(seed, dest)
        except OSError as exc:
            logger.warning("state_paths: could not seed %s from %s: %s", dest, seed, exc)
    return dest
