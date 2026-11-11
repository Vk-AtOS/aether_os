"""Launching a generated app, end to end through the real gateway:

  * the child process gets an allowlist environment — no platform secrets;
  * the preview proxy only reaches the process that was launched for the run
    (pid + per-launch nonce); a stale or forged state file means "app down".

Real code throughout: POST /run-app → RunAppManager.start → a real uvicorn child
→ GET /app-preview. Only the auto-restart launcher is stubbed where a test must
observe "treated as down" without starting another process.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid

import pytest

import aether_os.core.projects as projects_mod
from aether_os.core import app_state
from aether_os.core.run_app import preview_state
from aether_os.core.run_app.child_env import child_env
from aether_os.gateway.auth import create_preview_token
from aether_os.gateway.routers import app_preview_router
from aether_os.tests.gateway_env import gateway_env

PLATFORM_SECRETS = {
    "ANTHROPIC_API_KEY": "sk-ant-platform-secret",
    "OPENROUTER_API_KEY": "sk-or-platform-secret",
    "AWS_ACCESS_KEY_ID": "AKIAPLATFORMSECRET00",
    "AWS_SECRET_ACCESS_KEY": "aws-platform-secret",
    "FIELD_ENCRYPTION_KEY": "field-key-platform-secret",
    "JWT_PRIVATE_KEY": "jwt-platform-secret",
    "REDIS_URL": "redis://:platform-secret@localhost:6379/0",
}

GENERATED_MAIN = '''
import os
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/env")
def env():
    return dict(os.environ)
'''


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("projects")
    saved_manager = projects_mod._manager
    saved_env = {k: os.environ.get(k) for k in PLATFORM_SECRETS}
    os.environ.update(PLATFORM_SECRETS)
    projects_mod._manager = projects_mod.ProjectManager(root=root)
    try:
        with gateway_env(tmp_path_factory.mktemp("gw")) as e:
            e.projects_root = root
            yield e
    finally:
        projects_mod._manager = saved_manager
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _new_run(env) -> str:
    run_id = str(uuid.uuid4())
    env.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
            "VALUES (?, ?, 'factory: demo', 'completed', ?, 0, 1)", (run_id, env.org_id, time.time()))
    return run_id


def _get_when_up(env, run_id, path, timeout=30.0):
    """GET through the preview proxy as `run_id`, waiting for the app to finish booting."""
    env.client.cookies.clear()
    env.client.cookies.set("aether_preview", create_preview_token(run_id, env.org_id))
    deadline = time.time() + timeout
    while True:
        resp = env.client.get(path)
        if resp.headers.get("content-type", "").startswith("application/json") or time.time() > deadline:
            return resp
        time.sleep(0.5)


@pytest.fixture(scope="module")
def launched(env):
    """A generated app started by the real launcher through the real endpoint."""
    run_id = _new_run(env)
    src = env.projects_root / run_id / "p04_backend" / "backend_codegen" / "src"
    src.mkdir(parents=True)
    (src / "main.py").write_text(GENERATED_MAIN)

    resp = env.client.post(f"/factory/runs/{run_id}/run-app", headers=env.auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "started" and body["mode"] == "backend", body
    try:
        yield {"run_id": run_id, **body}
    finally:
        env.client.delete(f"/factory/runs/{run_id}/run-app", headers=env.auth)
        env.client.cookies.clear()


# ── Item 6: child environment ────────────────────────────────────────────────

def test_child_env_is_an_allowlist():
    env_vars = child_env(DATABASE_URL="sqlite:///x.db")
    assert env_vars["DATABASE_URL"] == "sqlite:///x.db"
    assert env_vars["PATH"] == os.environ["PATH"]
    assert set(env_vars) <= {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "DATABASE_URL"}


def test_generated_app_starts_without_platform_secrets(env, launched):
    resp = _get_when_up(env, launched["run_id"], "/app-preview/env")
    assert resp.status_code == 200, resp.text
    child = resp.json()

    for name, value in PLATFORM_SECRETS.items():
        assert os.environ[name] == value          # set in the parent…
        assert name not in child, name            # …absent from the child
    assert "AETHER_SECRET_KEY" not in child and "RAZORPAY_KEY_SECRET" not in child
    leaked = [k for k, v in child.items() if "platform-secret" in v or "PLATFORMSECRET" in v]
    assert leaked == []
    # The app's own values, set by the launcher — not the platform's database.
    assert child["DATABASE_URL"].endswith(f"{launched['run_id']}/preview.db")
    assert child["DATABASE_URL"] != os.environ["DATABASE_URL"]
    assert child["PYTHONPATH"].endswith("backend_codegen/src")
    assert child["PATH"] == os.environ["PATH"]


# ── Item 4: the proxy is bound to the launched process ───────────────────────

def test_state_records_pid_and_nonce_of_the_launched_process(env, launched):
    state = json.loads(preview_state.state_path(launched["run_id"]).read_text())
    assert state["pid"] == launched["pid"] and state["port"] == launched["port"]
    assert len(state["nonce"]) == 32
    assert preview_state.is_launched_process(state["pid"], state["nonce"])
    assert not preview_state.is_launched_process(state["pid"], "0" * 32)
    assert not preview_state.is_launched_process(os.getpid(), state["nonce"])


def test_proxy_does_not_expose_the_nonce(env, launched):
    resp = _get_when_up(env, launched["run_id"], "/app-preview/health")
    assert resp.json() == {"status": "ok"}
    assert preview_state.NONCE_HEADER not in resp.headers


@pytest.fixture
def no_restart(monkeypatch):
    """Record auto-restart requests instead of launching anything."""
    calls = []

    async def _fake_launch(run_id, user):
        calls.append(run_id)

    monkeypatch.setattr(app_preview_router, "_launch_generated_app", _fake_launch)
    return calls


def _preview_as(env, run_id):
    env.client.cookies.clear()
    env.client.cookies.set("aether_preview", create_preview_token(run_id, env.org_id))


def _write_state(env, run_id, **state):
    path = preview_state.state_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_id": run_id, "mode": "backend", **state}))


@pytest.mark.parametrize("case", ["wrong_nonce", "no_nonce", "wrong_pid"])
def test_stale_state_pointing_at_another_runs_app_is_treated_as_down(env, launched, no_restart, case):
    """A second run whose stale state file names the first run's live port (port reuse)."""
    up = _get_when_up(env, launched["run_id"], "/app-preview/health")
    assert up.json() == {"status": "ok"}                     # the first run's app is up
    real = json.loads(preview_state.state_path(launched["run_id"]).read_text())
    stale_run = _new_run(env)
    state = {
        "wrong_nonce": {"port": real["port"], "pid": real["pid"], "nonce": "f" * 32},
        "no_nonce": {"port": real["port"], "pid": real["pid"]},                     # pre-fix file format
        "wrong_pid": {"port": real["port"], "pid": os.getpid(), "nonce": real["nonce"]},
    }[case]
    _write_state(env, stale_run, **state)
    assert preview_state.live_port(stale_run) is None

    _preview_as(env, stale_run)
    try:
        resp = env.client.get("/app-preview/env")
        assert "application/json" not in resp.headers.get("content-type", "")   # never reached the other app
        assert "Starting generated app" in resp.text
        assert no_restart == [stale_run]
    finally:
        env.client.cookies.clear()


