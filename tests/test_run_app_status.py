"""run-app status, stop and the restore at startup believe only a process that is
provably this run's launch (own child, or pid + start time) — never the
state file on its own.

Real gateway, real processes; nothing in the code under test is stubbed.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid

import pytest

import aether_os.core.projects as projects_mod
from aether_os.core import app_state
from aether_os.core.run_app import preview_state
from aether_os.gateway.lifespan import register_live_run_app
from aether_os.tests.gateway_env import gateway_env


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("projects")
    saved = projects_mod._manager
    projects_mod._manager = projects_mod.ProjectManager(root=root)
    try:
        with gateway_env(tmp_path_factory.mktemp("gw")) as e:
            e.projects_root = root
            yield e
    finally:
        projects_mod._manager = saved


def _new_run(env) -> str:
    run_id = str(uuid.uuid4())
    env.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
            "VALUES (?, ?, 'factory: demo', 'completed', ?, 0, 1)", (run_id, env.org_id, time.time()))
    return run_id


def _write_state(env, run_id, **state):
    path = preview_state.state_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_id": run_id, "mode": "backend", **state}))


def _sleeper(*extra_args):
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", *extra_args])


def _kill(proc):
    if proc.poll() is None:
        proc.send_signal(signal.SIGKILL)
    proc.wait()


def _status(env, run_id):
    resp = env.client.get(f"/factory/runs/{run_id}/run-app/status", headers=env.auth)
    assert resp.status_code == 200, resp.text
    return resp


@pytest.fixture
def other_app():
    """Some other live process listening on a port: what a stale state file ends up pointing at."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    proc = _sleeper()
    yield {"pid": proc.pid, "port": listener.getsockname()[1], "proc": proc}
    _kill(proc)
    listener.close()


@pytest.mark.parametrize("nonce", [None, "f" * 32])
def test_status_does_not_show_another_process_as_this_runs_app(env, other_app, nonce):
    run_id = _new_run(env)
    state = {"port": other_app["port"], "pid": other_app["pid"], **({"nonce": nonce} if nonce else {})}
    _write_state(env, run_id, **state)

    resp = _status(env, run_id)
    assert resp.json() == {"running": False, "port": None, "pid": None, "preview_url": None}
    assert "aether_preview" not in resp.headers.get("set-cookie", "")   # no preview grant either
    assert run_id not in app_state.get_all_procs() and run_id not in app_state.get_all_ports()


def test_stop_never_signals_a_pid_taken_from_a_stale_state_file(env, other_app):
    run_id = _new_run(env)
    _write_state(env, run_id, port=other_app["port"], pid=other_app["pid"])
    _status(env, run_id)  # used to adopt the pid from the file, so the stop below killed it
    resp = env.client.delete(f"/factory/runs/{run_id}/run-app", headers=env.auth)
    assert resp.json() == {"status": "not_running"}
    time.sleep(0.3)
    assert other_app["proc"].poll() is None, "an unrelated process was killed"


def test_status_and_stop_work_for_an_app_launched_by_an_earlier_gateway_process(env):
    """No child handle in this process; the pid + start time in the state file identify the launch."""
    run_id = _new_run(env)
    nonce = preview_state.new_nonce()
    proc = _sleeper()
    try:
        _write_state(env, run_id, port=20997, pid=proc.pid, nonce=nonce,
                     pid_start=preview_state.process_started(proc.pid))
        resp = _status(env, run_id)
        assert resp.json() == {"running": True, "port": 20997, "pid": proc.pid, "preview_url": "/app-preview/"}
        assert "aether_preview" in resp.headers.get("set-cookie", "")

        stopped = env.client.delete(f"/factory/runs/{run_id}/run-app", headers=env.auth)
        assert stopped.json() == {"status": "stopped", "run_id": run_id}
        proc.wait(timeout=5)
        assert _status(env, run_id).json()["running"] is False
    finally:
        _kill(proc)


def test_restore_at_startup_registers_only_a_verified_launch(env, other_app):
    stale_run, live_run = _new_run(env), _new_run(env)
    nonce = preview_state.new_nonce()
    proc = _sleeper()
    try:
        # Stale file, newest on disk, naming a port that something else is listening on:
        # the old socket probe registered it.
        _write_state(env, stale_run, port=other_app["port"], pid=other_app["pid"])
        assert asyncio.run(register_live_run_app(env.projects_root)) is None
        assert stale_run not in app_state.get_all_ports()

        _write_state(env, live_run, port=20996, pid=proc.pid, nonce=nonce,
                     pid_start=preview_state.process_started(proc.pid))
        os.utime(preview_state.state_path(live_run), (1, 1))  # older than the stale one
        assert asyncio.run(register_live_run_app(env.projects_root)) == live_run
        assert app_state.get_all_ports().get(live_run) == 20996
        assert stale_run not in app_state.get_all_ports()
    finally:
        app_state.del_port(live_run)
        _kill(proc)
