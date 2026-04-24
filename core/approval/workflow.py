"""
Aether-One Approval & Audit Workflow Core

Goal:
    Provide a simple, explainable, offline approval engine that turns
    risk labels/scores into decisions and writes audit logs to disk.

Decisions:
    - AUTO_APPLY        → safe to apply automatically
    - REQUIRE_APPROVAL  → needs explicit human confirmation
    - BLOCKED           → blocked by default; override requires reason

Risk mapping (default):
    NONE      → AUTO_APPLY
    LOW       → AUTO_APPLY
    MEDIUM    → REQUIRE_APPROVAL
    HIGH      → BLOCKED
    UNKNOWN   → BLOCKED (conservative)

Audit log:
    A JSON-lines file stored at:
        <project_path>/.aetherone_audit.log

Public API:

    decide_for_risk(risk_label: str, risk_score: float | None) -> dict

    write_audit_entry(
        project_path: str,
        file_path: str,
        action: str,
        decision: str,
        risk_label: str,
        risk_score: float | None,
        actor: str,
        reason: str | None,
        extra: dict | None = None,
    ) -> dict
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional


_DECISION_AUTO = "AUTO_APPLY"
_DECISION_REQUIRE = "REQUIRE_APPROVAL"
_DECISION_BLOCKED = "BLOCKED"


@dataclass
class ApprovalDecision:
    decision: str
    risk_label: str
    risk_score: Optional[float]
    reason: str


def decide_for_risk(risk_label: str, risk_score: Optional[float] = None) -> Dict[str, Any]:
    """
    Map a risk label/score into a decision.

    Returns:
        {
            "decision": "AUTO_APPLY" | "REQUIRE_APPROVAL" | "BLOCKED",
            "risk_label": "...",
            "risk_score": ...,
            "reason": "human-readable explanation"
        }
    """
    label = (risk_label or "UNKNOWN").upper()

    if label in ("NONE",):
        decision = _DECISION_AUTO
        reason = "No meaningful risk detected."
    elif label in ("LOW",):
        decision = _DECISION_AUTO
        reason = "Low risk; safe to auto-apply under default policy."
    elif label in ("MEDIUM",):
        decision = _DECISION_REQUIRE
        reason = "Medium risk; require explicit human approval."
    elif label in ("HIGH",):
        decision = _DECISION_BLOCKED
        reason = "High risk; blocked by default. Override only with explicit justification."
    else:
        decision = _DECISION_BLOCKED
        reason = f"Unknown risk label '{label}'; blocked by default."

    return asdict(
        ApprovalDecision(
            decision=decision,
            risk_label=label,
            risk_score=risk_score,
            reason=reason,
        )
    )


def _audit_path_for_project(project_path: str) -> str:
    """
    Resolve the audit log path for a given project root.

    Always returns an absolute path:
        <project_root>/.aetherone_audit.log
    """
    project_abs = os.path.abspath(os.path.expanduser(project_path))
    return os.path.join(project_abs, ".aetherone_audit.log")


def write_audit_entry(
    project_path: str,
    file_path: str,
    action: str,
    decision: str,
    risk_label: str,
    risk_score: Optional[float],
    actor: str,
    reason: Optional[str],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Append an audit log entry to .aetherone_audit.log.

    The entry is a single JSON line, safe for offline review and compliance.

    Returns the entry dict that was written.
    """
    project_abs = os.path.abspath(os.path.expanduser(project_path))
    file_abs = os.path.abspath(os.path.expanduser(file_path))

    now = datetime.now(timezone.utc).isoformat()

    entry: Dict[str, Any] = {
        "timestamp": now,
        "project_path": project_abs,
        "file_path": file_abs,
        "action": action,
        "decision": decision,
        "risk_label": risk_label,
        "risk_score": risk_score,
        "actor": actor,
        "reason": reason,
        "extra": extra or {},
    }

    audit_path = _audit_path_for_project(project_abs)
    os.makedirs(os.path.dirname(audit_path), exist_ok=True)

    # Append as JSONL, one entry per line.
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry

