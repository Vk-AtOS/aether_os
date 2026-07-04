"""
Failure fingerprinting for patch reuse.
Builds deterministic fingerprints from root cause candidates and parsed CI logs.
Builds deterministic fingerprints from root cause candidates and parsed CI logs.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from aether_os.phases.p08_cicd.dfle.log_parser import ParsedLog, StackTrace
from aether_os.phases.p08_cicd.dfle.localizer import RootCauseCandidate

logger = logging.getLogger(__name__)


def _stack_trace_pattern(trace: StackTrace) -> str:
    parts = [f"{f.filename}:{f.line}:{f.function}" for f in trace.frames]
    return "|".join(parts)


def _failing_test(parsed_log: ParsedLog, candidate: RootCauseCandidate) -> str:
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
    return "\n".join([error_type, stack_trace_pattern, failing_test, target_module])


def _fingerprint_hash(payload: str) -> str:
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
        return {
            "error_type": self.error_type,
            "stack_trace_pattern": self.stack_trace_pattern,
            "failing_test": self.failing_test,
            "target_module": self.target_module,
            "fingerprint_hash": self.fingerprint_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FailureFingerprint":
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
    """Build a deterministic failure fingerprint from a root cause candidate and parsed log."""
    trace = parsed_log.primary_trace
    error_type = trace.exception_type if trace else ""
    stack_trace_pattern = _stack_trace_pattern(trace) if trace else ""
    failing_test = _failing_test(parsed_log, candidate)
    target_module = (
        f"{candidate.target_file}:{candidate.line_number}:{candidate.target_function}"
    )

    payload = _canonical_payload(
        error_type, stack_trace_pattern, failing_test, target_module
    )
    return FailureFingerprint(
        error_type=error_type,
        stack_trace_pattern=stack_trace_pattern,
        failing_test=failing_test,
        target_module=target_module,
        fingerprint_hash=_fingerprint_hash(payload),
    )
