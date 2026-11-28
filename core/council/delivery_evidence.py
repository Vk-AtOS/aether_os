"""Evidence the DeliveryCouncil judges (KAN-275).

The council used to see only {stage: status}. A stage that "completed" with failing tests, a failed s07 probe or
an s05 blocker looked identical to a clean one, so the LLM could not tell a good delivery from a bad one. This
builds a bounded, deterministic summary from the stage results (and optional run context): failed stages with
the reason, test counts, the s07 probe verdict, the s05 static-invariant and security findings and any
production-readiness findings, whatever is present.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

_MAX_ITEMS = 5          # findings listed per category
_MAX_TEXT = 200         # characters per finding
_MAX_CHARS = 3500       # whole summary


def _clip(value: Any) -> str:
    return str(value)[:_MAX_TEXT]


def _meta(phases_results: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    for stage, r in phases_results.items():
        if stage.startswith(prefix) and isinstance(r, dict):
            return r.get("metadata") or {}
    return {}


def build_delivery_evidence(
    phases_results: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    max_chars: int = _MAX_CHARS,
) -> str:
    """JSON summary (at most max_chars) of what the pipeline actually produced, for the council prompt."""
    ctx = context or {}
    ev: Dict[str, Any] = {}

    bad: List[Dict[str, str]] = []
    for stage, r in phases_results.items():
        if not isinstance(r, dict):
            continue
        status = r.get("status")
        if status in ("failed", "timeout", "escalated", "skipped"):
            reason = r.get("error") or "; ".join(str(i) for i in (r.get("issues") or [])[:2])
            bad.append({"stage": stage, "status": str(status), "reason": _clip(reason or "no reason given")})
    ev["failed_or_skipped_stages"] = bad[:_MAX_ITEMS * 2]

    s06 = _meta(phases_results, "s06")
    gate = s06.get("gate") or {}
    total = s06.get("total_tests", gate.get("tests_ran"))
    if total is not None:
        passed = s06.get("passed_tests")
        failed = gate.get("tests_failed", (total - passed) if isinstance(passed, int) and isinstance(total, int) else None)
        ev["tests"] = {"total": total, "passed": passed, "failed": failed,
                       "failed_but_did_not_block": bool(gate.get("tests_failed_but_did_not_block"))}

    s07 = _meta(phases_results, "s07")
    probe = s07.get("quality_probe") or ctx.get("quality_probe") or {}
    if probe or "healing_passed" in s07:
        ev["s07_probe"] = {
            "healing_passed": s07.get("healing_passed"),
            "status": s07.get("status") or (s07.get("self_healing_report") or {}).get("status"),
            "probe_passed": probe.get("passed", probe.get("all_passed")),
            "failed_layers": [_clip(x) for x in (probe.get("failed_layers") or probe.get("failures") or [])[:_MAX_ITEMS]],
        }

    s05 = _meta(phases_results, "s05")
    findings = [_clip(x) for x in (s05.get("blocking_findings") or [])[:_MAX_ITEMS]]
    vr = s05.get("verification_report") or {}
    if findings or vr:
        ev["security_and_invariants"] = {
            "blocking_findings": findings,
            "static_invariants_verdict": vr.get("overall_verdict"),
            "static_invariants_failed": len(vr.get("invariants_failed") or []) if isinstance(vr, dict) else None,
        }

    readiness = ctx.get("production_readiness") or _meta(phases_results, "s09").get("production_readiness")
    if readiness:
        ev["production_readiness"] = _clip(json.dumps(readiness, default=str))

    text = json.dumps(ev, default=str)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + '..."(truncated)"'
    return text
