"""ssh git intake must not let a member make the server connect to internal addresses (both URL forms)."""
import socket

import pytest

from aether_os.core.security.git_remote import check_ssh_remote, ssh_command
from aether_os.core.security.safe_http import UnsafeURL

BAD = [
    "git@127.0.0.1:org/repo.git", "ssh://git@127.0.0.1/org/repo.git", "git@169.254.169.254:x", "ssh://169.254.169.254/x",
    "git@10.0.0.5:org/r.git", "ssh://10.1.2.3:22/r", "git@localhost:r.git", "ssh://localhost/r", "ssh://git@[::1]/r",
    "ssh://git@github.com:6379/r.git", "ssh://github.com:2222/r.git", "git@192.168.1.1:r", "ssh://metadata.google.internal/r",
    "file:///etc/passwd", "/srv/repo", "../repo", "-oProxyCommand=x", "ext::sh -c id", "http://github.com/x", "", "user@host",
    "ssh://user:pw@github.com/r",
]


@pytest.mark.parametrize("url", BAD)
def test_bad_remotes_are_refused(url):
    with pytest.raises(UnsafeURL):
        check_ssh_remote(url)


def test_hostname_resolving_to_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.7", 22))])
    with pytest.raises(UnsafeURL):
        check_ssh_remote("git@internal.example.com:org/repo.git")


def test_public_remote_in_both_forms_is_pinned(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("140.82.112.3", 22))])
    for u in ("git@github.com:org/repo.git", "ssh://git@github.com/org/repo.git", "ssh://git@github.com:22/org/repo.git"):
        r = check_ssh_remote(u)
        assert (r.host, r.port, r.address) == ("github.com", 22, "140.82.112.3")
    cmd = ssh_command("/k", r)
    assert "HostName=140.82.112.3" in cmd and "HostKeyAlias=github.com" in cmd and "-F /dev/null" in cmd


def test_port_allowlist_is_configurable(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("140.82.112.3", 22))])
    monkeypatch.setenv("GIT_SSH_ALLOWED_PORTS", "22,7999")
    assert check_ssh_remote("ssh://git@bitbucket.example.com:7999/p/r.git").port == 7999


def test_endpoint_refuses_before_any_process_and_hides_stderr(gw, monkeypatch):
    import asyncio
    org = gw.register("gitorg")
    called = []

    async def boom(*a, **k):
        called.append(a)
        raise AssertionError("git must not run")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    for u in ("git@127.0.0.1:x/y.git", "ssh://169.254.169.254/x"):
        r = gw.client.post("/factory/fetch-repo", headers=org.auth, json={"type": "ssh", "url": u, "ssh_key": "k"})
        assert r.status_code == 422 and "127.0.0.1" not in r.text and "169.254" not in r.text
    assert not called


HOSTILE = ["a b", "a;id", "a$(id)", "a`id`", "-oProxyCommand=x", "a'b", 'a"b', "a|b", "a&b", "a\\b", "ex\u0430mple.com",
           "exa\u202empl.com", "a" * 300 + ".com", "a..", ".a", "a_b", "a\nb", "a\tb", "a{b}", "a*b"]


@pytest.mark.parametrize("host", HOSTILE)
def test_hostile_hosts_never_reach_the_command_line(host, monkeypatch):
    import asyncio
    import subprocess
    spawned = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **k: spawned.append(a))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("140.82.112.3", 22))])
    for url in (f"ssh://git@{host}/r.git", f"git@{host}:org/r.git", f"{host}:org/r.git"):
        with pytest.raises(UnsafeURL):
            check_ssh_remote(url)
    assert not spawned


def test_ssh_command_is_fully_quoted_and_rejects_a_forged_remote():
    import shlex
    from aether_os.core.security.git_remote import SshRemote
    good = ssh_command("/tmp/k y/id", SshRemote("github.com", 22, "140.82.112.3"))
    assert shlex.split(good)[:3] == ["ssh", "-F", "/dev/null"] and "/tmp/k y/id" in shlex.split(good)
    for bad in (SshRemote("a;id", 22, "1.2.3.4"), SshRemote("github.com", 22, "1.2.3.4;id"), SshRemote("-oX=1", 22, "1.2.3.4")):
        with pytest.raises((UnsafeURL, ValueError)):
            ssh_command("/k", bad)
    with pytest.raises(UnsafeURL):
        ssh_command("relative; id", SshRemote("github.com", 22, "1.2.3.4"))