def test_dead_process_is_treated_as_down(env, no_restart):
    run_id = _new_run(env)
    nonce = preview_state.new_nonce()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                             *preview_state.nonce_args(nonce)])
    try:
        _write_state(env, run_id, port=59999, pid=proc.pid, nonce=nonce)
        assert preview_state.live_port(run_id) == 59999        # alive and carrying the nonce
    finally:
        proc.send_signal(signal.SIGKILL)
        proc.wait()
    assert preview_state.live_port(run_id) is None

    _preview_as(env, run_id)
    try:
        assert "Starting generated app" in env.client.get("/app-preview/").text
        assert no_restart == [run_id]
    finally:
        env.client.cookies.clear()


def test_never_launched_run_gets_503_and_no_restart(env, no_restart):
    run_id = _new_run(env)
    _preview_as(env, run_id)
    try:
        assert env.client.get("/app-preview/").status_code == 503
        assert no_restart == []
    finally:
        env.client.cookies.clear()


def test_dead_child_handle_is_not_trusted(env):
    run_id = _new_run(env)
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    app_state.set_proc(run_id, proc)
    app_state.set_port(run_id, 59998)
    try:
        assert preview_state.live_port(run_id) is None
    finally:
        app_state.del_proc(run_id)
        app_state.del_port(run_id)
