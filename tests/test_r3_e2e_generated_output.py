"""End to end on the generator's OUTPUT (KAN-180): one product description in, a backend that runs and serves CRUD
and a frontend that builds out. Offline (no model: the deterministic generators); the real `npm install && vite
build` runs only with AETHER_NPM_BUILD_TEST=1 (the nightly workflow sets it and has Node)."""
import os
import shutil
import subprocess

import pytest

from aether_os.tests.test_p04a_generated_backend import generate, run_app
from aether_os.tests.test_p05_generated_frontend import build_frontend, unresolved_imports


def test_generated_product_backend_serves_crud_and_frontend_is_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    (tmp_path / "be").mkdir()
    _, backend = generate(tmp_path / "be", domain="crm", monkeypatch=monkeypatch)
    out = run_app(backend, "customers")
    assert out["register"] in (200, 201) and out["admin_login"] == 200
    assert out["admin_create_customers"] == 201 and out["admin_items_customers"] >= 1      # created, seeded, listed
    assert out["user_list_customers"] == 403 and out["user_create_customers"] == 403         # the IR grants admin only: deny by default
    assert out["admin_delete_customers"] in (200, 204) and out["user_delete_customers"] == 403
    frontend = build_frontend(tmp_path / "fe", "crm", monkeypatch)
    assert unresolved_imports(frontend) == []
    assert (frontend / "package.json").exists() and (frontend / "index.html").exists()


@pytest.mark.skipif(os.environ.get("AETHER_NPM_BUILD_TEST") != "1" or not shutil.which("npm"),
                    reason="AETHER_NPM_BUILD_TEST=1 and npm are needed for the real frontend build")
def test_generated_frontend_really_builds_with_npm(tmp_path, monkeypatch):
    frontend = build_frontend(tmp_path, "crm", monkeypatch)
    for cmd in (["npm", "install", "--no-audit", "--no-fund"], ["npm", "run", "build"]):
        done = subprocess.run(cmd, cwd=frontend, capture_output=True, text=True, timeout=900)
        assert done.returncode == 0, f"{' '.join(cmd)} failed:\n{(done.stdout + done.stderr)[-2500:]}"
    assert (frontend / "dist" / "index.html").exists()
