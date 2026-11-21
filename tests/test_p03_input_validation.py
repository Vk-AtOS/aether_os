"""KAN-97: github_url and project_name from the request are validated."""
import asyncio
from types import SimpleNamespace

import pytest

from aether_os.phases.p03_scaffolding import task_agent
from aether_os.phases.p03_scaffolding.validation import (
    is_valid_project_name, safe_project_name, validate_clone_url)


@pytest.mark.parametrize("url", [
    "file:///etc", "/srv/repo", "../x", "--upload-pack=touch /tmp/x", "ssh://git@github.com/a/b",
    "http://github.com/a/b", "https://evil.example/a/b", "https://user:pw@github.com/a/b",
    "https://github.com:22/a/b", "https://github.com/a b", "ext::sh -c id", "",
])
def test_bad_urls_rejected(url):
    with pytest.raises(ValueError):
        validate_clone_url(url)


def test_good_url_and_configured_host(monkeypatch):
    assert validate_clone_url("https://github.com/a/b.git")
    monkeypatch.setenv("GIT_CLONE_ALLOWED_HOSTS", "git.corp.example")
    assert validate_clone_url("https://git.corp.example/a/b")
    with pytest.raises(ValueError):
        validate_clone_url("https://github.com/a/b")


@pytest.mark.parametrize("n", ["../x", "a/b", "..", ".hidden", "a\\b", "x" * 65, ""])
def test_bad_project_names(n):
    assert not is_valid_project_name(n)


def test_safe_project_name_is_one_component():
    for n in ["../../etc", "a/b", "..", "", "ok name"]:
        s = safe_project_name(n)
        assert "/" not in s and s not in ("", "..", ".")


def test_router_rejects_bad_input():
    from pydantic import ValidationError
    from aether_os.gateway.routers.factory_start_router import FactoryStartRequest
    with pytest.raises(ValidationError):
        FactoryStartRequest(project_name="../x")
    with pytest.raises(ValidationError):
        FactoryStartRequest(github_url="file:///etc")
    assert FactoryStartRequest(project_name="Todo REST API", github_url="").project_name


def test_p03_refuses_local_clone(tmp_path):
    pi = SimpleNamespace(project_id="p", input_data={"github_url": "file:///tmp/x", "project_name": "n"})
    res = asyncio.run(task_agent.run(pi, [], tmp_path))
    assert res.success is False and not (tmp_path / "n").exists()


def test_clone_is_shallow_time_limited_and_after_double_dash(tmp_path, monkeypatch):
    """KAN-97 accepted design: the clone runs on the host with a validated https URL, depth 1 and a timeout."""
    seen = {}

    def fake_run(cmd, **kw):
        if "clone" in cmd:  # the fallback scaffold also runs `git init`
            seen["cmd"], seen["kw"] = cmd, kw
        return SimpleNamespace(returncode=1, stderr="stop", stdout="")

    monkeypatch.setattr(task_agent, "check_https_remote_pinned",
                        lambda url: SimpleNamespace(git_args=lambda: []))
    monkeypatch.setattr(task_agent.subprocess, "run", fake_run)
    pi = SimpleNamespace(project_id="p", input_data={"github_url": "https://github.com/a/b", "project_name": "n"})
    asyncio.run(task_agent.run(pi, [], tmp_path))
    cmd = seen["cmd"]
    assert "--depth=1" in cmd and cmd.index("--") < cmd.index("https://github.com/a/b")
    assert "protocol.allow=never" in cmd and 0 < seen["kw"]["timeout"] <= 60
