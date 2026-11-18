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
        logger.warning("p07b_perf: HTTP probe failed for %s: %s", url, exc)
        return {"status": 0, "error": str(exc), "latency_ms": (time.monotonic() - start) * 1000}


# p95 targets by domain, used when the requirements do not state one. Trading: 200 ms is the target the
# capacity planner's real-time HPA metric already uses. Engineering defaults, the product's real SLA is the owner's.
_DEFAULT_SLA_P95_MS = 2000
_DOMAIN_SLA_P95_MS = {"trading": 200, "fintech": 500}


def _latency_sla_p95_ms(data: dict) -> int:
    """p95 target: an explicit latency_sla_p95_ms (from the requirements/IR) wins, then the domain's, then 2000."""
    try:
        explicit = int(data.get("latency_sla_p95_ms") or 0)
    except (TypeError, ValueError):
        explicit = 0
    if explicit > 0:
        return explicit
    return _DOMAIN_SLA_P95_MS.get(str(data.get("domain", "")).lower(), _DEFAULT_SLA_P95_MS)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    project_name: str = data.get("project_name", "App")
    backend_port = data.get("backend_port", None)

    if backend_port is None:
        result = {
            "skipped": True,
            "reason": "no running app during pipeline build",
            "success": True,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "perf_results.json").write_text(json.dumps(result, indent=2))
        return TaskResult(
            output_path=str(output_dir / "perf_results.json"),
            confidence=1.0,
            metadata={"phase": "p07b_performance_testing", "skipped": True, "data": result},
        )

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
        logger.error("[p07b] backend not reachable at %s (%s) — load test failed", health_url, exc)
        results["success"] = False
        results["reason"] = f"Cannot run performance test — app health check failed: {exc}"
        (output_dir / "perf_results.json").write_text(json.dumps(results, indent=2))
        return TaskResult(
            output_path=str(output_dir / "perf_results.json"),
            confidence=0.0,
            metadata=results,
            success=False,
            issues=[results["reason"]],
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
    sla_p95_ms = _latency_sla_p95_ms(data)
    results["sla_p95_ms"] = sla_p95_ms
    results["passed"] = results["error_rate_pct"] < 10 and results.get("p95_ms", 9999) < sla_p95_ms

    logger.info(
        "[p07b] load test done: p95=%.0fms errors=%.1f%%",
        results.get("p95_ms", 0),
        results["error_rate_pct"],
    )

    # ── Build entity-aware Locust tasks ──────────────────────────────────────
    entities = data.get("entities") or []
    entity_tasks: list[str] = []
    for entity in entities[:20]:  # cap at 20 to keep file readable
        name = entity.get("name") if isinstance(entity, dict) else str(entity)
        if not name:
            continue
        slug = name.lower().replace(" ", "_")
        fn_name = f"list_{slug}"
        endpoint = f"/api/{slug}s"
        entity_tasks.append(
            f"    @task(1)\n    def {fn_name}(self):\n        self.client.get(\"{endpoint}\")\n"
        )

    if not entity_tasks:
        # Fallback: generic list endpoint when no entity info is available
        entity_tasks = [
            "    @task(1)\n    def list_resources(self):\n        self.client.get(\"/api/items\")\n"
        ]

    entity_task_block = "\n".join(entity_tasks)
    class_name = project_name.replace(" ", "").replace("-", "") + "User"
    locust_file = textwrap.dedent(f"""\
        from locust import HttpUser, task, between


        class {class_name}(HttpUser):
            wait_time = between(0.5, 2)

            @task(3)
            def health(self):
                self.client.get("/health")

    """) + entity_task_block + "\n"

    locust_path = output_dir / "locustfile.py"
    locust_path.write_text(locust_file)
    logger.info("[p07b] locustfile written: %d entity task(s) at %s", len(entity_tasks), locust_path)

    (output_dir / "perf_results.json").write_text(json.dumps(results, indent=2))

    load_test_summary = {
        "p50_ms": results.get("p50_ms"),
        "p95_ms": results.get("p95_ms"),
        "p99_ms": results.get("p99_ms"),
        "error_rate": results.get("error_rate_pct"),
        "requests_tested": results.get("total_requests"),
    }

    return TaskResult(
        output_path=str(output_dir / "perf_results.json"),
        confidence=0.80,
        metadata={
            **results,
            "locustfile_path": str(locust_path),
            "load_test_summary": load_test_summary,
        },
        success=True,
        issues=[f"error rate {results['error_rate_pct']}%"] if results["error_rate_pct"] > 5 else [],
    )
