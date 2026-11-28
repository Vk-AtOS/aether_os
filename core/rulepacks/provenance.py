"""Which files of a generated app a model wrote (KAN-243).

The rule-pack gate (pipeline_gate.py) treats a blocking finding differently by author: a model-written file goes back
to the model for repair, a template file is a platform bug and fails the run. The generators record every file a
model wrote here, in `<app root>/.aetheros/model_files.json` (paths relative to the app root). `.aetheros` travels with
the app when a stage copies it (p05 -> <run>/frontend) and is never exported (core/project_export.SKIP_DIRS).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

LEDGER = Path(".aetheros") / "model_files.json"


def _app_root(path: Path) -> Path | None:
    """The app folder that holds `path`: the nearest parent with package.json (frontend) or a src/main.py / main.py
    (backend)."""
    for parent in path.resolve().parents:
        if (parent / "package.json").is_file() or (parent / "src" / "main.py").is_file() \
                or ((parent / "main.py").is_file() and parent.name != "src"):
            return parent
    return None


def load_model_files(app_root: Path) -> set[str]:
    try:
        data = json.loads((Path(app_root) / LEDGER).read_text(encoding="utf-8"))
        return {str(f) for f in data.get("files", []) if isinstance(f, str)}
    except FileNotFoundError:
        return set()
    except (OSError, ValueError, AttributeError) as e:
        logger.warning("rulepacks provenance: unreadable ledger in %s: %s", app_root, e)
        return set()


def record_model_files(app_root: Path, rel_paths: Iterable[str]) -> None:
    """Add paths (relative to app_root) to the ledger."""
    app_root = Path(app_root)
    files = load_model_files(app_root) | {Path(r).as_posix() for r in rel_paths}
    try:
        (app_root / LEDGER).parent.mkdir(parents=True, exist_ok=True)
        (app_root / LEDGER).write_text(json.dumps({"files": sorted(files)}, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("rulepacks provenance: cannot write the ledger in %s: %s", app_root, e)


def write_model_file(path: Path, code: str, app_root: Path | None = None) -> None:
    """Write model output to `path` and record it. app_root defaults to the app folder that holds the file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    root = Path(app_root) if app_root else _app_root(path)
    if root is None:
        logger.warning("rulepacks provenance: %s is not inside a generated app; not recorded", path)
        return
    record_model_files(root, [path.resolve().relative_to(root.resolve()).as_posix()])
