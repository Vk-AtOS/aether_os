"""/rerun and /branch start the new run on a copy of the parent's (edited) project folder."""
from __future__ import annotations

import os
import time
import uuid
from unittest.mock import patch

import pytest

import aether_os.core.projects as projects_mod
from aether_os.core import project_copy


class _NoBuild:
    async def run(self, **kw):
        return None


@pytest.fixture(scope="module")
def projects_root(tmp_path_factory):
    saved = projects_mod._manager
    root = tmp_path_factory.mktemp("forkprojects")
    projects_mod._manager = projects_mod.ProjectManager(root=root)
    yield root
    projects_mod._manager = saved


def _run(gw, org_id):
    run_id = str(uuid.uuid4())
    gw.sql("INSERT INTO runs (id, org_id, command, raw_input, status, started_at, cost, run_version, project_name) "
           "VALUES (?, ?, 'factory: todo', 'todo', 'completed', ?, 0, 1, 'Todo')", (run_id, org_id, time.time()))
    return run_id


def _parent_folder(root, run_id, outside):
    base = root / run_id
    (base / "p04_backend" / "backend_codegen" / "src").mkdir(parents=True)
    (base / "p04_backend" / "backend_codegen" / "src" / "main.py").write_text("# edited by the user\n")
    (base / "p05_frontend" / "frontend" / "src").mkdir(parents=True)
    (base / "p05_frontend" / "frontend" / "src" / "App.tsx").write_text("export default 1\n")
    # everything below must NOT be copied
    (base / "p04_backend" / ".env").write_text("SECRET_KEY=abc")
    (base / "p05_frontend" / "frontend" / ".env.production").write_text("VITE=1")
    (base / "p05_frontend" / "frontend" / "node_modules" / "pkg").mkdir(parents=True)
    (base / "p05_frontend" / "frontend" / "node_modules" / "pkg" / "i.js").write_text("x")
    (base / ".venv-docker" / "bin").mkdir(parents=True)
    (base / ".venv-docker" / "bin" / "python").write_text("x")
    (base / "run_app.log").write_text("log")
    (base / "server.pem").write_text("-----BEGIN PRIVATE KEY-----")
    (base / "preview.db").write_text("db")
    (base / ".sandbox_home").mkdir()
    (base / ".sandbox_home" / "cache").write_text("x")
    (base / "link_out").symlink_to(outside)
    (base / "link_file").symlink_to(outside / "secret.txt")
    return base


def _files(path):
    return {str(p.relative_to(path)) for p in path.rglob("*") if p.is_file() or p.is_symlink()}


@pytest.fixture
def outside(tmp_path):
    d = tmp_path / "outside"
    d.mkdir()
    (d / "secret.txt").write_text("platform secret")
    return d


@pytest.mark.parametrize("route, body, branch_key", [
    ("rerun", {"from_phase": "s03_backend"}, "from_phase"),
    ("branch", {"branch_phase": "s04_frontend"}, "branch_phase"),
])
def test_new_run_starts_with_a_copy_of_the_parents_edited_files(gw, projects_root, outside, route, body, branch_key):
    owner = gw.register(f"fork{route}")
    parent = _run(gw, owner.org_id)
    _parent_folder(projects_root, parent, outside)
    with patch("aether_os.gateway.services.run_start.get_factory", return_value=_NoBuild()):
        resp = gw.client.post(f"/factory/runs/{parent}/{route}", headers=owner.auth, json=body)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    new = projects_root / out["run_id"]
    assert _files(new) == {"p04_backend/backend_codegen/src/main.py", "p05_frontend/frontend/src/App.tsx"}
    assert (new / "p04_backend/backend_codegen/src/main.py").read_text() == "# edited by the user\n"
    assert out["files_copied"] == 2 and out["source_run_id"] == parent
    row = gw.sql("SELECT parent_run_id, branch_phase FROM runs WHERE id = ?", (out["run_id"],))[0]
    assert row == (parent, body[branch_key])
    assert out["parent_run_id"] == parent and out["branch_phase"] == body[branch_key]
    assert (projects_root / parent / "link_out").is_symlink()           # the parent is untouched


