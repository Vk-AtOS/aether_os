#!/usr/bin/env python3.11
"""KAN-114: the pre-sale acceptance run, scripted and recorded. Needs a running stack, a real model key and Docker.

    ACCEPT_API=http://127.0.0.1:8000 ACCEPT_TOKEN=<owner/admin JWT> python3.11 scripts/acceptance_run.py \
        [--out docs/acceptance] [--prompt "a small todo app"] [--velaris] [--max-minutes 45]

Steps (each ends PASS / FAIL / SKIP with its measurements):
  1 preflight        API healthy, Docker usable, a model key configured (one of the provider env vars)
  2 pipeline         POST /factory/start, poll to a final state; records time, cost, which stages ran / were skipped / failed
  3 velaris flow     POST /velaris/flows, poll, approve the waiting call if any, verify the hash chain   (--velaris)
  4 signed session   scripts/velaris_smoke.py (HMAC + Ed25519), when VELARIS_API_URL is set                (--velaris)
  5 sandbox          tests/test_docker_sandbox_live.py (real containers, network isolation, kill at timeout)
Mail, Jira/Zoho/Razorpay/Stripe sandbox accounts need the owner's test accounts: they are listed as MANUAL rows to fill in.
No model key, no Docker or no stack: prints SKIP with the reason and exits 0 (nothing was run, nothing is claimed).
Result: <out>/acceptance-<UTC time>.json and .md (the table pasted into Confluence "Acceptance Run 1"). Exit 1 = a FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
MODEL_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "AWS_BEARER_TOKEN_BEDROCK")
MANUAL = ["real mail send/receive on a test domain", "Jira sandbox connector", "Zoho / Razorpay / Stripe sandbox accounts"]
FINAL = {"completed", "failed", "cancelled", "error", "done", "success"}


def call(api: str, token: str, method: str, path: str, body: Optional[dict] = None, timeout: float = 30.0) -> tuple[int, Any]:
    req = urllib.request.Request(api.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, {"detail": e.read()[:300].decode(errors="replace")}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, {"detail": str(e)}


def docker_ok() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def preflight(api: str, token: str) -> Dict[str, Any]:
    missing = []
    if not token:
        missing.append("ACCEPT_TOKEN not set")
    if not any(os.environ.get(k) for k in MODEL_KEYS):
        missing.append("no model key in the environment (" + ", ".join(MODEL_KEYS) + ")")
    if not docker_ok():
        missing.append("Docker is not available")
    if call(api, token, "GET", "/healthz", timeout=5)[0] != 200:
        missing.append(f"API not reachable at {api}")
    return {"step": "preflight", "status": "SKIP" if missing else "PASS", "detail": "; ".join(missing) or "ready"}


def stage_summary(run: Dict[str, Any]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {"ran": [], "skipped": [], "failed": []}
    for ph in run.get("phases") or []:
        st = str(ph.get("status", "")).lower()
        name = str(ph.get("phase_name") or ph.get("name") or ph.get("phase") or "?")
        out["skipped" if "skip" in st else "failed" if st in ("failed", "error") else "ran"].append(name)
    return out


def pipeline(api: str, token: str, prompt: str, max_minutes: int) -> Dict[str, Any]:
    t0 = time.time()
    code, started = call(api, token, "POST", "/factory/start", {"raw_input": prompt, "domain": "general", "project_name": "acceptance-run"})
    if code != 200 or not isinstance(started, dict) or not started.get("run_id"):
        return {"step": "pipeline", "status": "FAIL", "detail": f"start answered {code}: {started}"}
    run_id, run = started["run_id"], {}
    while time.time() - t0 < max_minutes * 60:
        time.sleep(15)
        code, run = call(api, token, "GET", f"/factory/runs/{run_id}")
        if code == 200 and str(run.get("status", "")).lower() in FINAL:
            break
    stages = stage_summary(run if isinstance(run, dict) else {})
    status = str((run or {}).get("status", "")).lower()
    ok = status in ("completed", "done", "success") and not stages["failed"]
    return {"step": "pipeline", "status": "PASS" if ok else "FAIL", "run_id": run_id, "final_status": status or "timeout",
            "seconds": round(time.time() - t0), "cost_usd": (run or {}).get("cost"), "stages": stages,
            "detail": f"{len(stages['ran'])} ran, {len(stages['skipped'])} skipped, {len(stages['failed'])} failed"}


def velaris_flow(api: str, token: str, max_minutes: int = 10) -> Dict[str, Any]:
    t0 = time.time()
    code, started = call(api, token, "POST", "/velaris/flows", {"task": "List the available agents and summarise them in one line.", "tools": []})
    if code not in (200, 201, 202) or not isinstance(started, dict) or not started.get("run_id"):
        return {"step": "velaris flow", "status": "FAIL", "detail": f"start answered {code}: {started}"}
    run_id, flow = started["run_id"], {}
    while time.time() - t0 < max_minutes * 60:
        code, flow = call(api, token, "GET", f"/velaris/flows/{run_id}")
        waiting = isinstance(flow, dict) and flow.get("pending_call_hash") or (flow or {}).get("call_hash")
        if waiting and str((flow or {}).get("status", "")).startswith(("await", "wait", "pending")):
            call(api, token, "POST", f"/velaris/flows/{run_id}/decide", {"call_hash": waiting, "approve": True, "note": "acceptance run"})
        elif str((flow or {}).get("status", "")).lower() in FINAL:
            break
        time.sleep(5)
    vcode, verified = call(api, token, "GET", f"/velaris/flows/{run_id}/verify")
    ok = vcode == 200 and isinstance(verified, dict) and verified.get("ok") is True
    return {"step": "velaris flow", "status": "PASS" if ok else "FAIL", "run_id": run_id,
            "final_status": (flow or {}).get("status"), "trace_verified": ok, "seconds": round(time.time() - t0)}


def signed_session() -> Dict[str, Any]:
    if not os.environ.get("VELARIS_API_URL"):
        return {"step": "signed session", "status": "SKIP", "detail": "VELARIS_API_URL not set"}
    org = os.environ.get("ACCEPT_ORG", "")
    r = subprocess.run([sys.executable, str(ROOT / "scripts/velaris_smoke.py"), "--org", org], capture_output=True, text=True, timeout=120)
    return {"step": "signed session", "status": "PASS" if r.returncode == 0 else "FAIL", "detail": (r.stdout + r.stderr).strip()[-300:]}


def sandbox() -> Dict[str, Any]:
    # The live Docker backend test (real containers, network isolation probe, kill at timeout); it skips itself without Docker.
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", "tests/test_docker_sandbox_live.py"],
                       capture_output=True, text=True, cwd=ROOT, timeout=600, env={**os.environ, "PYTHONPATH": str(ROOT.parent)})
    tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
    return {"step": "sandbox", "status": "PASS" if r.returncode == 0 and "skipped" not in tail[0] else "FAIL", "detail": tail[0]}


def render(results: List[Dict[str, Any]]) -> str:
    rows = ["| step | result | detail |", "|---|---|---|"]
    rows += [f"| {r['step']} | {r['status']} | {r.get('detail') or json.dumps({k: v for k, v in r.items() if k not in ('step', 'status')})[:200]} |" for r in results]
    rows += [f"| {m} | MANUAL | fill in with the owner's test account |" for m in MANUAL]
    return "\n".join(rows) + "\n"


def run(api: str, token: str, prompt: str, velaris: bool, max_minutes: int) -> List[Dict[str, Any]]:
    pre = preflight(api, token)
    if pre["status"] != "PASS":
        return [pre]
    results = [pre, pipeline(api, token, prompt, max_minutes), sandbox()]
    if velaris:
        results[2:2] = [velaris_flow(api, token), signed_session()]
    return results


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "docs/acceptance"))
    ap.add_argument("--prompt", default="A small todo list app with users, tasks and due dates")
    ap.add_argument("--velaris", action="store_true")
    ap.add_argument("--max-minutes", type=int, default=45)
    args = ap.parse_args(argv)
    results = run(os.environ.get("ACCEPT_API", "http://127.0.0.1:8000"), os.environ.get("ACCEPT_TOKEN", ""),
                  args.prompt, args.velaris, args.max_minutes)
    if results[0]["status"] == "SKIP":
        print("SKIP:", results[0]["detail"])
        return 0
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"acceptance-{stamp}.json").write_text(json.dumps({"at": stamp, "results": results, "manual": MANUAL}, indent=2))
    (out / f"acceptance-{stamp}.md").write_text(render(results))
    print(render(results))
    return 1 if any(r["status"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
