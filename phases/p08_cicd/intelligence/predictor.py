from __future__ import annotations
import math
import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DECAY_HALF_LIFE_DAYS = 14
# Score halves every 14 days of inactivity
MIN_OCCURRENCES = 2
# Need at least 2 to predict
RECURRENCE_THRESHOLD = 0.3
# Min score to flag as likely


@dataclass
class FailureRecord:
    error_type: str
    language: str
    fingerprint: str
    occurred_at: datetime
    repo_name: str = ""
    was_resolved: bool = False


@dataclass
class PredictionResult:
    error_type: str
    language: str
    recurrence_score: float
    # 0.0-1.0, higher = more likely to recur
    predicted_severity: str
    # "low", "medium", "high", "critical"
    occurrence_count: int
    last_seen: Optional[datetime] = None
    contributing_repos: list[str] = field(default_factory=list)
    is_likely_to_recur: bool = False


class FailurePredictor:
    """
    Predicts failure recurrence using
    frequency analysis with time decay.
    """

    def __init__(self):
        # {error_type: [FailureRecord]}
        self._records: dict[str, list[FailureRecord]] = defaultdict(list)

    def record_failure(
        self,
        error_type: str,
        language: str,
        fingerprint: str,
        repo_name: str = "",
        occurred_at: Optional[datetime] = None,
        was_resolved: bool = False
    ) -> None:
        """Record a failure occurrence."""
        ts = occurred_at or datetime.now(timezone.utc)
        record = FailureRecord(
            error_type=error_type,
            language=language,
            fingerprint=fingerprint,
            occurred_at=ts,
            repo_name=repo_name,
            was_resolved=was_resolved
        )
        self._records[error_type].append(record)

    def _decay_score(
        self,
        occurred_at: datetime,
        now: Optional[datetime] = None
    ) -> float:
        """
        Exponential decay score.
        Recent events score near 1.0,
        older events score lower.
        """
        now = now or datetime.now(timezone.utc)
        days_ago = (now - occurred_at).total_seconds() / 86400
        half_lives = days_ago / DECAY_HALF_LIFE_DAYS
        return math.pow(0.5, half_lives)

    def predict(
        self,
        error_type: str,
        now: Optional[datetime] = None
    ) -> Optional[PredictionResult]:
        """
        Predict recurrence for an error type.
        Returns None if insufficient data.
        """
        records = self._records.get(error_type, [])

        if len(records) < MIN_OCCURRENCES:
            return None

        now = now or datetime.now(timezone.utc)

        # Sum decay scores
        score = sum(
            self._decay_score(r.occurred_at, now)
            for r in records
        )

        # Normalize to 0-1
        # Score of MIN_OCCURRENCES = 0.5
        normalized = score / (score + MIN_OCCURRENCES)

        # Determine severity
        count = len(records)
        if normalized >= 0.8 or count >= 10:
            severity = "critical"
        elif normalized >= 0.6 or count >= 5:
            severity = "high"
        elif normalized >= 0.4 or count >= 3:
            severity = "medium"
        else:
            severity = "low"

        repos = list({
            r.repo_name for r in records
            if r.repo_name
        })

        last_seen = max(r.occurred_at for r in records)

        return PredictionResult(
            error_type=error_type,
            language=records[-1].language,
            recurrence_score=round(normalized, 4),
            predicted_severity=severity,
            occurrence_count=count,
            last_seen=last_seen,
            contributing_repos=repos,
            is_likely_to_recur=(normalized >= RECURRENCE_THRESHOLD)
        )

    def predict_all(
        self,
        now: Optional[datetime] = None
    ) -> list[PredictionResult]:
        """
        Predict for all known error types.
        Returns sorted by recurrence_score desc.
        """
        results = []
        for error_type in self._records:
            r = self.predict(error_type, now=now)
            if r:
                results.append(r)
        results.sort(
            key=lambda x: x.recurrence_score,
            reverse=True
        )
        return results

    def score_log_snippet(
        self,
        log_content: str
    ) -> dict:
        """
        Score a log snippet for predicted
        severity based on known patterns.
        Returns dict with matches + severity.
        """
        matches = []
        for error_type, records in self._records.items():
            if error_type.lower() in log_content.lower():
                prediction = self.predict(error_type)
                if prediction:
                    matches.append(prediction)

        if not matches:
            return {
                "severity": "unknown",
                "score": 0.0,
                "matches": []
            }

        top = max(
            matches,
            key=lambda x: x.recurrence_score
        )
        return {
            "severity": top.predicted_severity,
            "score": top.recurrence_score,
            "matches": [
                {
                    "error_type": m.error_type,
                    "score": m.recurrence_score,
                    "severity": m.predicted_severity
                }
                for m in matches
            ]
        }

    def clear(self) -> None:
        """Clear all records."""
        self._records.clear()

    @property
    def known_error_types(self) -> list[str]:
        return list(self._records.keys())


# Module-level singleton
PREDICTOR = FailurePredictor()
