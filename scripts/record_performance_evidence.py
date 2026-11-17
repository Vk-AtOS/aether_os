#!/usr/bin/env python3.11
"""Record the evidence for the performance claims into a dated file (KAN-193). Needs a running stack.

    python3.11 scripts/record_performance_evidence.py --host http://127.0.0.1:8000 \
        --email loadtest_0@example.com --password '...' --users 50 --duration 120 \
        [--token <jwt> --builds 3]      # --builds N also runs N benchmark prompts: build time and cost per run

Writes docs/evidence/performance_<UTC date>.json and .md: the git commit, the measured load p95 / error rate,
(with --builds) build time and cost per run, and each public claim next to what was measured. Exit codes:
0 recorded, 2 no stack reachable (nothing written: a missing measurement is not evidence), 3 a claim is not met.
Never point it at production. The claims below are the ones the docs make; update CLAIMS when a doc changes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# claim -> (where it is made, metric, comparison, limit)
CLAIMS = {
    "load p95 at 50 users <= 240 ms": ("CHANGELOG.md 1.0.0", "load_p95_ms", "<=", 240.0),
    "load error rate 0 %": ("CHANGELOG.md 1.0.0", "load_error_rate", "<=", 0.0),
    "build time 7-10 minutes": ("SALE_READINESS.md", "build_minutes_mean", "<=", 10.0),
}


def reachable(host: str) -> bool:
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/health", timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def judge(measured: dict) -> list:
    """Each claim next to its measurement: met True/False, or None when it was not measured."""
    out = []
    for claim, (source, metric, op, limit) in CLAIMS.items():
        value = measured.get(metric)
        met = None if value is None else (value <= limit if op == "<=" else value >= limit)
        out.append({"claim": claim, "source": source, "metric": metric, "limit": limit, "measured": value, "met": met})
    return out


def measure_load(args) -> dict:
    out = ROOT / "tests" / "load" / "results" / "_evidence_tmp.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "aether_os.tests.load.harness", "--host", args.host, "--users", str(args.users),
                    "--duration", str(args.duration), "--email", args.email, "--password", args.password,
                    "--out", str(out)], cwd=ROOT, check=False, timeout=args.duration + 300,
                   env={**__import__("os").environ, "PYTHONPATH": str(ROOT.parent)})
    result = json.loads(out.read_text())
    out.unlink()
    return result


def measure_builds(args) -> list:
    import benchmark_harness as bh
    runs = []
    for prompt in sorted(bh.PROMPTS_DIR.glob("*.md"))[: args.builds]:
        run_id = bh._start_run(args.host, args.token, prompt.read_text())
        if not run_id:
            runs.append({"prompt": prompt.name, "error": "run did not start"})
            continue
        data = bh._poll_run(args.host, args.token, run_id)
        meta = data.get("metadata") or {}
        runs.append({"prompt": prompt.name, "run_id": run_id, "status": data.get("status"),
                     "duration_s": data.get("duration_s"), "cost_usd": data.get("cost_usd", meta.get("cost_usd"))})
    return runs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--duration", type=float, default=120)
    ap.add_argument("--token", default="")
    ap.add_argument("--builds", type=int, default=0)
    ap.add_argument("--out-dir", default=str(ROOT / "docs" / "evidence"))
    args = ap.parse_args(argv)
    if not reachable(args.host):
        print(f"no stack answering at {args.host}/health: nothing recorded", file=sys.stderr)
        return 2
    load = measure_load(args)
    measured = {"load_p95_ms": load["total"]["p95_ms"], "load_error_rate": load["total"]["error_rate"]}
    builds = measure_builds(args) if args.builds and args.token else []
    done = [b for b in builds if b.get("status") == "completed" and b.get("duration_s")]
    if done:
        measured["build_minutes_mean"] = round(sum(b["duration_s"] for b in done) / len(done) / 60, 1)
        costs = [b["cost_usd"] for b in done if b.get("cost_usd") is not None]
        measured["cost_per_run_usd_mean"] = round(sum(costs) / len(costs), 3) if costs else None
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    stamp = datetime.now(timezone.utc)
    record = {"recorded_at": stamp.isoformat(timespec="seconds"), "commit": commit, "host": args.host, "users": args.users,
              "duration_s": load["duration_s"], "load": load["total"], "builds": builds, "measured": measured,
              "claims": judge(measured)}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"performance_{stamp:%Y-%m-%d}"
    base.with_suffix(".json").write_text(json.dumps(record, indent=2))
    lines = [f"# Performance evidence {stamp:%Y-%m-%d}", "", f"Commit `{commit}`, {args.users} users, {load['duration_s']} s.", "",
             "| Claim | Source | Measured | Met |", "|---|---|---|---|"]
    lines += [f"| {c['claim']} | {c['source']} | {c['measured'] if c['measured'] is not None else 'not measured'} | "
              f"{'yes' if c['met'] else 'NO' if c['met'] is False else '-'} |" for c in record["claims"]]
    base.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print(f"recorded {base}.json")
    return 3 if any(c["met"] is False for c in record["claims"]) else 0


if __name__ == "__main__":
    sys.exit(main())
