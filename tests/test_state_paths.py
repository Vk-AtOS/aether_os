"""Runtime state is written under AETHER_STATE_DIR, never into the package (KAN-216, KAN-217: the image is read-only
for the API user, so the error registry and Guardian snapshots failed with Permission denied on production)."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from aether_os.core import state_paths


def test_state_file_seeds_from_the_shipped_copy_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_STATE_DIR", str(tmp_path / "state"))
    seed = tmp_path / "seed.json"
    seed.write_text("[1]")
    p = state_paths.state_file("x/reg.json", seed=seed)
    assert p == tmp_path / "state" / "x" / "reg.json" and p.read_text() == "[1]"
    p.write_text("[1, 2]")
    seed.write_text("[9]")
    assert state_paths.state_file("x/reg.json", seed=seed).read_text() == "[1, 2]"   # never overwritten


def test_error_registry_writes_under_the_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_STATE_DIR", str(tmp_path))
    from aether_os.core.error_registry import ErrorCategory, ErrorRegistry
    reg = ErrorRegistry()
    reg.record(ErrorCategory.UNKNOWN, "p04a", "detail")
    assert reg._path.is_relative_to(tmp_path)
    assert json.loads(reg._path.read_text())


def test_stage_feedback_writes_under_the_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_STATE_DIR", str(tmp_path))
    from aether_os.core import stage_feedback
    stage_feedback.record_stage_output("s04", "r", ["a"], {"q": 1.0})
    assert (tmp_path / "knowledge_graph" / "stage_feedback.jsonl").read_text().strip()


def test_guardian_default_is_under_the_state_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("GUARDIAN_SNAPSHOT_DIR", raising=False)
    monkeypatch.setenv("AETHER_STATE_DIR", str(tmp_path))
    from aether_os.core.guardian import snapshot_manager as sm
    try:
        assert importlib.reload(sm)._SNAPSHOT_DIR == (tmp_path / "snapshots" / "guardian").resolve()
    finally:
        monkeypatch.undo()
        importlib.reload(sm)


def test_package_files_are_only_seeds():
    import aether_os.core.error_registry as er
    assert er._SHIPPED_JSON_PATH.name == "error_registry.json" and er._SHIPPED_JSON_PATH.parent == Path(er.__file__).parent
