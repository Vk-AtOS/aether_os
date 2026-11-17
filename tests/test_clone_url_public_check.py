"""KAN-69: every clone of a user-supplied URL goes through the shared public-address check (core/security/git_remote,
safe_http), not only a host allow-list; the p08 repo manager had no check at all and sent tokens by substring."""
import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from aether_os.core.security.git_remote import check_https_remote
from aether_os.core.security.safe_http import UnsafeURL
from aether_os.phases.p03_scaffolding import task_agent
from aether_os.phases.p08_cicd.repo.git_manager import RepoError, RepoManager


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/a/b", "https://169.254.169.254/x", "https://[::1]/a", "https://localhost/a",
    "https://10.0.0.5/a/b", "http://github.com/a/b", "https://u:p@github.com/a/b", "https://github.com:22/a",
    "file:///etc/passwd", "--upload-pack=x", "ssh://git@github.com/a/b", "https://exa mple.com/a",
])
def test_https_remote_refuses_unsafe_urls(url):
    with pytest.raises(UnsafeURL):
        check_https_remote(url)


def test_https_remote_accepts_a_public_literal():
    assert check_https_remote("https://8.8.8.8/a/b.git") == "https://8.8.8.8/a/b.git"


def test_p03_refuses_an_allow_listed_host_that_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CLONE_ALLOWED_HOSTS", "10.0.0.5")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=1, stderr=""))
    pi = SimpleNamespace(project_id="p", input_data={"github_url": "https://10.0.0.5/a/b", "project_name": "n"})
    res = asyncio.run(task_agent.run(pi, [], tmp_path))
    assert res.success is False and not calls


def test_repo_manager_checks_the_url_and_keeps_tokens_for_their_own_host(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok-123")
    seen = []
    monkeypatch.setattr(RepoManager, "_run_git", lambda self, args, cwd=None: seen.append(args) or "")
    mgr = RepoManager(str(tmp_path))
    for bad in ("https://127.0.0.1/x/y.git", "file:///srv/repo", "https://169.254.169.254/github.com/y"):
        with pytest.raises(RepoError):
            mgr.clone_or_pull(bad)
    assert not seen
    with pytest.raises(RepoError):
        mgr.clone_or_pull("https://8.8.8.8/org/repo.git", commit_sha="--orphan")
    # the token is embedded only for the real github.com host, never by substring
    monkeypatch.setattr("aether_os.phases.p08_cicd.repo.git_manager.check_https_remote", lambda u: u)
    mgr.clone_or_pull("https://evil.example/github.com/repo.git")
    mgr.clone_or_pull("https://github.com/org/ok.git")
    urls = [a[2] for a in seen if a[0] == "clone"]
    assert "tok-123" not in urls[0] and "tok-123" in urls[1], urls
