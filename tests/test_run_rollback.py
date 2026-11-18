"""KAN-161: POST /factory/runs/{id}/snapshots/{sid}/rollback restores a file from a snapshot row."""


def _home(monkeypatch, tmp_path):
    """The project manager is a singleton: point it at this test's projects dir."""
    from aether_os.core.projects import get_project_manager
    monkeypatch.setattr(get_project_manager(), "_root", tmp_path / ".aether_os" / "projects")


def _run(gw, org, rid):
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'x', 'completed', 0, 0, 1)", (rid, org.org_id))


def _snap(gw, sid, rid, path, content, org_id=None):
    gw.sql("INSERT INTO snapshots (id, run_id, org_id, file_path, content, created_at) VALUES (?,?,?,?,?,0)",
           (sid, rid, org_id, path, content))


def test_rollback_restores_audits_and_is_scoped(gw, tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    org, other = gw.register("rbk"), gw.register("rbkb")
    _run(gw, org, "rb-run")
    _snap(gw, "s1", "rb-run", "src/app.py", "GOOD = 1\n", org.org_id)
    proj = tmp_path / ".aether_os" / "projects" / "rb-run"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "app.py").write_text("BROKEN")
    url = "/factory/runs/rb-run/snapshots/s1/rollback"

    assert gw.client.post(url, headers=other.auth).status_code == 404       # other org: nothing leaks
    viewer = gw.user_with_role("viewer", org.org_id)
    assert gw.client.post(url, headers=viewer.auth).status_code == 403      # admin only
    assert (proj / "src" / "app.py").read_text() == "BROKEN"

    got = gw.client.post(url, headers=org.auth)
    assert got.status_code == 200, got.text
    assert (proj / "src" / "app.py").read_text() == "GOOD = 1\n"


def test_rollback_refuses_paths_outside_the_run_and_foreign_snapshots(gw, tmp_path, monkeypatch):
    _home(monkeypatch, tmp_path)
    org, other = gw.register("rbk2"), gw.register("rbk2b")
    _run(gw, org, "rb2")
    _run(gw, other, "rb2-other")
    _snap(gw, "bad1", "rb2", "../../escape.txt", "x", org.org_id)
    _snap(gw, "bad2", "rb2", "/etc/passwd", "x", org.org_id)
    _snap(gw, "foreign", "rb2-other", "a.py", "x", other.org_id)
    for sid in ("bad1", "bad2"):
        assert gw.client.post(f"/factory/runs/rb2/snapshots/{sid}/rollback", headers=org.auth).status_code == 422
    # a snapshot of another org's run, addressed through my run id
    assert gw.client.post("/factory/runs/rb2/snapshots/foreign/rollback", headers=org.auth).status_code == 404
    assert not (tmp_path / "escape.txt").exists()
    # a planted link inside the run dir is never written through
    proj = tmp_path / ".aether_os" / "projects" / "rb2"
    proj.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    (proj / "link.py").symlink_to(victim)
    _snap(gw, "lnk", "rb2", "link.py", "pwned", org.org_id)
    assert gw.client.post("/factory/runs/rb2/snapshots/lnk/rollback", headers=org.auth).status_code == 403
    assert victim.read_text() == "keep"
