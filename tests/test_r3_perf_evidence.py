"""KAN-193: the evidence script refuses to record without a stack and judges each claim against its measurement."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rpe", ROOT / "scripts" / "record_performance_evidence.py")
rpe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rpe)


def test_no_stack_means_exit_2_and_no_file(tmp_path, capsys):
    code = rpe.main(["--host", "http://127.0.0.1:9", "--email", "a@b.c", "--password", "x", "--out-dir", str(tmp_path / "ev")])
    assert code == 2 and not (tmp_path / "ev").exists()


def test_claims_are_judged_against_measurements():
    got = {c["metric"]: c["met"] for c in rpe.judge({"load_p95_ms": 310.0, "load_error_rate": 0.0})}
    assert got == {"load_p95_ms": False, "load_error_rate": True, "build_minutes_mean": None}     # build not measured
    assert all(c["met"] for c in rpe.judge({"load_p95_ms": 100, "load_error_rate": 0, "build_minutes_mean": 8.5}))


def test_scheduled_workflows_exist_and_point_at_real_files():
    import yaml
    wf = ROOT / ".github" / "workflows"
    weekly = yaml.safe_load((wf / "weekly-benchmark.yml").read_text())
    nightly = yaml.safe_load((wf / "nightly-generated-app.yml").read_text())
    for doc in (weekly, nightly):
        assert doc[True]["schedule"][0]["cron"]          # YAML reads the key `on` as True
    text = (wf / "weekly-benchmark.yml").read_text()
    assert "scripts/benchmark_harness.py" in text and (ROOT / "scripts" / "benchmark_harness.py").exists()
    run = nightly["jobs"]["generated-output"]["steps"][-1]["run"]
    for path in run.split():
        if path.startswith("tests/"):
            assert (ROOT / path).exists(), path
