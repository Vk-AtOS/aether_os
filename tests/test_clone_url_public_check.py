"""KAN-69: every clone of a user-supplied URL goes through the shared public-address check (core/security/git_remote,
safe_http), not only a host allow-list; the p08 repo manager had no check at all and sent tokens by substring."""
import asyncio
import base64
import subprocess
from types import SimpleNamespace

import pytest

from aether_os.core.security.git_remote import HttpsRemote, check_https_remote, check_https_remote_pinned
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
    auths = []
    monkeypatch.setattr(RepoManager, "_run_git", lambda self, args, cwd=None, pin=None, auth=None:
                        (seen.append(args), auths.append(auth or {})) and "")
    mgr = RepoManager(str(tmp_path))
    for bad in ("https://127.0.0.1/x/y.git", "file:///srv/repo", "https://169.254.169.254/github.com/y"):
        with pytest.raises(RepoError):
            mgr.clone_or_pull(bad)
    assert not seen
    with pytest.raises(RepoError):
        mgr.clone_or_pull("https://8.8.8.8/org/repo.git", commit_sha="--orphan")
    # the token goes only to the real github.com host, never by substring, and never inside the URL (KAN-122)
    monkeypatch.setattr("aether_os.phases.p08_cicd.repo.git_manager.check_https_remote_pinned",
                        lambda u: HttpsRemote(u, "x", ("8.8.8.8",)))
    mgr.clone_or_pull("https://evil.example/github.com/repo.git")
    mgr.clone_or_pull("https://github.com/org/ok.git")
    assert [a[2] for a in seen] == ["https://evil.example/github.com/repo.git", "https://github.com/org/ok.git"]
    assert "tok-123" not in str(seen)
    assert auths[0] == {} and auths[1]["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert base64.b64decode(auths[1]["GIT_CONFIG_VALUE_0"].rsplit(" ", 1)[1]) == b"x-access-token:tok-123"


def test_https_clone_is_pinned_to_the_checked_address(tmp_path, monkeypatch):
    """KAN-69: the ssh path pinned the checked address, https did not, so DNS could change between the check and
    git's own lookup (rebinding). git is now told host:443:address for the clone, with redirects off."""
    from aether_os.core.security import git_remote
    monkeypatch.setattr(git_remote, "resolve_public", lambda url: (None, ["93.184.216.34", "2606:2800:220:1::1"]))
    remote = check_https_remote_pinned("https://Example.COM/a/b.git")
    assert remote.git_args() == ["-c", "http.curloptResolve=example.com:443:93.184.216.34,[2606:2800:220:1::1]",
                                 "-c", "http.followRedirects=false"]
    seen = []

    async def fake_to_thread(fn, *a, **k):
        if fn is subprocess.run:
            seen.append(a[0])
            return SimpleNamespace(returncode=1, stderr="", stdout="")
        return fn(*a, **k)
    monkeypatch.setattr(task_agent.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setenv("GIT_CLONE_ALLOWED_HOSTS", "example.com")
    pi = SimpleNamespace(project_id="p", input_data={"github_url": "https://example.com/a/b.git", "project_name": "n"})
    asyncio.run(task_agent.run(pi, [], tmp_path))
    assert seen and "http.curloptResolve=example.com:443:93.184.216.34,[2606:2800:220:1::1]" in seen[0]
    assert seen[0].index("http.curloptResolve=example.com:443:93.184.216.34,[2606:2800:220:1::1]") < seen[0].index("clone")


def test_git_really_connects_to_the_pinned_address_not_to_dns(tmp_path):
    out = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.split()[-1].split(".")
    if tuple(int(x) for x in out[:2] if x.isdigit()) < (2, 37):
        pytest.skip("git older than 2.37 has no http.curloptResolve")
    p = subprocess.run(["git", "-c", "http.curloptResolve=pin.invalid:443:127.0.0.1", "-c", "http.followRedirects=false",
                        "ls-remote", "https://pin.invalid/x.git"], capture_output=True, text=True, timeout=60,
                       env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)})
    assert p.returncode != 0 and "resolve host" not in p.stderr.lower(), p.stderr    # refused connection, not a DNS miss
