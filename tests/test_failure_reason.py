"""KAN-249 / KAN-257: a stage failure carries the sub-phase's own error; an identical failure is not retried."""
import asyncio
from types import SimpleNamespace

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult
from aether_os.phases.failure_reason import (
    exception_issue, failure_fingerprint, failure_issues, is_generic_failure, sub_phase_causes,
)
from aether_os.stages.s03_backend.supervisor import BackendStageSupervisor
from aether_os.stages.s04_frontend.supervisor import FrontendStageSupervisor

PREGEN = "P04a pre-generation check failed: ['circular_fk: Task -> Project -> Task']"


def test_causes_come_from_issues_then_metadata():
    r = TaskResult(output_path="", confidence=0.0, success=False, issues=["a"],
                   metadata={"tsc_messages": ["src/X.tsx(1,2): error TS1005", "b"], "error": "boom"})
    assert sub_phase_causes(r, limit=3) == ["a", "boom", "src/X.tsx(1,2): error TS1005"]
    assert failure_issues("s04", "p05", r)[0] == "s04: p05 failed: a"


def test_no_recorded_error_is_said_plainly_not_guessed():
    out = failure_issues("s04", "p05", TaskResult(output_path="", confidence=0.0, success=False))
    assert out == ["s04: p05 failed and recorded no error text (success=False)"]


def test_s03_gate_reports_the_validator_error_not_a_missing_path():
    """Runs e53e5f12 / af268b8e: p04a rejected the spec, s03 said 'backend_output_path is missing'."""
    sup = BackendStageSupervisor()

    async def raising_p04(*a, **k):
        raise RuntimeError(PREGEN)

    sup._run_p04_backend = raising_p04  # the real wrapper turns the exception into the failed result below
    failed = TaskResult(output_path="", confidence=0.0, success=False,
                        issues=[exception_issue("s03_backend", "p04_backend", RuntimeError(PREGEN))])
    gate = asyncio.run(sup.validate_gate(failed, None))
    assert not gate.passed
    assert "circular_fk" in gate.issues[0] and "missing" not in " ".join(gate.issues)


def test_s03_wrapper_turns_a_raised_error_into_its_reason(monkeypatch, tmp_path):
    import aether_os.phases.p04_backend.task_agent as p04

    async def boom(*a, **k):
        raise RuntimeError(PREGEN)

    monkeypatch.setattr(p04, "run", boom)
    res = asyncio.run(BackendStageSupervisor()._run_p04_backend(SimpleNamespace(), [], tmp_path / "s03"))
    assert not res.success and "circular_fk" in res.issues[0] and "RuntimeError" in res.issues[0]


def test_s04_gate_carries_tsc_errors_from_phase_metadata():
    res = TaskResult(output_path="/x", confidence=0.0, success=False,
                     metadata={"tsc_messages": ["error TS2345: Argument of type 'string'"]})
    gate = asyncio.run(FrontendStageSupervisor().validate_gate(res, None))
    assert not gate.passed and "TS2345" in gate.issues[0] and "check p05 logs" not in gate.issues[0]


def test_fingerprint_ignores_volatile_parts_only():
    a = failure_fingerprint(["run e53e5f12-0000-4000-8000-123456789abc failed at 2026-11-28T10:00:01Z in /tmp/x/y: bad"])
    b = failure_fingerprint(["run aaaaaaaa-0000-4000-8000-123456789abc failed at 2026-11-28T11:30:09Z in /tmp/z/q: bad"])
    assert a == b and a != failure_fingerprint(["worse"])
    assert is_generic_failure(["x: sub-step reported failure"]) and not is_generic_failure([PREGEN])


class _Retry(PhaseBase):
    phase_name = "fake"

    def __init__(self, mode):
        super().__init__()
        self.mode, self.runs, self.escalated = mode, 0, None

    async def run_task(self, phase_input, memory_ctx):
        self.runs += 1
        if self.mode == "raise":
            raise RuntimeError(PREGEN)
        if self.mode == "timeout":
            raise asyncio.TimeoutError()
        return TaskResult(output_path="", confidence=1.0)

    async def validate_gate(self, result, phase_input):
        return GateOutcome(passed=False, issues=[PREGEN if self.mode == "gate" else f"different {self.runs}"])

    async def _escalate(self, phase_input, reason):
        self.escalated = reason

    async def memory_before(self, *a, **k):
        return []

    async def communicate(self, *a, **k):
        return None


def _go(stage):
    return asyncio.run(stage.run(SimpleNamespace(input_data={}, run_id="r", output_dir="", domain="x")))


def test_identical_gate_failure_stops_after_second_attempt_with_real_reason():
    st = _Retry("gate")
    res = _go(st)
    assert st.runs == 2 and not res.success
    assert "circular_fk" in st.escalated and "identical failure on retry, not retried further" in st.escalated


def test_identical_exception_stops_but_timeouts_keep_retrying():
    st = _Retry("raise")
    _go(st)
    assert st.runs == 2 and "identical failure on retry" in st.escalated
    st = _Retry("timeout")
    _go(st)
    assert st.runs == 3


def test_changing_failure_keeps_all_attempts():
    st = _Retry("changing")
    _go(st)
    assert st.runs == 3
