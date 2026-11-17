"""KAN-114: the acceptance script skips cleanly without a model key/Docker/stack and records what it ran."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("acceptance_run", ROOT / "scripts/acceptance_run.py")
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)


def test_without_model_key_docker_or_stack_it_skips_and_writes_nothing(tmp_path, monkeypatch, capsys):
    for k in ar.MODEL_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ar, "docker_ok", lambda: False)
    monkeypatch.delenv("ACCEPT_TOKEN", raising=False)
    assert ar.main(["--out", str(tmp_path)]) == 0
    assert "SKIP" in capsys.readouterr().out and not list(tmp_path.iterdir())


def test_a_recorded_run_has_json_and_markdown_and_a_failed_stage_fails_it(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "run", lambda *a: [
        {"step": "preflight", "status": "PASS", "detail": "ready"},
        {"step": "pipeline", "status": "FAIL", "detail": "1 failed", "stages": {"ran": ["p01"], "skipped": [], "failed": ["p05"]}}])
    assert ar.main(["--out", str(tmp_path)]) == 1
    names = sorted(p.suffix for p in tmp_path.iterdir())
    assert names == [".json", ".md"]
    assert "MANUAL" in next(tmp_path.glob("*.md")).read_text()


def test_stage_summary_separates_ran_skipped_failed():
    s = ar.stage_summary({"phases": [{"phase_name": "a", "status": "completed"}, {"phase_name": "b", "status": "skipped"},
                                     {"phase_name": "c", "status": "failed"}]})
    assert s == {"ran": ["a"], "skipped": ["b"], "failed": ["c"]}
