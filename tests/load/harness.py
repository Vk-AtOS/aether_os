"""Dependency-light load harness (stdlib only) with a recorded result format.

    python3 -m aether_os.tests.load.harness --host http://127.0.0.1:8000 \
        --users 50 --duration 30 --email demo@example.com --password '...' [--out FILE]

Each virtual user logs in once, then loops over the read endpoints below with a short think time.
Writes tests/load/results/<UTC timestamp>.json (schema_version 1, see README.md) and exits 1 if
the run breaches the thresholds (p95 > --p95-ms or error rate > --max-error-rate).
For the full Locust scenarios use locustfile.py; this one needs no extra install and is what CI or
an engineer on a laptop runs.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

SCHEMA_VERSION = 1
ENDPOINTS = ["/health", "/factory/runs?limit=20", "/workspaces", "/notifications"]


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def _call(host: str, path: str, token: Optional[str], timeout: float, body: Optional[dict] = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urlrequest.Request(host + path, data=data, method="POST" if body is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    t0 = time.perf_counter()
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            return resp.status, (time.perf_counter() - t0) * 1000, payload
    except HTTPError as e:
        return e.code, (time.perf_counter() - t0) * 1000, b""
    except (URLError, TimeoutError, OSError):
        return 0, (time.perf_counter() - t0) * 1000, b""


def _user_loop(host, creds, deadline, timeout, think, out: Dict[str, list], lock):
    status, ms, payload = _call(host, "/auth/login", None, timeout, {"email": creds[0], "password": creds[1]})
    token = None
    if status == 200:
        try:
            token = json.loads(payload).get("access_token")
        except ValueError:
            token = None
    with lock:
        out.setdefault("/auth/login", []).append((status, ms))
    if not token:
        return
    i = 0
    while time.monotonic() < deadline:
        path = ENDPOINTS[i % len(ENDPOINTS)]
        i += 1
        status, ms, _ = _call(host, path, token, timeout, None)
        with lock:
            out.setdefault(path.split("?")[0], []).append((status, ms))
        time.sleep(think)


def summarise(samples: Dict[str, list], duration_s: float) -> dict:
    def stats(rows):
        lat = [ms for _, ms in rows]
        errors = sum(1 for st, _ in rows if st == 0 or st >= 500)
        return {
            "requests": len(rows), "errors": errors,
            "error_rate": round(errors / len(rows), 4) if rows else 0.0,
            "p50_ms": round(percentile(lat, 50), 1), "p95_ms": round(percentile(lat, 95), 1),
            "p99_ms": round(percentile(lat, 99), 1),
            "mean_ms": round(statistics.fmean(lat), 1) if lat else 0.0,
        }
    every = [r for rows in samples.values() for r in rows]
    total = stats(every)
    total["rps"] = round(len(every) / duration_s, 1) if duration_s else 0.0
    return {"total": total, "endpoints": {k: stats(v) for k, v in sorted(samples.items())}}


def run(host: str, users: int, duration: float, creds: tuple, timeout: float = 30.0, think: float = 0.2) -> dict:
    samples: Dict[str, list] = {}
    lock = threading.Lock()
    start = time.monotonic()
    deadline = start + duration
    threads = [threading.Thread(target=_user_loop, args=(host, creds, deadline, timeout, think, samples, lock), daemon=True)
               for _ in range(users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(duration + timeout + 5)
    elapsed = time.monotonic() - start
    return {
        "schema_version": SCHEMA_VERSION,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": host, "users": users, "duration_s": round(elapsed, 1), "think_s": think,
        "client": {"python": platform.python_version(), "os": platform.platform()},
        **summarise(samples, elapsed),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--p95-ms", type=float, default=1500)
    ap.add_argument("--max-error-rate", type=float, default=0.02)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    result = run(a.host.rstrip("/"), a.users, a.duration, (a.email, a.password))
    out = Path(a.out) if a.out else Path(__file__).parent / "results" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    t = result["total"]
    ok = t["requests"] > 0 and t["p95_ms"] <= a.p95_ms and t["error_rate"] <= a.max_error_rate
    print(f"{t['requests']} requests, {t['rps']} rps, p95 {t['p95_ms']} ms, errors {t['error_rate']:.2%} -> {out} ({'PASS' if ok else 'FAIL'})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
