"""
AetherOS Platform Workloop Monitor

Background task that runs every 5 minutes to:
  1. Scan recent run failures and extract failure patterns
  2. Feed patterns to LLM for diagnosis and suggested fixes
  3. Apply safe auto-fixes (env vars, phase config, model settings)
  4. Emit platform health events visible in the dashboard

Start via:   asyncio.create_task(workloop_monitor.start())
Stop via:    workloop_monitor.stop()
Status via:  workloop_monitor.get_status()
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = int(os.environ.get("WORKLOOP_INTERVAL", "300"))  # 5 min default
_MAX_RECENT_RUNS = int(os.environ.get("WORKLOOP_LOOKBACK_RUNS", "20"))
_AUTO_FIX_ENABLED = os.environ.get("WORKLOOP_AUTO_FIX", "true").lower() == "true"


# ── Module-level state ────────────────────────────────────────────────────────

class WorkloopMonitor:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_check: float = 0.0
        self._last_findings: List[Dict[str, Any]] = []
        self._fix_log: List[Dict[str, Any]] = []
        self._check_count = 0
        self._error_count = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> asyncio.Task:
        if self._running:
            return self._task  # type: ignore[return-value]
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="workloop_monitor")
        logger.info("WorkloopMonitor started (interval=%ds)", _INTERVAL_SECONDS)
        return self._task

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("WorkloopMonitor stopped")

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "last_check_at": self._last_check,
            "check_count": self._check_count,
            "error_count": self._error_count,
            "interval_seconds": _INTERVAL_SECONDS,
            "auto_fix_enabled": _AUTO_FIX_ENABLED,
            "last_findings": self._last_findings[-10:],
            "fix_log": self._fix_log[-20:],
        }

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._run_check()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._error_count += 1
                logger.warning("WorkloopMonitor check failed: %s", exc)
            # Wait for next interval
            try:
                await asyncio.sleep(_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _run_check(self) -> None:
        self._check_count += 1
        self._last_check = time.time()
        logger.info("WorkloopMonitor: starting check #%d", self._check_count)

        # Step 1: Collect recent run data
        runs = await self._fetch_recent_runs()
        if not runs:
            logger.info("WorkloopMonitor: no recent runs to analyse")
            return

        # Step 2: Extract failure patterns
        patterns = self._extract_patterns(runs)
        if not patterns["has_issues"]:
            logger.info("WorkloopMonitor: no issues detected in last %d runs", len(runs))
            self._last_findings = []
            return

        # Step 3: Diagnose via LLM
        findings = await self._diagnose(patterns)
        self._last_findings = findings
        logger.info("WorkloopMonitor: %d findings, applying auto-fixes", len(findings))

        # Step 4: Apply safe auto-fixes
        if _AUTO_FIX_ENABLED:
            for finding in findings:
                await self._maybe_apply_fix(finding)

        # Step 5: Emit platform health event
        await self._emit_health_event(patterns, findings)

    # ── Data collection ───────────────────────────────────────────────────────

    async def _fetch_recent_runs(self) -> List[Dict[str, Any]]:
        try:
            from aether_os.core.db import get_session_factory
            from aether_os.core.models import Run
            from sqlalchemy import select, desc

            async with get_session_factory()() as session:
                stmt = (
                    select(Run)
                    .order_by(desc(Run.started_at))
                    .limit(_MAX_RECENT_RUNS)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()
                return [
                    {
                        "id": str(r.id),
                        "status": r.status,
                        "current_phase": r.current_phase or "",
                        "message": r.message or "",
                        "started_at": r.started_at,
                        "finished_at": r.finished_at,
                        "domain": r.domain or "",
                    }
                    for r in rows
                ]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("WorkloopMonitor: failed to fetch runs: %s", exc)
            return []

    # ── Pattern extraction ────────────────────────────────────────────────────

    def _extract_patterns(self, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        statuses = Counter(r["status"] for r in runs)
        failed = [r for r in runs if r["status"] in ("failed", "error")]
        stuck_phases: Counter = Counter()
        error_messages: List[str] = []

        for r in failed:
            phase = r.get("current_phase", "unknown")
            if phase:
                stuck_phases[phase] += 1
            msg = r.get("message", "")
            if msg and len(msg) > 10:
                error_messages.append(msg[:300])

        # Detect runs that have been "running" for >30 minutes (hung)
        now = time.time()
        hung_runs = [
            r for r in runs
            if r["status"] == "running"
            and r["started_at"]
            and (now - r["started_at"]) > 1800
        ]

        has_issues = bool(failed or hung_runs or statuses.get("failed", 0) > 0)

        return {
            "has_issues": has_issues,
            "total_runs": len(runs),
            "statuses": dict(statuses),
            "failed_count": len(failed),
            "hung_count": len(hung_runs),
            "stuck_phases": dict(stuck_phases.most_common(5)),
            "sample_errors": error_messages[:5],
            "failure_rate": len(failed) / max(len(runs), 1),
        }

    # ── LLM diagnosis ─────────────────────────────────────────────────────────

    async def _diagnose(self, patterns: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            from aether_os.core.model_router import get_router
            router = get_router()

            prompt = f"""You are an AetherOS platform health analyzer. Analyse these pipeline failure patterns and return a JSON array of findings.

