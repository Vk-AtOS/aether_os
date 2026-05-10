"""
AetherOS — Project Living Memory (D6)

Creates and maintains .aetheros/project_memory.json in each generated
project directory. Called by the factory pipeline after each phase
completes and at final pipeline completion.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    mem_file = _memory_path(project_dir)
    mem_file.parent.mkdir(parents=True, exist_ok=True)

    if mem_file.exists():
        try:
            return json.loads(mem_file.read_text())
        except Exception:
            pass

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
    _write(mem_file, memory)
    return memory


def update_memory(project_dir: Path, updates: Dict[str, Any]) -> None:
    """Merge updates into the existing project memory."""
    mem_file = _memory_path(project_dir)
    if not mem_file.exists():
        return
    try:
        memory = json.loads(mem_file.read_text())
        _deep_merge(memory, updates)
        _write(mem_file, memory)
    except Exception as exc:
        logger.debug("update_memory failed: %s", exc)


def add_architectural_decision(
    project_dir: Path,
    *,
    phase: str,
    decision: str,
    rationale: str,
) -> None:
    mem_file = _memory_path(project_dir)
    if not mem_file.exists():
        return
    try:
        memory = json.loads(mem_file.read_text())
        memory.setdefault("architectural_decisions", []).append({
            "phase": phase,
            "decision": decision,
            "rationale": rationale,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })
        _write(mem_file, memory)
    except Exception as exc:
        logger.debug("add_architectural_decision failed: %s", exc)


def add_changelog_entry(
    project_dir: Path,
    entry: str,
    author: str = "system",
) -> None:
    mem_file = _memory_path(project_dir)
    if not mem_file.exists():
        return
    try:
        memory = json.loads(mem_file.read_text())
        memory.setdefault("changelog", []).append({
            "author": author,
            "entry": entry,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _write(mem_file, memory)
    except Exception as exc:
        logger.debug("add_changelog_entry failed: %s", exc)


def read_memory(project_dir: Path) -> Optional[Dict[str, Any]]:
    mem_file = _memory_path(project_dir)
    if not mem_file.exists():
        return None
    try:
        return json.loads(mem_file.read_text())
    except Exception:
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

def _write(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _deep_merge(base: Dict, updates: Dict) -> None:
    for k, v in updates.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        elif k in base and isinstance(base[k], list) and isinstance(v, list):
            base[k].extend(v)
        else:
            base[k] = v
