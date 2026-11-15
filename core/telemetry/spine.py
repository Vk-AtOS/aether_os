"""
Aether-One Telemetry Spine

Purpose
-------
Provide a central, structured telemetry pipeline for Aether-One:

- Records events from agents, orchestrator, sandbox, CI, etc.
- Writes append-only JSONL logs per project:
    .aetherone_telemetry.log

- Designed to power:
    - Temporal risk analysis
    - Safety pattern mining
    - Quantum/ensemble optimiser feedback
    - Dashboards and reports

This module is self-contained and safe to import from any component.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths & utilities
# ---------------------------------------------------------------------------


def _normalize_project_path(project_path: str) -> str:
    return os.path.abspath(os.path.expanduser(project_path))


def telemetry_log_path(project_path: str) -> str:
    """
    Path to the project-level telemetry JSONL log.
    """
    project_abs = _normalize_project_path(project_path)
    return os.path.join(project_abs, ".aetherone_telemetry.log")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TelemetryEvent:
    """
    Single telemetry event.

    Attributes:
        id:            UUID for the event.
        ts:            ISO8601 timestamp in UTC.
        project_path:  Absolute project path.
        session_id:    Logical session identifier (optional).
        source:        Component that emitted the event
                       e.g. "fix_engine", "sandbox", "ci_agent", "router"

        category:      High-level category, e.g. "code_fix", "test_run", "risk", "ci", "system"
        name:          Event name, e.g. "fix_applied", "test_failed"

        severity:      "INFO", "WARN", "ERROR", "DEBUG", etc.

        data:          Arbitrary JSON-serializable payload with details.
    """

    id: str
    ts: str
    project_path: str
    session_id: Optional[str]
    source: str
    category: str
    name: str
    severity: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TelemetryConfig:
    """
    Configuration for the TelemetrySpine.
    """

    project_path: str
    enabled: bool = True
    max_log_size_bytes: int = 500 * 1024 * 1024  # 500 MB
    rotate_when_full: bool = True
    # Future: remote sinks, sampling rates, PII filters, etc.


# ---------------------------------------------------------------------------
# Telemetry spine implementation
# ---------------------------------------------------------------------------


class TelemetrySpine:
    """
    Central telemetry manager.

    Thread-safe for concurrent writes from multiple threads in a single process.

    Usage:

        spine = TelemetrySpine(TelemetryConfig(project_path="."))
        spine.record_event(
            source="fix_engine",
            category="code_fix",
            name="fix_applied",
            severity="INFO",
            data={"file": "aetherone/api.py", "risk": "LOW"},
        )

    There is also a global default singleton via get_default_spine().
    """

    def __init__(self, config: TelemetryConfig) -> None:
        self._config = config
        self._project_abs = _normalize_project_path(config.project_path)
        self._log_path = telemetry_log_path(self._project_abs)
        self._lock = threading.Lock()
        self._session_id: Optional[str] = None

        # Ensure project directory exists
        if not os.path.isdir(self._project_abs):
            raise ValueError(f"Project path is not a directory: {self._project_abs}")

    # --- Session handling ---------------------------------------------------

    def start_session(self, session_id: Optional[str] = None) -> str:
        """
        Start or register a logical telemetry session.

        If session_id is None, a new UUID will be generated.

        Returns the active session_id.
        """
        if session_id is None:
            session_id = str(uuid.uuid4())
        self._session_id = session_id

        self.record_event(
            source="telemetry",
            category="system",
            name="session_started",
            severity="INFO",
            data={"session_id": session_id},
        )
        return session_id

    def end_session(self) -> None:
        """
        End the current telemetry session.
        """
        if self._session_id:
            self.record_event(
                source="telemetry",
                category="system",
                name="session_ended",
                severity="INFO",
                data={"session_id": self._session_id},
            )
        self._session_id = None

    # --- Core recording -----------------------------------------------------

    def record_event(
        self,
        *,
        source: str,
        category: str,
        name: str,
        severity: str = "INFO",
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> TelemetryEvent:
        """
        Record a telemetry event and append it to the JSONL log.

        Returns the TelemetryEvent object (for in-memory use).
        """
        if not self._config.enabled:
            # Emit a no-op event (could also return None, but staying consistent)
            ev = TelemetryEvent(
                id=str(uuid.uuid4()),
                ts=_utc_now_iso(),
                project_path=self._project_abs,
                session_id=session_id or self._session_id,
                source=source,
                category=category,
                name=name,
                severity=severity,
                data=data or {},
            )
            return ev

        ev = TelemetryEvent(
            id=str(uuid.uuid4()),
            ts=_utc_now_iso(),
            project_path=self._project_abs,
            session_id=session_id or self._session_id,
            source=source,
            category=category,
            name=name,
            severity=severity,
            data=data or {},
        )

        line = json.dumps(ev.to_dict(), ensure_ascii=False)

        with self._lock:
            # Rotate if necessary
            if self._config.rotate_when_full:
                self._rotate_if_oversized_unlocked()

            # Append line
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

        return ev

    def _rotate_if_oversized_unlocked(self) -> None:
        """
        Rotate telemetry log if it exceeds max_log_size_bytes.

        Called with self._lock held.
        """
        if not os.path.exists(self._log_path):
            return

        try:
            size = os.path.getsize(self._log_path)
        except OSError:
            return

        if size <= self._config.max_log_size_bytes:
            return

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rotated = f"{self._log_path}.{ts}.bak"
        try:
            os.rename(self._log_path, rotated)
        except OSError as e:
            # If rename fails, we simply keep the existing file
            logger.warning("telemetry/spine: log rotation failed for %s: %s", self._log_path, e)

    # --- Query helpers ------------------------------------------------------

    def _iter_events(self) -> Iterable[TelemetryEvent]:
        """
        Internal generator to iterate over events in the current telemetry log.

        This reads only the *current* log file, not rotated ones.
        """
        if not os.path.exists(self._log_path):
            return

        with open(self._log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    # Basic validation
                    if not isinstance(obj, dict):
                        continue
                    # Convert dict -> TelemetryEvent
                    yield TelemetryEvent(
                        id=str(obj.get("id", "")),
                        ts=str(obj.get("ts", "")),
                        project_path=str(obj.get("project_path", "")),
                        session_id=obj.get("session_id"),
                        source=str(obj.get("source", "")),
                        category=str(obj.get("category", "")),
                        name=str(obj.get("name", "")),
                        severity=str(obj.get("severity", "")),
                        data=obj.get("data") or {},
                    )
                except Exception as e:
                    logger.warning("telemetry spine: could not parse event line: %s", e)
                    continue

    def query_recent(
        self,
        *,
        limit: int = 100,
        category: Optional[str] = None,
        source: Optional[str] = None,
        severity_at_least: Optional[str] = None,
    ) -> List[TelemetryEvent]:
        """
        Return up to `limit` most recent events, optionally filtered.

        NOTE: This is a simple implementation that reads the file in order
        and takes the tail. It is intended for diagnostics and small queries,
        not massive analytics.
        """
        events = list(self._iter_events())

        # Filter
        def _sev_rank(s: str) -> int:
            s = s.upper()
            ranking = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40, "CRITICAL": 50}
            return ranking.get(s, 0)

        out: List[TelemetryEvent] = []
        min_rank = _sev_rank(severity_at_least) if severity_at_least else None

        for ev in reversed(events):
            if category and ev.category != category:
                continue
            if source and ev.source != source:
                continue
            if min_rank is not None and _sev_rank(ev.severity) < min_rank:
                continue
            out.append(ev)
            if len(out) >= limit:
                break

        return list(reversed(out))

    def query_by_type(
        self,
        *,
        name: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 200,
    ) -> List[TelemetryEvent]:
        """
        Query events by name/category.
        """
        events = list(self._iter_events())
        out: List[TelemetryEvent] = []

        for ev in events:
            if category and ev.category != category:
                continue
            if name and ev.name != name:
                continue
            out.append(ev)
            if len(out) >= limit:
                break

        return out


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_default_spine: Optional[TelemetrySpine] = None


def get_default_spine(project_path: str) -> TelemetrySpine:
    """
    Get (or create) a process-level shared TelemetrySpine for the given project.

    If a spine already exists with a different project path, this will
    replace it with a new one.
    """
    global _default_spine
    project_abs = _normalize_project_path(project_path)

    if _default_spine is not None:
        # If same project, just reuse
        if _default_spine._project_abs == project_abs:
            return _default_spine

    cfg = TelemetryConfig(project_path=project_abs)
    _default_spine = TelemetrySpine(cfg)
    return _default_spine


def record_event_for_project(
    project_path: str,
    *,
    source: str,
    category: str,
    name: str,
    severity: str = "INFO",
    data: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> TelemetryEvent:
    """
    One-shot helper: acquire default spine for project, record event.
    """
    spine = get_default_spine(project_path)
    return spine.record_event(
        source=source,
        category=category,
        name=name,
        severity=severity,
        data=data,
        session_id=session_id,
    )

