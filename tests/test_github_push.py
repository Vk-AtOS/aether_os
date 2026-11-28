"""KAN-269: the GitHub push sends the whole export in one commit, reports each failed file, and fails loudly."""
import asyncio
import base64
import json
import re

import httpx
import pytest

from aether_os.core import github_push as gp


PEM = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----\n"


def _w(root, rel, text="x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


class FakeGitHub:
    """Just enough of api.github.com for the git data API; records what was sent."""

    def __init__(self, empty=True, fail_content=(), flaky_blob_once=False, rate_limit_first_blob=False):
        self.empty, self.fail_content = empty, set(fail_content)
        self.blobs, self.trees, self.commits, self.refs, self.calls = {}, [], [], [], []
        self.flaky, self.rate = flaky_blob_once, rate_limit_first_blob

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path, body = req.url.path, (json.loads(req.content) if req.content else {})
        self.calls.append((req.method, path))
        if req.method == "GET" and re.search(r"/git/ref/heads/", path):
            return httpx.Response(404 if self.empty else 200, json={"message": "Not Found", "object": {"sha": "head0"}})
        if req.method == "PUT" and "/contents/" in path:
            self.empty = False
            return httpx.Response(201, json={"commit": {"sha": "seed0"}})
        if req.method == "GET" and "/git/commits/" in path:
            return httpx.Response(200, json={"tree": {"sha": "tree0"}})
        if path.endswith("/git/blobs"):
            if self.rate:
                self.rate = False
                return httpx.Response(403, headers={"retry-after": "0"}, json={"message": "API rate limit exceeded"})
            if self.flaky:
                self.flaky = False
                return httpx.Response(502, text="bad gateway")
            if body["content"] in self.fail_content:
                return httpx.Response(422, json={"message": "blob rejected"})
            sha = f"blob{len(self.blobs)}"
            self.blobs[sha] = base64.b64decode(body["content"])
            return httpx.Response(201, json={"sha": sha})
        if path.endswith("/git/trees"):
            self.trees.append(body)
            return httpx.Response(201, json={"sha": f"tree{len(self.trees)}"})
        if path.endswith("/git/commits"):
            self.commits.append(body)
            return httpx.Response(201, json={"sha": "commit1"})
        if req.method == "PATCH" and "/git/refs/heads/" in path:
            self.refs.append(body)
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"message": f"unexpected {req.method} {path}"})


def _push(fake, files, **kw):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as c:
            return await gp.push_files("tok", "octo/app", files, client=c, **kw)
    return asyncio.run(go())


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _s(_):
        return None
    monkeypatch.setattr(gp.asyncio, "sleep", _s)


def _files(n):
    return [("README.md", b"# hi")] + [(f"backend/src/m{i}.py", f"x={i}".encode()) for i in range(n)]


def test_pushes_far_more_than_50_files_in_one_commit():
    fake = FakeGitHub()
    out = _push(fake, _files(400))
    assert out["files_pushed"] == 401 and out["commit_sha"] == "commit1"
    assert len(fake.blobs) == 401
    in_trees = [e["path"] for t in fake.trees for e in t["tree"]]
    assert len(in_trees) == 401 and len(set(in_trees)) == 401                      # every file, once
    assert len(fake.trees) == 3 and fake.trees[0]["base_tree"] == "tree0" and fake.trees[1]["base_tree"] == "tree1"
    assert len(fake.commits) == 1 and fake.commits[0]["parents"] == ["seed0"]       # one commit, on the seed commit
    assert fake.refs == [{"sha": "commit1"}]


def test_existing_branch_is_used_as_parent_without_seeding():
    fake = FakeGitHub(empty=False)
    _push(fake, _files(3))
    assert fake.commits[0]["parents"] == ["head0"] and ("PUT", "/repos/octo/app/contents/README.md") not in fake.calls


def test_failed_files_are_reported_and_nothing_is_committed():
    bad = base64.b64encode(b"x=7").decode()
    fake = FakeGitHub(fail_content={bad})
    with pytest.raises(gp.PushError) as e:
        _push(fake, _files(20))
    assert [x["path"] for x in e.value.errors] == ["backend/src/m7.py"]
    assert e.value.errors[0]["status"] == 422 and "blob rejected" in e.value.errors[0]["message"]
    assert not fake.trees and not fake.commits and not fake.refs                    # fail loudly, no half project


def test_rate_limit_and_5xx_are_retried():
    fake = FakeGitHub(flaky_blob_once=True, rate_limit_first_blob=True)
    out = _push(fake, _files(5))
    assert out["files_pushed"] == 6 and len(fake.blobs) == 6


def test_empty_export_and_ref_update_failure_raise():
    with pytest.raises(gp.PushError, match="nothing to push"):
        _push(FakeGitHub(), [])
    fake = FakeGitHub()
    orig = fake.__call__
    fake_fail = lambda r: httpx.Response(422, json={"message": "not fast forward"}) if r.method == "PATCH" else orig(r)  # noqa: E731
    with pytest.raises(gp.PushError, match="not fast forward"):
        _push(fake_fail, _files(2))


def test_route_pushes_the_clean_export_not_the_workspace(tmp_path, monkeypatch):
    from aether_os.gateway.routers import run_preview_router as r
    home = tmp_path / "home"
    ws = home / ".aether_os/projects/run1"
    _w(ws, "p04_backend/backend_codegen/src/main.py", "app = 1")
    _w(ws, "p04_backend/backend_codegen/requirements.txt", "fastapi\n")
    _w(ws, "p04_backend/backend_codegen/private_key.pem", PEM)
    _w(ws, "p04_backend/backend_codegen/.env", "SECRET_KEY=abcdefabcdef")
    for i in range(80):
        _w(ws, f"p04_backend/backend_codegen/src/routers/r{i}.py", f"x={i}")
    monkeypatch.setenv("HOME", str(home))

    class _Res:
        def scalar_one_or_none(self):
            return type("R", (), {"project_name": "My App"})()

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *_a):
            return _Res()

    monkeypatch.setattr(r, "get_session_factory", lambda: (lambda: _Sess()))
    fake = FakeGitHub()

    def handler(req):
        p = req.url.path
        if p == "/user/repos":
            return httpx.Response(201, json={})
        if p == "/user":
            return httpx.Response(200, json={"login": "octo"})
        if p == "/repos/octo/app":
            return httpx.Response(200, json={"html_url": "https://github.com/octo/app", "default_branch": "main"})
        return fake(req)

    real = httpx.AsyncClient
    monkeypatch.setattr(r.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    out = asyncio.run(r.push_run_to_github("run1", {"github_token": "t", "repo_name": "app"}, {"org_id": "o"}))
    pushed = b"".join(fake.blobs.values())
    assert out["files_pushed"] > 80 and out["html_url"] == "https://github.com/octo/app"
    assert b"SECRET_KEY=abcdefabcdef" not in pushed and b"BEGIN PRIVATE KEY" not in pushed

    bad = base64.b64encode(b"x=3").decode()
    fake2 = FakeGitHub(fail_content={bad})
    fake = fake2          # the handler closure reads this name, so the second push meets a failing blob
    with pytest.raises(Exception) as e:
        asyncio.run(r.push_run_to_github("run1", {"github_token": "t", "repo_name": "app"}, {"org_id": "o"}))
    assert getattr(e.value, "status_code", None) == 502 and e.value.detail["errors"][0]["path"].endswith("r3.py")
