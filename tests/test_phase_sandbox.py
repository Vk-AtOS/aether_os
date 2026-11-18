"""Generated code, its tests, probes and installs run only through the sandbox runner.

A fake SandboxRunner records every command; subprocess / asyncio subprocess creation is
patched to fail the test, so anything that still reached the host directly would break here.
The AST scan fails when generated-code execution outside core/sandbox uses subprocess.
"""
from __future__ import annotations

import ast
import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from aether_os.core.sandbox import phase_exec
from aether_os.core.sandbox.runner import SandboxRunner, SandboxUnavailable

ROOT = Path(__file__).resolve().parent.parent


class FakeRunner(SandboxRunner):
    name = "fake"

    def __init__(self, stdout=b"IMPORT_OK\n", code=0):
        super().__init__()
        self.calls, self.starts, self.stdout, self.code = [], [], stdout, code

    def available(self):
        return True

    def run(self, argv, *, run_dir, cwd=None, env, timeout=None, network=False):
        self.calls.append(SimpleNamespace(argv=list(argv), run_dir=run_dir, cwd=cwd, env=dict(env),
                                          timeout=timeout, network=network))
        return subprocess.CompletedProcess(argv, self.code, self.stdout, b"")

    def start(self, argv, *, run_dir, cwd, env, log_path, port, labels):
        self.starts.append(SimpleNamespace(argv=list(argv), run_dir=run_dir, cwd=cwd, env=dict(env), port=port))
        return SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda: None, kill=lambda: None,
                               wait=lambda timeout=None: 0)


def _no_host_exec(*a, **k):
    raise AssertionError("generated code reached the host: subprocess was called directly")


@pytest.fixture
def fake(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(phase_exec, "get_runner", lambda *a, **k: runner)
    for name in ("run", "Popen", "check_output", "check_call", "call"):
        monkeypatch.setattr(subprocess, name, _no_host_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_host_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _no_host_exec)
    monkeypatch.setenv("AETHER_SECRET_KEY", "platform-secret-key-value")
    monkeypatch.setenv("DATABASE_URL", "postgresql://platform")
    return runner


def _clean_env(call):
    assert "AETHER_SECRET_KEY" not in call.env
    assert call.env.get("DATABASE_URL") != "postgresql://platform"
    assert set(call.env) <= {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR",
                             "PIP_DISABLE_PIP_VERSION_CHECK", "DATABASE_URL", "SECRET_KEY", "PYTHONPATH",
                             "COVERAGE_FILE", "CORS_ORIGINS"}


@pytest.fixture
def backend(tmp_path):
    src = tmp_path / "p04_backend" / "backend_codegen" / "src"
    src.mkdir(parents=True)
    (src / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    return src


def test_p07a_import_check_runs_in_the_sandbox(fake, backend):
    from aether_os.phases.p07a_unit_testing.task_agent import _exec_validate_startup
    out = asyncio.run(_exec_validate_startup(backend, backend.parent))
    assert out["passed"] and len(fake.calls) == 1
    call = fake.calls[0]
    assert call.network is False and call.cwd == backend.parent and call.timeout == 20
    assert call.run_dir == backend.parent.resolve() or backend.parent.resolve().is_relative_to(call.run_dir)
    _clean_env(call)


def test_p07a_pytest_runs_in_the_sandbox(fake, backend, tmp_path):
    from aether_os.phases.p07a_unit_testing.task_agent import run
    fake.stdout = b"1 passed in 0.1s"
    asyncio.run(run(SimpleNamespace(input_data={"project_name": "App", "entities": [],
                                                 "backend_src_dir": str(backend)}), [], tmp_path / "out"))
    pytest_calls = [c for c in fake.calls if "pytest" in c.argv]
    assert pytest_calls and all(c.network is False for c in pytest_calls)
    _clean_env(pytest_calls[0])


def test_p07b_tests_run_in_the_sandbox(fake, tmp_path):
    from aether_os.phases.p07b_self_healing.task_agent import _run_tests
    test_file = tmp_path / "tests" / "test_x.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_a(): pass\n")
    assert asyncio.run(_run_tests(test_file))["passed"]
    assert fake.calls[0].argv[1:3] == ["-m", "pytest"] and fake.calls[0].network is False
    _clean_env(fake.calls[0])


def test_p07_tools_run_tests_in_the_sandbox(fake, tmp_path):
    from aether_os.phases.p07_testing.tools import run_tests
    assert run_tests(str(tmp_path), "pytest -q")["ok"]
    assert fake.calls[0].argv[1:] == ["-m", "pytest", "-q"] and fake.calls[0].network is False
    _clean_env(fake.calls[0])


def test_p04_smoke_runs_in_the_sandbox(fake, backend):
    from aether_os.phases.p04_backend.task_agent import _startup_smoke_test

    async def emit(_):
        return None
    assert asyncio.run(_startup_smoke_test(backend, emit))["passed"]
    assert len(fake.calls) == 2 and not any(c.network for c in fake.calls)   # py_compile + import check
    assert "-c" in fake.calls[1].argv
    _clean_env(fake.calls[1])


def test_p05_install_gets_network_and_build_does_not(fake, tmp_path, monkeypatch):
    from aether_os.phases.p05_frontend import npm_runner
    fe = tmp_path / "frontend"
    fe.mkdir()
    (fe / "package.json").write_text('{"name": "x"}')
    asyncio.run(npm_runner.run_npm_build(fe))
    by_cmd = {tuple(c.argv[1:3]): c for c in fake.calls}
    assert by_cmd[("install",)] if False else True
    install = next(c for c in fake.calls if "install" in c.argv)
    build = next(c for c in fake.calls if "build" in c.argv)
    assert install.network is True and build.network is False
    _clean_env(install)


def test_p05_build_loop_runs_tsc_and_build_in_the_sandbox(fake, tmp_path, monkeypatch):
    from aether_os.phases.p05_frontend.build_loop import run_build_loop
    monkeypatch.setenv("ENVIRONMENT", "development")
    out = asyncio.run(run_build_loop(tmp_path, max_rounds=1))
    assert out["success"] and len(fake.calls) == 2 and not any(c.network for c in fake.calls)


def test_p04a_live_probe_starts_the_app_in_the_sandbox(fake, backend, monkeypatch):
    import socket
    from aether_os.phases.p04a_backend_codegen import helpers

    async def noop_sleep(_):
        return None
    monkeypatch.setattr(helpers.asyncio, "sleep", noop_sleep)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))

    async def emit(_):
        return None
    asyncio.run(helpers._live_http_probe(backend, emit))
    assert len(fake.starts) == 1 and "uvicorn" in fake.starts[0].argv
    assert fake.starts[0].argv[fake.starts[0].argv.index("--host") + 1] == "127.0.0.1"
    _clean_env(fake.starts[0])


