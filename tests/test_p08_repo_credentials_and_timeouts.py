"""KAN-122: the p08 repo helpers must not put a token in the clone URL and must not call an API without a timeout."""
import subprocess
from types import SimpleNamespace

from aether_os.core.security.git_remote import HttpsRemote
from aether_os.phases.p08_cicd.repo import git_manager, pr_creator
from aether_os.phases.p08_cicd.repo.git_manager import RepoManager


def _pinned(monkeypatch):
    monkeypatch.setattr(git_manager, "check_https_remote_pinned", lambda u: HttpsRemote(u, "github.com", ("8.8.8.8",)))


def test_token_is_in_no_argv_and_only_in_the_git_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    _pinned(monkeypatch)
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw["env"]))
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    monkeypatch.setattr(git_manager.subprocess, "run", fake_run)
    mgr = RepoManager(str(tmp_path))
    path = mgr.clone_or_pull("https://github.com/org/app.git")
    git_manager.Path(path).mkdir()
    mgr.clone_or_pull("https://github.com/org/app.git")       # the update path: fetch + pull
    assert len(calls) == 3
    for argv, env in calls:
        assert "ghp_secret" not in " ".join(argv) and "@" not in " ".join(argv)
        assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert not any("set-url" in argv for argv, _ in calls)     # nothing writes a credential into .git/config


def test_git_sends_the_header_to_its_own_host_only(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(tmp_path), **git_manager._auth_env("github.com")}

    def header_for(url):
        return subprocess.run(["git", "config", "--get-urlmatch", "http.extraheader", url],
                              capture_output=True, text=True, env=env).stdout
    assert header_for("https://github.com/org/app.git").startswith("Authorization: Basic ")
    assert header_for("https://evil.example/github.com/app.git") == ""
    assert git_manager._auth_env("evil.example") == {}


def test_two_repositories_with_the_same_name_do_not_share_a_cache_directory(tmp_path, monkeypatch):
    _pinned(monkeypatch)
    monkeypatch.setattr(RepoManager, "_run_git", lambda self, *a, **k: "")
    mgr = RepoManager(str(tmp_path))
    assert mgr.clone_or_pull("https://github.com/org-a/app.git") != mgr.clone_or_pull("https://github.com/org-b/app.git")


def test_default_cache_is_not_under_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(git_manager.Path, "home", classmethod(lambda cls: tmp_path))
    mgr = RepoManager()
    assert mgr.cache_dir == tmp_path / ".aether_os" / "repo_cache"
    assert mgr.cache_dir.stat().st_mode & 0o077 == 0


def test_pr_and_mr_calls_have_a_timeout(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(timeout)
        raise OSError("stop here")
    monkeypatch.setattr(pr_creator.urllib.request, "urlopen", fake_urlopen)
    c = pr_creator.PRCreator("org/app", token="t")
    assert not c.create_github_pr("b", "t", "body").success
    assert not c.create_gitlab_mr("b", "t", "body").success
    assert seen == [pr_creator._TIMEOUT_S, pr_creator._TIMEOUT_S] and pr_creator._TIMEOUT_S > 0