PATTERNS:
- Total recent runs: {patterns['total_runs']}
- Failed: {patterns['failed_count']} ({patterns['failure_rate']:.0%})
- Hung (running >30min): {patterns['hung_count']}
- Phases where failures occur most: {patterns['stuck_phases']}
- Sample error messages: {patterns['sample_errors']}

Return a JSON array where each element has:
- "severity": "critical" | "warning" | "info"
- "phase": which pipeline phase is affected (or "platform" if system-level)
- "root_cause": 1-sentence diagnosis
- "fix_type": "env_var" | "restart" | "config" | "none"
- "fix_action": specific action string (e.g. "set BEDROCK_ENABLED=true") or null
- "auto_fixable": true/false (only true for clearly safe, reversible actions)

Return ONLY the JSON array, no markdown."""

            result = await router.call(prompt, task_type="summarize", max_tokens=1024)
            text = result[0] if isinstance(result, (list, tuple)) else result

            import json, re
            # Strip markdown fences if any
            text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
            findings = json.loads(text)
            if not isinstance(findings, list):
                findings = [findings]
            return findings
        except Exception as exc:
            logger.warning("WorkloopMonitor: LLM diagnosis failed: %s", exc)
            # Return minimal synthetic finding on LLM failure
            return [{
                "severity": "warning",
                "phase": "platform",
                "root_cause": f"Workloop LLM diagnosis failed: {exc}",
                "fix_type": "none",
                "fix_action": None,
                "auto_fixable": False,
            }]

    # ── Safe auto-fix application ─────────────────────────────────────────────

    _SAFE_ENV_VARS = {
        # Only allow setting these env vars automatically — never secrets
        "BEDROCK_ENABLED", "BEDROCK_MODEL_HEAVY", "BEDROCK_MODEL_LIGHT",
        "PRIMARY_LLM", "OLLAMA_TIMEOUT", "COUNCIL_STRICT_MODE",
        "WORKLOOP_INTERVAL", "PIPELINE_PHASE_TIMEOUT",
    }

    async def _maybe_apply_fix(self, finding: Dict[str, Any]) -> None:
        if not finding.get("auto_fixable"):
            return
        fix_type = finding.get("fix_type", "none")
        fix_action = finding.get("fix_action") or ""

        if fix_type == "env_var" and "=" in fix_action:
            key, _, val = fix_action.partition("=")
            key = key.strip().upper()
            val = val.strip()
            if key in self._SAFE_ENV_VARS:
                old = os.environ.get(key, "<unset>")
                os.environ[key] = val
                record = {
                    "at": time.time(),
                    "type": "env_var",
                    "key": key,
                    "old": old,
                    "new": val,
                    "reason": finding.get("root_cause", ""),
                }
                self._fix_log.append(record)
                logger.info(
                    "WorkloopMonitor: auto-fixed %s: %s → %s (%s)",
                    key, old, val, finding.get("root_cause", ""),
                )
        elif fix_type == "restart":
            # Never auto-restart — just log the recommendation
            self._fix_log.append({
                "at": time.time(),
                "type": "recommendation",
                "action": fix_action,
                "reason": finding.get("root_cause", ""),
            })

    # ── Health event emission ─────────────────────────────────────────────────

    async def _emit_health_event(
        self,
        patterns: Dict[str, Any],
        findings: List[Dict[str, Any]],
    ) -> None:
        try:
            from aether_os.core.pipeline_state import publish_event
            await publish_event("__platform__", {
                "type": "workloop_health",
                "timestamp": time.time(),
                "patterns": patterns,
                "findings": findings,
                "fix_count": len([f for f in findings if f.get("auto_fixable")]),
            })
        except Exception:
            pass  # Non-fatal — event emission is best-effort


# ── Singleton ─────────────────────────────────────────────────────────────────

_monitor: Optional[WorkloopMonitor] = None


def get_workloop_monitor() -> WorkloopMonitor:
    global _monitor
    if _monitor is None:
        _monitor = WorkloopMonitor()
    return _monitor
