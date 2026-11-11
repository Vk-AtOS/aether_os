"""/admin/prune-artifacts: platform-wide directory, so superadmin only, and ttl_days >= 1."""
from __future__ import annotations

import os
import time

import pytest


@pytest.fixture()
def artifacts(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    (root / "run1").mkdir(parents=True)
    old, new = root / "run1" / "old.bin", root / "run1" / "new.bin"
    old.write_bytes(b"x" * 10)
    new.write_bytes(b"y" * 10)
    long_ago = time.time() - 90 * 86400
    os.utime(old, (long_ago, long_ago))
    monkeypatch.setenv("ARTIFACT_DIR", str(root))
    return old, new


def test_org_owner_and_admin_cannot_prune_or_list(gw, artifacts):
    old, new = artifacts
    owner = gw.register("prune")
    admin = gw.user_with_role("admin", owner.org_id)
    for who in (owner, admin):
        for body in ({"ttl_days": 30, "dry_run": True}, {"ttl_days": 0}, {"ttl_days": 30}):
            resp = gw.client.post("/admin/prune-artifacts", headers=who.auth, json=body)
            assert resp.status_code == 403, resp.text
            assert "old.bin" not in resp.text
    assert old.exists() and new.exists()
    assert gw.client.post("/admin/prune-artifacts", json={}).status_code == 401


def test_superadmin_prunes_only_files_older_than_ttl(gw, artifacts):
    old, new = artifacts
    root = gw.user_with_role("superadmin", gw.register("plat").org_id)

    dry = gw.client.post("/admin/prune-artifacts", headers=root.auth, json={"ttl_days": 30, "dry_run": True})
    assert dry.status_code == 200, dry.text
    assert dry.json()["files"] == ["run1/old.bin"] and old.exists()

    for bad in (0, -5, "soon", None):
        resp = gw.client.post("/admin/prune-artifacts", headers=root.auth, json={"ttl_days": bad})
        assert resp.status_code == 422, (bad, resp.text)
    assert old.exists() and new.exists()

    done = gw.client.post("/admin/prune-artifacts", headers=root.auth, json={"ttl_days": 30})
    assert done.status_code == 200 and done.json()["deleted_count"] == 1
    assert not old.exists() and new.exists()
