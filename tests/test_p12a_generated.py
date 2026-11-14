"""KAN-109/KAN-99: generated feature-flag service: its own tests pass and the admin router needs admin auth."""
import asyncio
import subprocess
import sys
from types import SimpleNamespace

from aether_os.phases.p12a_feature_flags import task_agent


def _generate(tmp_path):
    asyncio.run(task_agent.run(SimpleNamespace(input_data={}), [], tmp_path))


def test_generated_tests_pass(tmp_path):
    _generate(tmp_path)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-800:]


def test_admin_router_is_not_open_without_auth(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    _generate(tmp_path)
    sys.path.insert(0, str(tmp_path))
    try:
        from feature_flags.flag_admin_router import router
        app = FastAPI()
        app.include_router(router)
        c = TestClient(app)
        assert c.post("/flags/x/enable").status_code in (401, 403, 503)
        assert c.get("/flags/").status_code in (401, 403, 503)
    finally:
        sys.path.remove(str(tmp_path))
        for m in [m for m in sys.modules if m.startswith("feature_flags")]:
            del sys.modules[m]
