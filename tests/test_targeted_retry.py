"""KAN-210: a gate failure repairs the named files only, never re-runs the stage, never repeats an identical failure."""
import asyncio
from types import SimpleNamespace

from aether_os.phases.base import GateOutcome, PhaseBase, TaskResult
from aether_os.phases.targeted_retry import describe_failures, failure_signature, parse_failed_files
from aether_os.stages.s04_frontend import supervisor as s04
from aether_os.stages.s04_frontend.repair import failed_files_from_metadata

BAD = {"src/pages/TaskPage.tsx": "src/pages/TaskPage.tsx(254,306): error TS1005: '}' expected."}


class FakeStage(PhaseBase):
    phase_name = "fake"

    def __init__(self, fixed_after, repairable=True):
        super().__init__()
        self.generated, self.repairs, self.fixed_after, self.repairable = 0, [], fixed_after, repairable
        self.escalated = None

    async def run_task(self, phase_input, memory_ctx):
        self.generated += 1
        return TaskResult(output_path="", confidence=1.0)

    async def validate_gate(self, result, phase_input):
        if len(self.repairs) >= self.fixed_after:
            return GateOutcome(passed=True)
        # error text changes with each repair unless the repair is a no-op
        err = dict(BAD) if not self.repairable else {k: f"{v} #{len(self.repairs)}" for k, v in BAD.items()}
        return GateOutcome(passed=False, issues=["failed"], failed_files=err)

    async def repair_failed_files(self, result, gate, phase_input):
        self.repairs.append(sorted(gate.failed_files))
        return result

    async def _escalate(self, phase_input, reason):
        self.escalated = reason

    async def memory_before(self, *a, **k):
        return []

    async def memory_after(self, *a, **k):
        return None

    async def communicate(self, *a, **k):
        return None


def _run(stage):
    return asyncio.run(stage.run(SimpleNamespace(input_data={}, run_id="r", output_dir="", domain="x")))


def test_repairs_only_the_failing_file_and_does_not_rerun_the_stage():
    st = FakeStage(fixed_after=1)
    assert _run(st).success
    assert st.generated == 1
    assert st.repairs == [["src/pages/TaskPage.tsx"]]


def test_identical_failure_after_repair_regenerates_once_then_stops_and_names_file_and_error():
    st = FakeStage(fixed_after=99, repairable=False)
    res = _run(st)
    # repair made no progress -> the stage is regenerated (run 16); the same failure again -> stop
    assert res.escalated and st.generated == 2 and len(st.repairs) == 2
    assert "src/pages/TaskPage.tsx" in st.escalated and "TS1005" in st.escalated


def test_repairs_are_bounded_per_attempt_and_the_stage_is_regenerated_when_they_run_out():
    st = FakeStage(fixed_after=99)
    assert _run(st).escalated
    assert st.generated >= 2 and len(st.repairs) <= st.max_retries * st.generated
    assert "TaskPage.tsx" in st.escalated


def test_phase_without_repair_falls_back_to_stage_retry():
    class NoRepair(FakeStage):
        async def repair_failed_files(self, *a):
            return None
    st = NoRepair(fixed_after=99)
    assert _run(st).escalated
    assert st.generated == 2  # second identical failure stops the whole-stage retry too


def test_parse_failed_files_tsc_and_vite():
    out = ("src/pages/A.tsx(254,306): error TS1005: '}' expected.\n"
           "[vite:esbuild] Transform failed\n/app/frontend/src/pages/B.tsx:291:42: ERROR: Unexpected \"<\"\n"
           "node_modules/x/y.js:1:1: boom")
    got = parse_failed_files(out)
    assert set(got) == {"src/pages/A.tsx", "src/pages/B.tsx"}
    assert "TS1005" in got["src/pages/A.tsx"]


def test_signature_depends_on_files_and_errors():
    assert failure_signature(BAD) == failure_signature(dict(BAD))
    assert failure_signature(BAD) != failure_signature({"src/a.tsx": "x"})
    assert "TaskPage.tsx" in describe_failures(BAD)


def test_s04_gate_names_failing_file():
    meta = {"tsc_messages": [BAD["src/pages/TaskPage.tsx"]], "build_errors": ""}
    assert "src/pages/TaskPage.tsx" in failed_files_from_metadata(meta)
    res = TaskResult(output_path="/x", confidence=0.0, success=False, metadata=meta)
    gate = asyncio.run(s04.FrontendStageSupervisor().validate_gate(res, None))
    assert not gate.passed and set(gate.failed_files) == {"src/pages/TaskPage.tsx"}
    assert "TaskPage.tsx" in gate.issues[0] and "check p05 logs" not in gate.issues[0]


def test_generic_gate_failures_keep_every_whole_stage_attempt():
    """Generic issue text ("sub-step reported failure") is not proof of identical input: a real model can pass on a
    later whole-stage attempt, so phases without file-level failures keep all max_retries attempts."""
    class Generic(FakeStage):
        async def validate_gate(self, result, phase_input):
            if self.generated >= 3:
                return GateOutcome(passed=True)
            return GateOutcome(passed=False, issues=["s04_frontend: sub-step reported failure"])

    st = Generic(fixed_after=99)
    assert _run(st).success and st.generated == 3


def test_regeneration_after_failed_repair_can_pass():
    class FixedOnRegenerate(FakeStage):
        async def validate_gate(self, result, phase_input):
            if self.generated >= 2:
                return GateOutcome(passed=True)
            return GateOutcome(passed=False, issues=["failed"], failed_files=dict(BAD))
    st = FixedOnRegenerate(fixed_after=99, repairable=False)
    assert _run(st).success and st.generated == 2
