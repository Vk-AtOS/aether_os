"""
Failure fingerprinting for patch reuse.

Builds deterministic fingerprints from root cause candidates and parsed CI logs
for matching known failures and reusing patches.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from src.dfle.log_parser import ParsedLog, StackTrace
from src.dfle.localizer import RootCauseCandidate


def _stack_trace_pattern(trace: StackTrace) -> str:
    """Canonical pattern: ordered sequence of filename:line:function."""
    parts = [
        f"{f.filename}:{f.line}:{f.function}"
        for f in trace.frames
    ]
    return "|".join(parts)


def _failing_test(parsed_log: ParsedLog, candidate: RootCauseCandidate) -> str:
    """Primary failing test identifier."""
    if parsed_log.test_names:
        return parsed_log.test_names[0]
    if candidate.affected_tests:
        return candidate.affected_tests[0]
    trace = parsed_log.primary_trace
    if trace and trace.frames:
        top = trace.frames[0]
        return f"{top.filename}:{top.line}:{top.function}"
    return ""


def _canonical_payload(
    error_type: str,
    stack_trace_pattern: str,
    failing_test: str,
    target_module: str,
) -> str:
    """Deterministic string for hashing. Fields separated by newline."""
    return "\n".join([
        error_type,
        stack_trace_pattern,
        failing_test,
        target_module,
    ])


def _fingerprint_hash(payload: str) -> str:
    """SHA256 hash of payload, hex-encoded."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class FailureFingerprint:
    """Deterministic fingerprint of a CI failure for patch reuse matching."""

    error_type: str
    stack_trace_pattern: str
    failing_test: str
    target_module: str
    fingerprint_hash: str

    def to_dict(self) -> dict:
        """Serialize for PostgreSQL storage."""
        return {
            "error_type": self.error_type,
            "stack_trace_pattern": self.stack_trace_pattern,
            "failing_test": self.failing_test,
            "target_module": self.target_module,
            "fingerprint_hash": self.fingerprint_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FailureFingerprint:
        """Deserialize from dict."""
        return cls(
            error_type=str(data.get("error_type", "")),
            stack_trace_pattern=str(data.get("stack_trace_pattern", "")),
            failing_test=str(data.get("failing_test", "")),
            target_module=str(data.get("target_module", "")),
            fingerprint_hash=str(data.get("fingerprint_hash", "")),
        )


def build_fingerprint(
    candidate: RootCauseCandidate,
    parsed_log: ParsedLog,
) -> FailureFingerprint:
    """
    Build a deterministic failure fingerprint from a root cause candidate and parsed log.

    Args:
        candidate: Top-ranked root cause candidate from localizer.localize().
        parsed_log: Parsed CI log from log_parser.parse_log().

    Returns:
        FailureFingerprint with deterministic fingerprint_hash.
    """
    trace = parsed_log.primary_trace
    error_type = trace.exception_type if trace else ""
    stack_trace_pattern = _stack_trace_pattern(trace) if trace else ""
    failing_test = _failing_test(parsed_log, candidate)
    target_module = f"{candidate.target_file}:{candidate.line_number}:{candidate.target_function}"

    payload = _canonical_payload(
        error_type,
        stack_trace_pattern,
        failing_test,
        target_module,
    )
    fingerprint_hash = _fingerprint_hash(payload)

    return FailureFingerprint(
        error_type=error_type,
        stack_trace_pattern=stack_trace_pattern,
        failing_test=failing_test,
        target_module=target_module,
        fingerprint_hash=fingerprint_hash,
    )
