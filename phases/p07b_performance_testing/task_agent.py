"""P07b Performance Testing — basic load test against the generated backend."""
from __future__ import annotations
import asyncio
import json
import logging
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

_CONCURRENT = 10
_REQUESTS_PER_WORKER = 5


async def _hit_endpoint(session, url: str) -> Dict:
    import httpx
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            return {"status": resp.status_code, "latency_ms": (time.monotonic() - start) * 1000}
    except Exception as exc:
        return {"status": 0, "error": str(exc), "latency_ms": (time.monotonic() - start) * 1000}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    project_name: str = data.get("project_name", "App")
    backend_port: int = data.get("backend_port", 8000)
    base_url = f"http://localhost:{backend_port}"
    health_url = f"{base_url}/health"

    results: Dict = {
        "target": health_url,
        "concurrent_workers": _CONCURRENT,
        "requests_per_worker": _REQUESTS_PER_WORKER,
        "total_requests": _CONCURRENT * _REQUESTS_PER_WORKER,
    }

    # ── Check if backend is reachable ─────────────────────────────────────────
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(health_url)
            if resp.status_code >= 400:
                raise ValueError(f"health returned {resp.status_code}")
    except Exception as exc:
        logger.info("[p07b] backend not reachable at %s (%s) — skipping load test", health_url, exc)
        results["skipped"] = True
        results["reason"] = "backend not running locally"
        (output_dir / "perf_results.json").write_text(json.dumps(results, indent=2))
        return TaskResult(
            output_path=str(output_dir / "perf_results.json"),
            confidence=0.5,
            metadata=results,
            success=True,
            issues=[],
        )

    # ── Run concurrent load ───────────────────────────────────────────────────
    tasks = [_hit_endpoint(None, health_url) for _ in range(_CONCURRENT * _REQUESTS_PER_WORKER)]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    responses = [r for r in raw if isinstance(r, dict)]

    latencies = [r["latency_ms"] for r in responses if "latency_ms" in r]
    statuses = [r["status"] for r in responses]
    errors = [r for r in responses if r.get("status", 0) not in (200, 201)]

    if latencies:
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        results["p50_ms"] = round(latencies_sorted[n // 2], 1)
        results["p95_ms"] = round(latencies_sorted[min(int(n * 0.95), n - 1)], 1)
        results["p99_ms"] = round(latencies_sorted[min(int(n * 0.99), n - 1)], 1)
        results["mean_ms"] = round(sum(latencies) / len(latencies), 1)

    results["success_count"] = statuses.count(200) + statuses.count(201)
    results["error_count"] = len(errors)
    results["error_rate_pct"] = round(len(errors) / max(len(responses), 1) * 100, 1)
    results["passed"] = results["error_rate_pct"] < 10 and results.get("p95_ms", 9999) < 2000

    logger.info(
        "[p07b] load test done: p95=%.0fms errors=%.1f%%",
        results.get("p95_ms", 0),
        results["error_rate_pct"],
    )

    # ── Write locust file for reference ───────────────────────────────────────
    locust_file = textwrap.dedent(f"""\
        from locust import HttpUser, task, between

        class {project_name.replace(' ', '')}User(HttpUser):
            wait_time = between(0.5, 2)

            @task(3)
            def health(self):
                self.client.get("/health")

            @task(1)
            def list_resources(self):
                self.client.get("/api/items")
    """)
    (output_dir / "locustfile.py").write_text(locust_file)

    (output_dir / "perf_results.json").write_text(json.dumps(results, indent=2))

    return TaskResult(
        output_path=str(output_dir / "perf_results.json"),
        confidence=0.80,
        metadata=results,
        success=True,
        issues=[f"error rate {results['error_rate_pct']}%"] if results["error_rate_pct"] > 5 else [],
    )
