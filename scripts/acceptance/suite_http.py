"""KAN-266: the HTTP pieces of the suite (stdlib only): the platform API client and the generated-app probes."""
from __future__ import annotations

import http.cookiejar
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional, Tuple

from acceptance.suite_checks import Resp
from acceptance.suite_export import safe_extract


def _parse(raw: bytes) -> Tuple[Any, str]:
    text = raw[:200_000].decode("utf-8", "replace")
    try:
        return json.loads(text), text
    except ValueError:
        return None, text


class Probe:
    """Requests against one base URL. Keeps cookies (the preview origin sets a session cookie) and follows redirects."""

    def __init__(self, base: str, token: str = ""):
        self.base, self.token = base.rstrip("/"), token
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, method: str, path: str, json: Any = None, token: str = "", timeout: float = 30.0) -> Resp:  # noqa: A002
        headers = {"Accept": "application/json, text/html"}
        data = None
        if json is not None:
            headers["Content-Type"] = "application/json"
            data = _dumps(json)
        tok = token or self.token
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        req = urllib.request.Request(self.base + path if path.startswith("/") else path, data=data, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=timeout) as r:
                body, text = _parse(r.read())
                return Resp(r.status, body, text)
        except urllib.error.HTTPError as e:
            body, text = _parse(e.read())
            return Resp(e.code, body, text)
        except (urllib.error.URLError, OSError, ValueError) as e:
            return Resp(0, None, str(e))

    def get_bytes(self, path: str, timeout: float = 300.0) -> Tuple[int, bytes, str]:
        req = urllib.request.Request(self.base + path, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with self._opener.open(req, timeout=timeout) as r:
                return r.status, r.read(), ""
        except urllib.error.HTTPError as e:
            return e.code, b"", e.read()[:400].decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as e:
            return 0, b"", str(e)


def _dumps(obj: Any) -> bytes:
    return json.dumps(obj).encode()


def login(base: str, email: str, password: str) -> Tuple[str, str]:
    """Platform login -> (token, reason)."""
    r = Probe(base).request("POST", "/auth/login", json={"email": email, "password": password})
    tok = (r.body or {}).get("access_token") if isinstance(r.body, dict) else None
    return (tok, "") if tok else ("", f"platform login answered {r.status}: {r.text[:120]}")


def preview_probe(api: Probe, run_id: str) -> Tuple[Optional[Probe], str]:
    """A Probe on the run's preview origin: POST preview-session, spend the one-time link, then /app-preview is the app."""
    s = api.request("POST", f"/factory/runs/{run_id}/preview-session")
    if s.status != 200 or not isinstance(s.body, dict) or not s.body.get("url"):
        return None, f"preview-session answered {s.status}: {s.text[:160]}"
    origin = s.body.get("preview_origin") or s.body["url"].split("/__preview")[0]
    p = Probe(origin + "/app-preview")
    entered = p.request("GET", s.body["url"])      # absolute URL: sets the session cookie, redirects into the app
    if entered.status == 0 or entered.status >= 400:
        return None, f"could not open the preview origin {origin}: {entered.status} {entered.text[:120]}"
    return p, ""


class LocalApp:
    """The exported backend, started on this machine in a throwaway venv. Needs python3 and network for pip."""

    def __init__(self, zip_bytes: bytes):
        self.tmp = Path(tempfile.mkdtemp(prefix="accept-app-"))
        self.zip, self.proc, self.probe = zip_bytes, None, None

    def start(self, timeout: int = 240) -> Tuple[Optional[Probe], str]:
        try:
            safe_extract(self.zip, self.tmp)
            be = self.tmp / "backend"
            venv = self.tmp / "venv"
            for cmd in ([sys.executable, "-m", "venv", str(venv)],
                         [str(venv / "bin/pip"), "install", "-q", "-r", str(be / "requirements.txt")]):
                r = subprocess.run(cmd, cwd=be, capture_output=True, text=True, timeout=900)  # noqa: S603
                if r.returncode != 0:
                    return None, f"{' '.join(cmd[1:3])} failed: " + (r.stdout + r.stderr).strip()[-300:]
            module = "src.main:app" if (be / "src/main.py").exists() else "main:app"
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            env = {**os.environ, "SECRET_KEY": os.urandom(24).hex(), "JWT_SECRET": os.urandom(24).hex(),
                   "DATABASE_URL": f"sqlite:///{self.tmp}/app.db"}
            self.proc = subprocess.Popen([str(venv / "bin/python"), "-m", "uvicorn", module, "--port", str(port)],  # noqa: S603
                                         cwd=be, env=env, stdout=open(self.tmp / "app.log", "w"), stderr=subprocess.STDOUT,
                                         start_new_session=True)
            self.probe = Probe(f"http://127.0.0.1:{port}")
            end = time.time() + timeout
            while time.time() < end:
                if self.proc.poll() is not None:
                    return None, "the exported backend exited at start: " + (self.tmp / "app.log").read_text()[-300:]
                if self.probe.request("GET", "/openapi.json", timeout=3).status == 200:
                    return self.probe, ""
                time.sleep(1)
            return None, "the exported backend did not answer /openapi.json in time"
        except (ValueError, OSError, subprocess.SubprocessError) as e:
            return None, f"could not start the exported backend: {e}"

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
        shutil.rmtree(self.tmp, ignore_errors=True)
