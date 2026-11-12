"""Gateway reads of sandbox-writable project dirs never follow a planted link."""
from __future__ import annotations

import json
import os

from aether_os.core.run_app import safe_fs
from aether_os.gateway.services import phase_output

SECRET = {"stolen": "HOST"}


def _plant(tmp_path):
    host = tmp_path / "host"
    host.mkdir()
    (host / "secret.json").write_text(json.dumps(SECRET))
    (host / "architecture.json").write_text(json.dumps(SECRET))
    proj = tmp_path / "proj"
    proj.mkdir()
    return proj, host


def test_symlinked_json_file_is_not_read(tmp_path):
    proj, host = _plant(tmp_path)
    (proj / "s02_architecture").mkdir()
    (proj / "s02_architecture" / "architecture.json").symlink_to(host / "secret.json")
    (proj / "s02_architecture" / "other.json").symlink_to(host / "secret.json")
    assert phase_output.stage_output(proj, "s02_architecture") == (None, None)


def test_symlinked_stage_folder_is_skipped(tmp_path):
    proj, host = _plant(tmp_path)
    (proj / "s02_architecture").symlink_to(host)
    assert phase_output.stage_output(proj, "s02_architecture") == (None, None)
    assert phase_output.stage_gate_result(proj, "s02_architecture") is None


def test_symlinked_subfolder_and_parent_are_not_counted_or_read(tmp_path):
    proj, host = _plant(tmp_path)
    folder = proj / "s02_architecture"
    folder.mkdir()
    (folder / "real.txt").write_text("x")
    (folder / "linkdir").symlink_to(host)
    (folder / "linkfile.txt").symlink_to(host / "secret.json")
    out, _ = phase_output.stage_output(proj, "s02_architecture")
    assert out["file_count"] == 1
    assert safe_fs.read_text_or_none(proj, "s02_architecture/linkdir/secret.json") is None
    assert safe_fs.walk_files(proj) == [folder.relative_to(proj) / "real.txt"]


def test_security_report_and_gate_through_links_are_ignored(tmp_path):
    proj, host = _plant(tmp_path)
    (proj / "p06_review_security").symlink_to(host)
    phases = {"s05_quality": {}}
    res = phase_output.enrich_phases(phases, proj, str(proj))
    assert "output" not in res["s05_quality"] and "gate_result" not in res["s05_quality"]


def test_real_files_still_work_and_big_or_special_files_are_refused(tmp_path):
    proj, _ = _plant(tmp_path)
    (proj / "s02_architecture").mkdir()
    (proj / "s02_architecture" / "architecture.json").write_text('{"ok": 1}')
    assert phase_output.stage_output(proj, "s02_architecture") == ({"ok": 1}, "s02_architecture/architecture.json")
    (proj / "big.txt").write_text("x" * 100)
    assert safe_fs.read_text_or_none(proj, "big.txt", max_bytes=10) is None
    os.mkfifo(proj / "pipe")
    assert safe_fs.read_text_or_none(proj, "pipe") is None
    assert safe_fs.read_text_or_none(proj, "../host/secret.json") is None
    assert safe_fs.read_text_or_none(proj, proj.parent / "host" / "secret.json") is None


def test_listing_walk_and_dir_checks_never_follow_links(tmp_path):
    proj, host = _plant(tmp_path)
    (proj / "real").mkdir()
    (proj / "real" / "f.txt").write_text("x")
    (proj / "dirlink").symlink_to(host)
    (proj / "filelink").symlink_to(host / "secret.json")
    assert safe_fs.list_dir(proj) == [("real", True)]
    assert safe_fs.list_dir(proj, "dirlink") == []
    assert not safe_fs.is_real_dir(proj, "dirlink") and safe_fs.is_real_dir(proj, "real")
    assert safe_fs.walk_files(proj) == [__import__("pathlib").Path("real/f.txt")]
    assert safe_fs.stat_or_none(proj, "filelink") is None
    assert safe_fs.read_prefix_or_none(proj, "dirlink/secret.json", 10) is None


def test_writes_and_makedirs_refuse_links(tmp_path):
    import pytest
    from aether_os.core.errors import SandboxViolation
    proj, host = _plant(tmp_path)
    (proj / "linked").symlink_to(host)
    with pytest.raises(SandboxViolation):
        safe_fs.safe_makedirs(proj, "linked/sub")
    assert not (host / "sub").exists()
    (proj / "fb.jsonl").symlink_to(host / "secret.json")
    with pytest.raises(SandboxViolation):
        safe_fs.safe_append_text(proj, proj / "fb.jsonl", "pwn")
    assert json.loads((host / "secret.json").read_text()) == SECRET
    safe_fs.safe_makedirs(proj, "a/b")
    safe_fs.safe_write_bytes(proj, proj / "a/b/x.bin", b"ok")
    assert (proj / "a/b/x.bin").read_bytes() == b"ok"


def test_project_memory_and_clarifying_questions_ignore_planted_links(tmp_path, monkeypatch):
    from aether_os.core import project_memory
    from aether_os.orchestrator import clarifying
    proj, host = _plant(tmp_path)
    (proj / ".aetheros").symlink_to(host)
    assert project_memory.read_memory(proj) is None
    (host / "s02_architecture.json").write_text(json.dumps({"clarifying_questions": [{"x": 1}]}))
    (proj / "s02_architecture").symlink_to(host)

    class PM:
        def get_project_dir(self, _id):
            return proj
    monkeypatch.setattr(clarifying, "get_project_manager", lambda: PM())
    assert clarifying.stored_questions("r") == []
