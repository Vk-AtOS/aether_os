"""KAN-110: the CLI must call routes the gateway really serves, and must not print success after a failure."""
import io
import re
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from typer.testing import CliRunner

from aether_os.cli import aetheros

CFG = {"url": "http://gw", "token": "t", "email": "a@b.c"}


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _http_error(status, text):
    resp = MagicMock(status_code=status, text=text)
    return requests.HTTPError(f"{status}", response=resp)


def _invoke(args, get=None, post=None):
    with patch.object(aetheros, "_load_cfg", lambda: dict(CFG)), \
         patch.object(aetheros, "_get", get or MagicMock()), patch.object(aetheros, "_post", post or MagicMock()):
        return CliRunner().invoke(aetheros.app, args)


def test_every_cli_path_is_a_gateway_route():
    from aether_os.gateway.api import app
    served = {re.sub(r"\{[^}]+\}", "{}", r.path) for r in app.routes if hasattr(r, "path")}
    src = Path(aetheros.__file__).read_text()
    called = {re.sub(r"\{[^}]+\}", "{}", p) for p in re.findall(r'f?"(?:\{url\})?(/[a-z][\w/{}\-]*)"', src)}
    assert "/factory/runs/{}/download" in called and len(called) >= 10, called
    assert not called - served, f"CLI calls routes the gateway does not serve: {sorted(called - served)}"


def test_download_extracts_the_run_zip(tmp_path):
    paths = []

    def get(cfg, path, **kw):
        paths.append(path)
        return MagicMock(content=_zip({"src/main.py": "print(1)\n", "README.md": "hi"}))

    res = _invoke(["download", "run1", "-o", str(tmp_path / "out")], get=get)
    assert res.exit_code == 0, res.output
    assert paths == ["/factory/runs/run1/download"]
    assert (tmp_path / "out" / "src" / "main.py").read_text() == "print(1)\n"
    assert "2 file(s)" in res.output


def test_download_fails_loudly_on_http_error(tmp_path):
    def get(cfg, path, **kw):
        raise _http_error(404, "Project files not found")

    res = _invoke(["download", "run1", "-o", str(tmp_path / "out")], get=get)
    assert res.exit_code == 1
    assert "Done" not in res.output and "404" in res.output
    assert not (tmp_path / "out").exists()


def test_download_fails_on_empty_or_broken_zip(tmp_path):
    res = _invoke(["download", "run1", "-o", str(tmp_path)], get=lambda *a, **k: MagicMock(content=_zip({})))
    assert res.exit_code == 1 and "Done" not in res.output
    res = _invoke(["download", "run1", "-o", str(tmp_path)], get=lambda *a, **k: MagicMock(content=b"<html>"))
    assert res.exit_code == 1 and "Done" not in res.output


def test_logs_uses_a_one_time_sse_token_and_exits_nonzero_on_error():
    seen = {}

    class _Stream:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_lines(self):
            return [b'data: {"type": "log", "message": "hello"}', b'data: {"type": "pipeline_complete", "status": "failed"}']

    def rget(url, params=None, headers=None, **kw):
        seen.update(url=url, params=params, headers=headers)
        return _Stream()

    post = MagicMock(return_value=MagicMock(json=lambda: {"sse_token": "once"}))
    with patch.object(aetheros.requests, "get", rget):
        res = _invoke(["logs", "run1"], post=post)
    assert res.exit_code == 0, res.output
    assert post.call_args[0][1] == "/factory/runs/run1/sse-token"
    assert seen["params"] == {"sse_token": "once"} and "Authorization" not in seen["headers"]
    assert "hello" in res.output and "failed" in res.output

    def denied(cfg, path, **kw):
        raise _http_error(403, "no")
    assert _invoke(["logs", "run1"], post=denied).exit_code == 1


def test_logout_says_when_the_server_did_not_revoke():
    def post(cfg, path, **kw):
        raise requests.ConnectionError("down")

    with patch.object(aetheros, "_save_cfg", lambda c: None):
        res = _invoke(["logout"], post=post)
    assert "did not revoke" in res.output
