"""
Root cause candidate scoring for DFLE.

Scores stack frames from a parsed CI log using AST proximity, stack depth,
dependency radius, and test coverage impact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aether_os.phases.p08_cicd.dfle.call_graph import CallGraph
from aether_os.phases.p08_cicd.dfle.log_parser import ParsedLog, StackFrame


def _node_id(frame: StackFrame) -> str:
    """Canonical ID for a stack frame (matches call_graph format)."""
    return f"{frame.filename}:{frame.line}:{frame.function}"


def _is_test_file(path: str) -> bool:
    """Heuristic: path is a test file if under tests/ or named test_*.py."""
    parts = path.replace("\\", "/").split("/")
    if any(p == "tests" for p in parts):
        return True
    return len(parts) > 0 and parts[-1].startswith("test_") and parts[-1].endswith(".py")


def _score_frame(
    frame: StackFrame,
    index: int,
    total_frames: int,
    call_graph: CallGraph,
    parsed_log: ParsedLog,
) -> tuple[float, int, list[str]]:
    """
    Score a single frame. Returns (confidence, dependency_radius, affected_tests).
    """
    node_id = _node_id(frame)

    # AST proximity: is the function in the call graph (i.e. indexed)?
    # Use 0.5 when call graph is empty so scores degrade gracefully
    if not call_graph.callees:
        ast_proximity = 0.5
    elif node_id in call_graph.callees:
        ast_proximity = 1.0
    else:
        ast_proximity = 0.0

    # Stack depth: frames closer to the exception (higher index) score higher
    # Frames[0] = entry, frames[-1] = near exception
    stack_depth_score = (index + 1) / max(total_frames, 1) if total_frames else 0.5

    # Dependency radius: how many callers does this function have?
    callers = call_graph.callers_of(node_id)
    dependency_radius = len(callers)
    # Normalize: more callers = higher impact, cap at 20 for scoring
    dep_score = min(1.0, dependency_radius / 20.0) if dependency_radius > 0 else 0.5

    # Test coverage impact: how many test files reference this function?
    test_files: set[str] = set()
    for caller_id in callers:
        path = caller_id.split(":")[0]
        if _is_test_file(path):
            test_files.add(path)
    # Also include test_names from parsed log that mention this file
    for t in parsed_log.test_names:
        if frame.filename in t or t in frame.filename:
            test_files.add(t.split("::")[0] if "::" in t else t)
    affected_tests = sorted(test_files)
    test_score = min(1.0, len(affected_tests) / 5.0) if affected_tests else 0.0

    # Weighted confidence: AST and stack depth primary, dep/test secondary
    confidence = (
        0.35 * ast_proximity
        + 0.35 * stack_depth_score
        + 0.15 * dep_score
        + 0.15 * test_score
    )

    return (confidence, dependency_radius, affected_tests)


@dataclass
class RootCauseCandidate:
    """A scored root cause candidate from a stack frame."""

    target_file: str
    target_function: str
    line_number: int
    confidence_score: float
    dependency_radius: int
    affected_tests: list[str] = field(default_factory=list)


def localize(
    parsed_log: ParsedLog,
    call_graph: CallGraph,
) -> list[RootCauseCandidate]:
    """
    Score and rank stack frames from the primary trace as root cause candidates.

    Args:
        parsed_log: Parsed CI log (from log_parser.parse_log).
        call_graph: Call graph (from call_graph.build_call_graph).

    Returns:
        Ranked list of RootCauseCandidate, highest confidence first.
    """
    trace = parsed_log.primary_trace
    if not trace or not trace.frames:
        return []

    frames = trace.frames
    total = len(frames)
    candidates: list[RootCauseCandidate] = []

    for i, frame in enumerate(frames):
        confidence, dep_radius, affected = _score_frame(
            frame, i, total, call_graph, parsed_log
        )
        candidates.append(
            RootCauseCandidate(
                target_file=frame.filename,
                target_function=frame.function,
                line_number=frame.line,
                confidence_score=round(confidence, 4),
                dependency_radius=dep_radius,
                affected_tests=affected,
            )
        )

    # Sort by confidence descending, then by stack depth (deeper frames first)
    frame_order = {_node_id(f): i for i, f in enumerate(frames)}

    def _sort_key(c: RootCauseCandidate) -> tuple[float, int]:
        idx = frame_order.get(_node_id_from_candidate(c), 0)
        return (-c.confidence_score, -idx)  # higher index = deeper = better

    candidates.sort(key=_sort_key)
    return candidates


def _node_id_from_candidate(c: RootCauseCandidate) -> str:
    return f"{c.target_file}:{c.line_number}:{c.target_function}"
