"""
Fingerprint similarity matching for patch reuse.

Matches a failure fingerprint against historical patch records
with exact and fuzzy scoring.
"""

from __future__ import annotations

from dataclasses import dataclass

from aether_os.phases.p08_cicd.patch_reuse.fingerprint import FailureFingerprint

FUZZY_THRESHOLD = 0.85


def _error_type_similarity(a: str, b: str) -> float:
    """Exact match only."""
    return 1.0 if a == b else 0.0


def _stack_trace_similarity(a: str, b: str) -> float:
    """Frame overlap: |intersection| / max(|a|, |b|) using frames as tokens."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    frames_a = set(f.strip() for f in a.split("|") if f.strip())
    frames_b = set(f.strip() for f in b.split("|") if f.strip())
    if not frames_a or not frames_b:
        return 0.0
    overlap = len(frames_a & frames_b) / max(len(frames_a), len(frames_b))
    return overlap


def _target_module_similarity(a: str, b: str) -> float:
    """Exact match = 1.0; same file (first path segment) = 0.5."""
    if a == b:
        return 1.0
    file_a = a.split(":")[0] if ":" in a else a
    file_b = b.split(":")[0] if ":" in b else b
    return 0.5 if file_a == file_b else 0.0


def _fuzzy_score(fp: FailureFingerprint, record: dict) -> float:
    """Score similarity across error_type, stack_trace_pattern, target_module."""
    rec_error = str(record.get("error_type", ""))
    rec_stack = str(record.get("stack_trace_pattern", ""))
    rec_target = str(record.get("target_module", ""))

    s1 = _error_type_similarity(fp.error_type, rec_error)
    s2 = _stack_trace_similarity(fp.stack_trace_pattern, rec_stack)
    s3 = _target_module_similarity(fp.target_module, rec_target)

    return (s1 + s2 + s3) / 3.0


@dataclass
class MatchResult:
    """Result of matching a fingerprint against historical records."""

    matched: bool
    confidence: float
    patch_diff: str
    match_type: str  # "exact" | "fuzzy" | "none"


def match(
    fingerprint: FailureFingerprint,
    historical_records: list[dict],
) -> MatchResult:
    """
    Match a failure fingerprint against historical patch records.

    Args:
        fingerprint: The failure fingerprint to match.
        historical_records: List of dicts with fingerprint_hash, error_type,
            stack_trace_pattern, failing_test, target_module, patch_diff, success_rate.

    Returns:
        MatchResult with best match (exact > fuzzy > none). Fuzzy only if score > 0.85.
    """
    best: MatchResult | None = None

    for rec in historical_records:
        rec_hash = str(rec.get("fingerprint_hash", ""))
        patch_diff = str(rec.get("patch_diff", ""))

        # Exact match
        if fingerprint.fingerprint_hash == rec_hash:
            return MatchResult(
                matched=True,
                confidence=1.0,
                patch_diff=patch_diff,
                match_type="exact",
            )

        # Fuzzy match (only if no exact found yet)
        score = _fuzzy_score(fingerprint, rec)
        if score > FUZZY_THRESHOLD and (best is None or score > best.confidence):
            best = MatchResult(
                matched=True,
                confidence=round(score, 4),
                patch_diff=patch_diff,
                match_type="fuzzy",
            )

    if best:
        return best
    return MatchResult(
        matched=False,
        confidence=0.0,
        patch_diff="",
        match_type="none",
    )