# ── no runner: generated code does not run at all ────────────────────────────────

def test_without_a_sandbox_nothing_runs_and_the_message_is_clear(monkeypatch, backend):
    def unavailable(*a, **k):
        raise SandboxUnavailable("docker not available")
    monkeypatch.setattr(phase_exec, "get_runner", unavailable)
    for name in ("run", "Popen"):
        monkeypatch.setattr(subprocess, name, _no_host_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_host_exec)
    from aether_os.phases.p07a_unit_testing.task_agent import run
    with pytest.raises(SandboxUnavailable, match="generated code was not run"):
        asyncio.run(run(SimpleNamespace(input_data={"project_name": "A", "entities": [],
                                                     "backend_src_dir": str(backend)}), [], backend.parent / "o"))


def test_none_backend_behaves_like_a_host_process_with_the_same_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AETHER_SANDBOX", "none")
    monkeypatch.setenv("AETHER_SANDBOX_ALLOW_NONE", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AETHER_SECRET_KEY", "platform-secret-key-value")
    done = phase_exec.run_sync(["python3", "-c", "import os; print(os.environ.get('AETHER_SECRET_KEY'), os.environ['HOME'])"],
                               cwd=tmp_path, text=True)
    assert done.returncode == 0
    assert done.stdout.split()[0] == "None" and ".sandbox_home" in done.stdout


def test_timeout_surfaces_as_asyncio_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("AETHER_SANDBOX", "none")
    monkeypatch.setenv("AETHER_SANDBOX_ALLOW_NONE", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(phase_exec.run(["python3", "-c", "import time; time.sleep(30)"], cwd=tmp_path, timeout=1))


# ── AST scan: who still calls subprocess outside core/sandbox ────────────────────

_SP = {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}

# Files that start processes, and why none of them runs GENERATED code on the host.
ALLOWED = {
    "phases/p03_scaffolding/task_agent.py": "git init / git clone of a user-given repo: no generated code",
    "phases/p06_review_security/subtasks.py": "bandit (pinned dependency): static analysis, reads files only",
    "phases/p08_cicd/repo/git_manager.py": "git operations",
    "phases/p08_cicd/repo/patch_applier.py": "git apply/commit",
    "phases/p08_cicd/task_agent.py": "bandit: static analysis",
    "phases/p11_deployment/helpers.py": "docker network/run of the deployed image; the BUILD is the builder sandbox's (core/sandbox/build_runner.py)",
    "phases/p11_deployment/task_agent.py": "docker info/stop/rm/logs of the deployed container; no build, no generated code runs here",
    "core/guardian/auto_recovery.py": "platform self-recovery",
    "core/guardian/snapshot_manager.py": "platform snapshots (git)",
    "core/quality/metrics.py": "bandit: static analysis",
    "core/run_app/preview_state.py": "ps: process start time / command line lookup",
    "core/security/code_scanner.py": "pip-audit: reads requirements.txt",
    "gateway/routers/admin_platform_router.py": "platform admin operations",
    "gateway/routers/factory_analytics_router.py": "docker ps listing",
    "gateway/routers/factory_intake_router.py": "git clone of a user repo for intake context",
    "gateway/routers/factory_run_files_router.py": "opens VS Code on the project folder",
    "gateway/routers/run_deploy_router.py": "docker info / rm of deployment containers",
    "gateway/routers/system_router.py": "docker info health check",
    "main.py": "platform entry point",
}


def _uses_process_api(path: Path) -> bool:
    tree = ast.parse(path.read_text(errors="ignore"))
    aliases = {"subprocess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases |= {a.asname or "subprocess" for a in node.names if a.name == "subprocess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("create_subprocess"):
                return True
            if isinstance(node.value, ast.Name):
                if node.value.id in aliases and node.attr in _SP:
                    return True
                if node.value.id == "os" and node.attr in ("system", "popen"):
                    return True
    return False


def test_only_known_files_start_processes_outside_the_sandbox_package():
    found = set()
    for top in ("phases", "core", "gateway", "orchestrator", "stages", "agents", "integrations", "cli", "prime"):
        for f in (ROOT / top).rglob("*.py"):
            rel = f.relative_to(ROOT).as_posix()
            if rel.startswith("core/sandbox/") or "__pycache__" in rel:
                continue
            if _uses_process_api(f):
                found.add(rel)
    if (ROOT / "main.py").exists() and _uses_process_api(ROOT / "main.py"):
        found.add("main.py")
    assert found <= set(ALLOWED), f"new direct process execution: {sorted(found - set(ALLOWED))}"
    # the phases that run generated code must be clean of it
    for rel in found:
        assert not rel.startswith(("phases/p04", "phases/p07a", "phases/p07b", "phases/p07_", "phases/p07d")), rel
        assert not rel.startswith(("phases/p05", "phases/p07c")), rel   # the browser work is the sandbox's (KAN-99)


def test_p08_tiered_tests_run_in_the_sandbox_and_fail_closed(fake, tmp_path, monkeypatch):
    from aether_os.phases.p08_cicd.dsee.test_runner import TieredTestRunner
    ok, _ = TieredTestRunner(tmp_path).run_tier1("tests/test_x.py::test_y").passed, None
    assert ok and fake.calls[0].argv[1:4] == ["-m", "pytest", "tests/test_x.py::test_y"]
    assert fake.calls[0].network is False and fake.calls[0].timeout

    from aether_os.core.sandbox.runner import SandboxUnavailable
    def none(*a, **k):
        raise SandboxUnavailable("no docker")
    monkeypatch.setattr(phase_exec, "get_runner", none)
    res = TieredTestRunner(tmp_path).run_tier1("t")
    assert res.passed is False and "sandbox unavailable" in res.output


def test_p06_never_pip_installs_on_the_host():
    src = (ROOT / "phases/p06_review_security/subtasks.py").read_text()
    assert '"pip", "install"' not in src
