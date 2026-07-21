"""
AetherOS Benchmark Harness
==========================
Buyer-runnable, zero-dependency benchmark: fire 10 golden prompts through the
pipeline and produce JSON + Markdown results.

Usage
-----
  python scripts/benchmark_harness.py --api-url http://localhost:8000 --token <jwt>
  AETHER_TOKEN=<jwt> python scripts/benchmark_harness.py

Exit codes: 0 = all passed, 1 = one or more failures / errors.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────

PROMPTS_DIR = Path(__file__).parent.parent / "benchmarks" / "prompts"
RESULTS_DIR = Path(__file__).parent.parent / "benchmarks" / "results"
POLL_INTERVAL = 15          # seconds between status polls
RUN_TIMEOUT   = 1200        # 20 minutes per run
TERMINAL      = {"completed", "failed", "timeout", "cancelled", "error"}


# ── HTTP helpers (stdlib only) ─────────────────────────────────────────────────

def _request(url: str, token: str, method: str = "GET",
             body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _start_run(api_url: str, token: str, prompt: str) -> str | None:
    try:
        data = _request(
            f"{api_url}/factory/start", token, method="POST",
            body={"raw_input": prompt, "autonomous_mode": True},
        )
        return data.get("run_id")
    except urllib.error.HTTPError as e:
        print(f"  [start] HTTP {e.code}: {e.read()[:200]}")
    except Exception as e:
        print(f"  [start] error: {e}")
    return None


def _poll_run(api_url: str, token: str, run_id: str) -> dict:
    deadline = time.monotonic() + RUN_TIMEOUT
    while time.monotonic() < deadline:
        try:
            data = _request(f"{api_url}/factory/runs/{run_id}", token)
            if data.get("status") in TERMINAL:
                return data
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"  [poll] HTTP {e.code}")
        except Exception as e:
            print(f"  [poll] error: {e}")
        time.sleep(POLL_INTERVAL)
    return {"status": "timeout", "run_id": run_id}


# ── Scoring ────────────────────────────────────────────────────────────────────

def _score(prompt_file: Path, run_data: dict) -> dict:
    meta = run_data.get("metadata") or {}
    return {
        "prompt_file":       prompt_file.name,
        "run_id":            run_data.get("run_id") or run_data.get("id"),
        "status":            run_data.get("status"),
        "build_pass":        run_data.get("status") == "completed",
        "template_debt_pct": meta.get("template_debt_pct"),
        "confidence":        run_data.get("confidence"),
        "domain":            run_data.get("domain") or prompt_file.stem.split("_", 1)[-1].split("_")[0],
        "duration_s":        run_data.get("duration_s"),
        "error":             run_data.get("message") if run_data.get("status") != "completed" else None,
    }


# ── Output writers ─────────────────────────────────────────────────────────────

def _write_json(results: list[dict], today: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{today}.json"
    out.write_text(json.dumps(results, indent=2))
    return out


def _write_md(results: list[dict], today: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# AetherOS Benchmark — {today}",
        "",
        "| # | Prompt | Status | Build | Debt% | Confidence | Domain |",
        "|---|--------|--------|-------|-------|------------|--------|",
    ]
    for i, r in enumerate(results, 1):
        build    = "PASS" if r["build_pass"] else "FAIL"
        debt     = f"{r['template_debt_pct']:.1f}" if r["template_debt_pct"] is not None else "—"
        conf     = f"{r['confidence']:.2f}"         if r["confidence"]        is not None else "—"
        lines.append(
            f"| {i} | {r['prompt_file']} | {r['status']} | {build} | {debt} | {conf} | {r['domain']} |"
        )
    passes = sum(1 for r in results if r["build_pass"])
    lines += ["", f"**{passes}/{len(results)} builds passed.**", ""]
    out = RESULTS_DIR / f"{today}.md"
    out.write_text("\n".join(lines))
    return out


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="AetherOS benchmark harness")
    p.add_argument("--api-url", default="http://localhost:8000")
    p.add_argument("--token",   default="")
    args = p.parse_args()

    token = args.token or os.environ.get("AETHER_TOKEN", "")
    if not token:
        print("Set --token or AETHER_TOKEN")
        return 1

    api_url = args.api_url.rstrip("/")

    prompt_files = sorted(PROMPTS_DIR.glob("*.md"))
    if not prompt_files:
        print(f"No prompt files found in {PROMPTS_DIR}")
        return 1

    print(f"Running {len(prompt_files)} prompts against {api_url}\n")
    results: list[dict] = []

    for pf in prompt_files:
        prompt = pf.read_text().strip()
        print(f"→ {pf.name}")

        run_id = _start_run(api_url, token, prompt)
        if not run_id:
            results.append(_score(pf, {"status": "start_failed", "run_id": None}))
            print("  SKIPPED (could not start)\n")
            continue

        print(f"  run_id={run_id}  polling every {POLL_INTERVAL}s (max {RUN_TIMEOUT//60}m)…")
        run_data = _poll_run(api_url, token, run_id)
        run_data.setdefault("run_id", run_id)
        result = _score(pf, run_data)
        results.append(result)

        status = "PASS" if result["build_pass"] else f"FAIL ({result['status']})"
        print(f"  {status}\n")

    today = date.today().isoformat()
    json_path = _write_json(results, today)
    md_path   = _write_md(results, today)

    passes = sum(1 for r in results if r["build_pass"])
    print(f"Results: {passes}/{len(results)} passed")
    print(f"  JSON → {json_path}")
    print(f"  MD   → {md_path}")

    return 0 if passes == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
