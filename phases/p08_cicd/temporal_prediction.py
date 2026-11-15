"""
Aether-One Temporal Prediction & Risk Trends

Purpose
-------
Analyze telemetry over time and estimate:

- Which files / modules are becoming more or less risky
- Temporal trends (rising / stable / falling risk)
- Simple forecasts of future risk levels for each file glob

This module is built on top of the telemetry spine and is intended to
feed:

- Temporal risk views in the dashboard
- "Run tests here first" planners
- Pre-emptive policy tightening
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .telemetry_spine import (
    TelemetryEvent,
    get_default_spine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_project_path(project_path: str) -> str:
    return os.path.abspath(os.path.expanduser(project_path))


def _parse_ts(ts: str) -> float:
    """
    Convert ISO8601 timestamp to POSIX timestamp (seconds).
    """
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception as e:
        logger.debug("temporal_prediction: could not parse timestamp %r: %s", ts, e)
        return 0.0


def _normalize_risk_level(data: Dict[str, Any]) -> Optional[str]:
    """
    Extract a normalized risk level from a telemetry event's data payload.
    """
    for key in ("risk_level", "risk_label", "effective_risk"):
        if key in data and data[key]:
            return str(data[key]).upper()
    return None


def _extract_file_path(ev: TelemetryEvent) -> Optional[str]:
    """
    Try to extract a relevant file path from event data (if any).
    """
    data = ev.data if isinstance(ev.data, dict) else {}
    for key in ("file", "file_path", "path", "target_file"):
        if key in data and data[key]:
            return str(data[key])
    return None


def _path_to_glob(path: str) -> str:
    """
    Simple heuristic turning a concrete file path into a glob key.
    """
    path = path.replace("\\", "/")
    parts = path.split("/")

    if len(parts) <= 2:
        return path

    if parts[-1].endswith(".py"):
        return "/".join(parts[:-1]) + "/*.py"
    return "/".join(parts[:-1]) + "/*"


def _severity_score(sev: str) -> int:
    sev = (sev or "").upper()
    mapping = {
        "DEBUG": 0,
        "INFO": 1,
        "WARN": 2,
        "WARNING": 2,
        "ERROR": 3,
        "CRITICAL": 4,
    }
    return mapping.get(sev, 0)


def _risk_score(risk: Optional[str]) -> int:
    if not risk:
        return 0
    r = risk.upper()
    mapping = {
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "CRITICAL": 4,
    }
    return mapping.get(r, 0)


def _score_to_level(score: float) -> str:
    """
    Map numeric score back to a qualitative risk level.
    Rough scale:
        0-1  -> LOW
        1-2  -> MEDIUM
        2-3  -> HIGH
        >=3  -> CRITICAL
    """
    if score < 1.0:
        return "LOW"
    if score < 2.0:
        return "MEDIUM"
    if score < 3.0:
        return "HIGH"
    return "CRITICAL"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TemporalPredictionConfig:
    """
    Configuration for temporal prediction.
    """

    project_path: str
    max_events: int = 5000
    # fraction of oldest events to treat as "baseline"
    baseline_fraction: float = 0.5
    # minimal number of samples required for a forecast
    min_samples: int = 5


@dataclass
class FileRiskSample:
    """
    Single time-stamped risk sample for a file glob.
    """

    ts: str
    timestamp: float
    file_glob: str
    severity: str
    risk_level: Optional[str]
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FileRiskForecast:
    """
    Forecast for a single file glob.
    """

    file_glob: str
    sample_count: int
    baseline_score: float
    recent_score: float
    forecast_score: float
    current_level: str
    forecast_level: str
    trend: str  # "rising", "falling", "stable"
    last_observed_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TemporalPredictionResult:
    """
    Aggregated result for a prediction run.
    """

    project_path: str
    generated_at: str
    forecasts: List[FileRiskForecast]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _collect_samples(cfg: TemporalPredictionConfig) -> Dict[str, List[FileRiskSample]]:
    """
    Read telemetry events and build risk samples per file glob.
    """
    project_abs = _normalize_project_path(cfg.project_path)
    spine = get_default_spine(project_abs)

    # Load events (most recent first, then we reverse to chronological)
    events = spine.query_recent(limit=cfg.max_events)
    events = sorted(events, key=lambda e: _parse_ts(e.ts) or 0.0)

    by_glob: Dict[str, List[FileRiskSample]] = {}

    for ev in events:
        file_path = _extract_file_path(ev)
        if not file_path:
            continue

        file_glob = _path_to_glob(file_path)
        ts_num = _parse_ts(ev.ts)
        sev = ev.severity or "INFO"
        risk = _normalize_risk_level(ev.data if isinstance(ev.data, dict) else {})

        score = float(_severity_score(sev) + _risk_score(risk))

        sample = FileRiskSample(
            ts=ev.ts,
            timestamp=ts_num,
            file_glob=file_glob,
            severity=sev,
            risk_level=risk,
            score=score,
        )
        by_glob.setdefault(file_glob, []).append(sample)

    return by_glob


def _compute_forecast_for_samples(
    samples: List[FileRiskSample],
) -> Optional[FileRiskForecast]:
    """
    Given samples for a single file_glob, compute trend + forecast.
    """
    if not samples:
        return None

    # Require minimal sample count for stability
    n = len(samples)
    if n < 2:
        return None

    scores = [s.score for s in samples]

    # Baseline vs recent split
    split_idx = max(1, int(math.floor(n * 0.5)))
    baseline_scores = scores[:split_idx]
    recent_scores = scores[split_idx:]

    baseline = float(sum(baseline_scores) / len(baseline_scores))
    recent = float(sum(recent_scores) / len(recent_scores))

    # Simple trend
    delta = recent - baseline
    if delta > 0.3:
        trend = "rising"
    elif delta < -0.3:
        trend = "falling"
    else:
        trend = "stable"

    # Simple forecast: push recent a bit further along delta
    forecast_score = recent + (delta * 0.5)
    current_score = scores[-1]
    current_level = _score_to_level(current_score)
    forecast_level = _score_to_level(forecast_score)
    last_ts = samples[-1].ts

    return FileRiskForecast(
        file_glob=samples[-1].file_glob,
        sample_count=n,
        baseline_score=baseline,
        recent_score=recent,
        forecast_score=forecast_score,
        current_level=current_level,
        forecast_level=forecast_level,
        trend=trend,
        last_observed_at=last_ts,
    )


def analyze_temporal_risk(cfg: TemporalPredictionConfig) -> TemporalPredictionResult:
    """
    High-level entrypoint:

    - Collect risk samples from telemetry per file glob
    - Compute simple trend + forecast for each
    - Return an aggregated prediction result
    """
    project_abs = _normalize_project_path(cfg.project_path)
    generated_at = datetime.now(timezone.utc).isoformat()

    by_glob = _collect_samples(cfg)

    forecasts: List[FileRiskForecast] = []
    for file_glob, samples in by_glob.items():
        if len(samples) < cfg.min_samples:
            continue
        fc = _compute_forecast_for_samples(samples)
        if fc is not None:
            forecasts.append(fc)

    # Sort by descending forecast_score (most risky first)
    forecasts.sort(key=lambda f: f.forecast_score, reverse=True)

    return TemporalPredictionResult(
        project_path=project_abs,
        generated_at=generated_at,
        forecasts=forecasts,
    )


def forecast_for_file_glob(
    project_path: str,
    file_glob: str,
    *,
    max_events: int = 5000,
    min_samples: int = 3,
) -> Optional[FileRiskForecast]:
    """
    Convenience function: get temporal forecast for a single file glob.
    """
    cfg = TemporalPredictionConfig(
        project_path=project_path,
        max_events=max_events,
        min_samples=min_samples,
    )
    by_glob = _collect_samples(cfg)
    samples = by_glob.get(file_glob)
    if not samples or len(samples) < min_samples:
        return None
    return _compute_forecast_for_samples(samples)

