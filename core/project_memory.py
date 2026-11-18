"""
AetherOS — Project Living Memory (D6)

Creates and maintains .aetheros/project_memory.json in each generated
project directory. Called by the factory pipeline after each phase
completes and at final pipeline completion.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from aether_os.core.run_app import safe_fs

logger = logging.getLogger(__name__)

_MEMORY_DIR = ".aetheros"
_MEMORY_FILE = "project_memory.json"
_VERSION = "1.0.0"


def _memory_path(project_dir: Path) -> Path:
    return project_dir / _MEMORY_DIR / _MEMORY_FILE


def init_memory(
    project_dir: Path,
    *,
    project_name: str,
    requirement: str,
    domain: str,
    run_id: str,
) -> Dict[str, Any]:
    """Create initial project_memory.json. Safe to call multiple times."""
    safe_fs.safe_makedirs(project_dir, _MEMORY_DIR)   # the sandboxed app writes here: no links

    text = _text(project_dir)
    if text is not None:
        try:
            return json.loads(text)
        except Exception as exc:
            logger.debug("Project memory JSON parse failed, reinitializing: %s", exc)

    memory = {
        "project_name": project_name,
        "original_requirement": requirement,
        "domain": domain,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "aetheros_version": _VERSION,
        "tech_stack": {},
        "architectural_decisions": [],
        "security_findings": [],
        "quality_scores": {},
        "test_results": {"passed": 0, "failed": 0, "coverage_pct": 0},
        "changelog": [],
    }
    _write(project_dir, memory)
    return memory


def update_memory(project_dir: Path, updates: Dict[str, Any]) -> None:
    """Merge updates into the existing project memory."""
    text = _text(project_dir)
    if text is None:
        return
    try:
        memory = json.loads(text)
        _deep_merge(memory, updates)
        _write(project_dir, memory)
    except Exception as exc:
        logger.debug("update_memory failed: %s", exc)


def add_architectural_decision(
    project_dir: Path,
    *,
    phase: str,
    decision: str,
    rationale: str,
) -> None:
    text = _text(project_dir)
    if text is None:
        return
    try:
        memory = json.loads(text)
        memory.setdefault("architectural_decisions", []).append({
            "phase": phase,
            "decision": decision,
            "rationale": rationale,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })
        _write(project_dir, memory)
    except Exception as exc:
        logger.debug("add_architectural_decision failed: %s", exc)


def add_changelog_entry(
    project_dir: Path,
    entry: str,
    author: str = "system",
) -> None:
    text = _text(project_dir)
    if text is None:
        return
    try:
        memory = json.loads(text)
        memory.setdefault("changelog", []).append({
            "author": author,
            "entry": entry,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _write(project_dir, memory)
    except Exception as exc:
        logger.debug("add_changelog_entry failed: %s", exc)


def read_memory(project_dir: Path) -> Optional[Dict[str, Any]]:
    mem_file = _memory_path(project_dir)
    text = _text(project_dir)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception as e:
        logger.warning("read_memory failed for %s: %s", mem_file, e)
        return None


def build_enhance_context(memory: Dict[str, Any]) -> str:
    """Convert project memory into a context string for the requirements phase."""
    lines = [
        "=== EXISTING PROJECT CONTEXT ===",
        f"Project: {memory.get('project_name', 'Unknown')}",
        f"Domain: {memory.get('domain', 'general')}",
        f"Original requirement: {memory.get('original_requirement', '')}",
    ]
    tech = memory.get("tech_stack", {})
    if tech:
        lines.append(f"Tech stack: {json.dumps(tech)}")
    decisions = memory.get("architectural_decisions", [])
    if decisions:
        lines.append("Architectural decisions:")
        for d in decisions[-5:]:  # last 5
            lines.append(f"  [{d['phase']}] {d['decision']} — {d['rationale']}")
    changelog = memory.get("changelog", [])
    if changelog:
        lines.append("Recent changelog:")
        for entry in changelog[-3:]:
            lines.append(f"  - {entry.get('entry', '')}")
    lines.append("=== Build the new feature to be architecturally consistent with the above. ===")
    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _text(project_dir: Path) -> Optional[str]:
    return safe_fs.read_text_or_none(project_dir, _memory_path(project_dir))


def _write(project_dir: Path, data: Dict[str, Any]) -> None:
    safe_fs.safe_write_text(project_dir, _memory_path(project_dir), json.dumps(data, indent=2, default=str))


def _deep_merge(base: Dict, updates: Dict) -> None:
    for k, v in updates.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        elif k in base and isinstance(base[k], list) and isinstance(v, list):
            base[k].extend(v)
        else:
            base[k] = v