def test_copy_files_false_starts_empty(gw, projects_root, outside):
    owner = gw.register("forkempty")
    parent = _run(gw, owner.org_id)
    _parent_folder(projects_root, parent, outside)
    with patch("aether_os.gateway.services.run_start.get_factory", return_value=_NoBuild()):
        out = gw.client.post(f"/factory/runs/{parent}/rerun", headers=owner.auth,
                             json={"from_phase": "s03_backend", "copy_files": False}).json()
    assert out["files_copied"] == 0 and not (projects_root / out["run_id"]).exists()


def test_another_orgs_run_cannot_be_copied_from(gw, projects_root, outside):
    a, b = gw.register("forka"), gw.register("forkb")
    mine, theirs = _run(gw, a.org_id), _run(gw, b.org_id)
    _parent_folder(projects_root, theirs, outside)
    before = set(os.listdir(projects_root))
    with patch("aether_os.gateway.services.run_start.get_factory", return_value=_NoBuild()):
        # their run as the parent
        assert gw.client.post(f"/factory/runs/{theirs}/rerun", headers=a.auth,
                              json={"from_phase": "s03_backend"}).status_code == 404
        # their run as the file source of my own run
        resp = gw.client.post(f"/factory/runs/{mine}/rerun", headers=a.auth,
                              json={"from_phase": "s03_backend", "source_run_id": theirs})
    assert resp.status_code == 404
    assert set(os.listdir(projects_root)) == before      # no folder was created


def test_oversized_folder_is_413_and_nothing_is_created_or_consumed(gw, projects_root, outside, monkeypatch):
    owner = gw.register("forkbig")
    gw.sql("UPDATE organisations SET plan = 'trial', trial_runs_limit = 3, trial_runs_used = 0 WHERE id = ?", (owner.org_id,))
    parent = _run(gw, owner.org_id)
    _parent_folder(projects_root, parent, outside)
    monkeypatch.setenv("AETHER_FORK_COPY_MAX_MB", "0.00001")
    before = gw.sql("SELECT count(*) FROM runs WHERE org_id = ?", (owner.org_id,))[0][0]
    with patch("aether_os.gateway.services.run_start.get_factory", return_value=_NoBuild()):
        resp = gw.client.post(f"/factory/runs/{parent}/branch", headers=owner.auth, json={"branch_phase": "s03_backend"})
    assert resp.status_code == 413
    assert gw.sql("SELECT count(*) FROM runs WHERE org_id = ?", (owner.org_id,))[0][0] == before
    assert gw.sql("SELECT trial_runs_used FROM organisations WHERE id = ?", (owner.org_id,))[0][0] == 0


def test_file_count_limit(tmp_path, monkeypatch, outside):
    (tmp_path / "p").mkdir()
    for i in range(5):
        (tmp_path / "p" / f"f{i}.py").write_text("x")
    monkeypatch.setenv("AETHER_FORK_COPY_MAX_FILES", "3")
    with pytest.raises(project_copy.ProjectTooLarge):
        project_copy.plan_copy(tmp_path)


def test_the_copy_is_recorded_in_the_ledger(gw, projects_root, outside):
    owner = gw.register("forkledger")
    parent = _run(gw, owner.org_id)
    _parent_folder(projects_root, parent, outside)
    with patch("aether_os.gateway.services.run_start.get_factory", return_value=_NoBuild()):
        out = gw.client.post(f"/factory/runs/{parent}/rerun", headers=owner.auth,
                             json={"from_phase": "s03_backend"}).json()
    rows = gw.sql("SELECT log_metadata FROM audit_log WHERE action = 'run.rerun' AND resource_id = ?", (out["run_id"],))
    assert rows and parent in rows[0][0] and '"files_copied": 2' in rows[0][0]
