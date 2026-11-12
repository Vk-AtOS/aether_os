"""Stage-keyed phase output for GET /factory/runs/{id}.

phase_completions rows (and so `phases` in the response) are keyed by the 12 stage ids, but
generated artifacts still live in per-sub-phase folders at the project root
(p04_backend/..., p05_frontend/...; see docs/BLUEPRINT.md section 2). STAGE_FOLDERS is the one
explicit mapping from a stage to the folders that can hold its output: the stage's own folder
first (its summary, e.g. s02_architecture/s02_architecture.json), then its sub-phases' folders,
taken from the same table the legacy-id resolver uses (orchestrator/phase_selector.py).

A legacy key (a run from before the 12-stage pipeline) is its own folder, as before.
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any, Dict, List, Optional, Tuple

from aether_os.core.run_app import safe_fs
from aether_os.orchestrator.phase_selector import _STAGE_SUB_PHASES

logger = logging.getLogger(__name__)

OUTPUT_FILE_CANDIDATES = [
    "consolidated.json", "architecture.json", "frontend_meta.json",
    "review.json", "test_results.json", "delivery.json",
    "observability.json", "cicd.json",
]

# stage id -> folders (relative to the project root) that can hold its output, in priority order.
STAGE_FOLDERS: Dict[str, Tuple[str, ...]] = {
    stage: (stage, *subs) for stage, subs in _STAGE_SUB_PHASES.items()
}

# Where the security scan writes its findings, per stage (and for the legacy sub-phase key).
SECURITY_REPORTS: Dict[str, str] = {
    "s05_quality": "p06_review_security/security/security_report.json",
    "p06_review_security": "p06_review_security/security/security_report.json",
}


def folders_for(key: str) -> Tuple[str, ...]:
    return STAGE_FOLDERS.get(key, (key,))


def _load_json(project_dir: pathlib.Path, rel: str) -> Optional[Any]:
    """Parse one artifact. The project dir is writable by the sandboxed app, so it is read
    through safe_fs: a link anywhere on the path, a non-regular file or an oversized file is
    skipped (None), never followed."""
    text = safe_fs.read_text_or_none(project_dir, rel)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError as exc:
        logger.debug("phase output: cannot parse %s: %s", rel, exc)
        return None


def _first_output(project_dir: pathlib.Path, key: str, folder: str) -> Optional[Tuple[Any, str]]:
    if not safe_fs.is_real_dir(project_dir, folder):   # a symlinked stage folder is skipped
        return None
    for name in [*OUTPUT_FILE_CANDIDATES, f"{key}.json", f"{folder}.json"]:
        data = _load_json(project_dir, f"{folder}/{name}")
        if data is not None:
            return data, f"{folder}/{name}"
    for name, is_dir in safe_fs.list_dir(project_dir, folder):   # sorted, links left out
        if is_dir or not name.endswith(".json") or name == "gate_result.json":
            continue
        data = _load_json(project_dir, f"{folder}/{name}")
        if data is not None:
            return data, f"{folder}/{name}"
    return None


def _artifact_summary(project_dir: pathlib.Path, folders: List[str]) -> Optional[Dict[str, Any]]:
    """For a stage whose folders hold files but no JSON summary: which folders, how many files."""
    present = [f for f in folders if safe_fs.is_real_dir(project_dir, f)]
    count = sum(len(safe_fs.walk_files(project_dir, f, skip_dirs=("node_modules", ".git"),
                                       skip_prefixes=(".venv",))) for f in present)
    return {"artifact_folders": present, "file_count": count} if count else None


def stage_output(project_dir: pathlib.Path, key: str) -> Tuple[Optional[Any], Optional[str]]:
    """(output, output_file) for one phases key, or (None, None) when it has no artifacts."""
    folders = list(folders_for(key))
    for folder in folders:
        found = _first_output(project_dir, key, folder)
        if found:
            return found
    return _artifact_summary(project_dir, folders), None


def stage_gate_result(project_dir: pathlib.Path, key: str) -> Optional[Any]:
    for folder in folders_for(key):
        data = _load_json(project_dir, f"{folder}/gate_result.json")
        if data is not None:
            return data
    return None


def enrich_phases(phases: Dict[str, Any], project_dir: pathlib.Path, project_prefix: str) -> Dict[str, Any]:
    """Inject output / output_file / gate_result per phases key, then strip server paths."""
    for key, value in phases.items():
        output, output_file = stage_output(project_dir, key)
        if output is not None:
            value["output"] = output
            if output_file:
                value["output_file"] = output_file
        gate = stage_gate_result(project_dir, key)
        if gate is not None:
            value["gate_result"] = gate

    for key, rel in SECURITY_REPORTS.items():
        if key in phases:
            data = _load_json(project_dir, rel)
            if isinstance(data, dict):
                out = phases[key].setdefault("output", {})
                if isinstance(out, dict):
                    out["security_findings"] = data.get("findings", [])
                    out["security_total"] = data.get("total", 0)

    def _strip(obj: Any) -> Any:  # S8: never expose absolute server paths
        if isinstance(obj, str):
            return obj.replace(project_prefix, "")
        if isinstance(obj, dict):
            return {k: _strip(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_strip(v) for v in obj]
        return obj

    return _strip(phases)
