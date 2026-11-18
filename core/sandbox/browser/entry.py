"""In-sandbox driver for browser work on a generated app (KAN-99 / KAN-65).

Runs INSIDE the browser sandbox (core/sandbox/Dockerfile.browser: no network, read-only root, non-root,
only the run directory writable) or, in development, under the macos/none backends. The platform never
starts Chromium or node on its own host: it writes a job file into the run directory and runs this script
through the sandbox runner (core/sandbox/browser_job.py).

Everything the job needs runs on this container's loopback: a static server for the built frontend, the
generated backend when the job names one, and then ONE action:

  screenshot       full page PNG of `url`                  -> job["out"] (png)
  axe              axe-core run on `url` (tags optional)   -> job["out"] (json) and stdout
  playwright_test  `npx playwright test <spec>` (json)     -> job["out"] (json) and stdout

It prints one JSON line on stdout: {"ok": bool, ...}. Standard library plus playwright only.
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

AXE_JS = os.environ.get("AETHER_AXE_JS", "/opt/axe/node_modules/axe-core/axe.min.js")
CHROMIUM_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]   # the container is the sandbox


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Static files from `directory`, optionally under a base path (a Vite build with VITE_BASE_PATH)."""
    base = ""

    def translate_path(self, path: str) -> str:
        if self.base and path.startswith("/" + self.base):
            path = path[len(self.base) + 1:] or "/"
        return super().translate_path(path)

    def log_message(self, *args) -> None:  # quiet
        return


def serve_static(directory: str, port: int, base: str = "") -> http.server.ThreadingHTTPServer:
    handler = functools.partial(_Handler, directory=directory)
    handler.func.base = base.strip("/")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def wait_port(port: int, timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def start_backend(spec: dict):
    proc = subprocess.Popen(spec["argv"], cwd=spec.get("cwd"), env={**os.environ, **spec.get("env", {})},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    if not wait_port(int(spec["port"]), float(spec.get("wait_s", 30))):
        proc.kill()
        raise RuntimeError(f"backend did not listen on {spec['port']}")
    return proc


def do_screenshot(job: dict) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(job["url"], wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(1500)
            page.screenshot(path=job["out"], full_page=True)
        finally:
            browser.close()
    return {"ok": True, "out": job["out"]}


def do_axe(job: dict) -> dict:
    from playwright.sync_api import sync_playwright
    tags = job.get("tags") or []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        try:
            page = browser.new_page()
            page.goto(job["url"], wait_until="networkidle", timeout=20000)
            page.add_script_tag(path=AXE_JS)
            # axe.run returns violations/passes/incomplete; a thrown error is a scan that did not run.
            r = page.evaluate("(t) => axe.run(document, t.length ? {runOnly: {type: 'tag', values: t}} : {})", tags)
        finally:
            browser.close()
    out = {"ok": True, "violations": len(r["violations"]), "passes": len(r["passes"]),
           "incomplete": len(r["incomplete"]),
           "items": [{"id": v["id"], "impact": v.get("impact"), "description": v.get("description")}
                     for v in r["violations"][:10]]}
    Path(job["out"]).write_text(json.dumps(out), encoding="utf-8")
    return out


def do_playwright_test(job: dict) -> dict:
    done = subprocess.run(["npx", "playwright", "test", job["spec"], "--reporter=json"], cwd=job.get("cwd"),
                          capture_output=True, text=True, timeout=int(job.get("timeout", 100)))
    Path(job["out"]).write_text(done.stdout or done.stderr, encoding="utf-8")
    return {"ok": True, "returncode": done.returncode, "out": job["out"]}


ACTIONS = {"screenshot": do_screenshot, "axe": do_axe, "playwright_test": do_playwright_test}


def main(argv: list) -> int:
    job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    procs, servers = [], []
    try:
        if job["action"] not in ACTIONS:
            raise ValueError(f"unknown action {job['action']!r}")
        if job.get("serve"):
            s = job["serve"]
            servers.append(serve_static(s["dir"], int(s["port"]), s.get("base", "")))
        if job.get("backend"):
            procs.append(start_backend(job["backend"]))
        print(json.dumps(ACTIONS[job["action"]](job)))
        return 0
    except Exception as exc:  # reported to the platform as a failed job, never a crash with no output
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    finally:
        for srv in servers:
            srv.shutdown()
        for p in procs:
            p.kill()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
