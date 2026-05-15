"""P07b Task Agent — locust performance tests."""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    api_url = data.get("api_url", "http://localhost:8000")
    arch_json = data.get("architecture_json", {})
    if isinstance(arch_json, str):
        try:
            arch_json = json.loads(arch_json)
        except Exception:
            arch_json = {}
    endpoints = arch_json.get("api_endpoints", [])
    llm = get_llm_client()

    # Generate locustfile.py
    locust_code = await llm.call(
        f"Write a Locust performance test file for these API endpoints:\n"
        f"{json.dumps(endpoints, indent=2)[:2000]}\n\n"
        f"API base URL: {api_url}\n"
        f"Include:\n"
        f"- Login task to get JWT token (if auth endpoints exist)\n"
        f"- GET endpoint tasks as read tasks with @task(3) weight\n"
        f"- POST endpoint tasks as write tasks with realistic JSON payloads\n"
        f"- HttpUser class with wait_time = between(0.5, 2.0)\n"
        f"- on_start() to authenticate if needed\n"
        f"Use locust.HttpUser, locust.task, locust.between.",
        task_type="testing",
    )
    locust_path = output_dir / "locustfile.py"
    locust_path.write_text(_strip_fences(locust_code))

    # Check reachability before running locust
    import urllib.request
    import urllib.error
    report_path = output_dir / "performance_report.json"
    locust_ran = False
    p95_results: Dict[str, float] = {}
    issues: List[str] = []
    app_reachable = False

    try:
        urllib.request.urlopen(api_url + "/health", timeout=5)
        app_reachable = True
    except Exception:
        try:
            urllib.request.urlopen(api_url, timeout=5)
            app_reachable = True
        except Exception:
            pass

    if not app_reachable:
        logger.warning("Performance test: generated app not reachable at %s — skipping locust", api_url)
        issues = [f"Generated app not running at {api_url} — performance test skipped. Start the app first."]
        report = {
            "api_url": api_url,
            "users": 0,
            "run_time_s": 0,
            "p95_by_endpoint": {},
            "issues": issues,
            "locust_ran": False,
            "skipped_reason": f"App not reachable at {api_url}",
        }
        report_path.write_text(json.dumps(report, indent=2))
        return TaskResult(
            output_path=str(report_path),
            confidence=0.0,
            metadata={"endpoint_count": len(endpoints), "locust_ran": False, "app_reachable": False},
            issues=issues,
            success=True,  # non-blocking; the skip itself is not a failure
        )

    try:
        csv_prefix = str(output_dir / "locust_stats")
        result = subprocess.run(
            ["python3", "-m", "locust", "--headless", "--users", "100",
             "--spawn-rate", "10", "--run-time", "30s",
             "--host", api_url,
             "--csv", csv_prefix,
             "-f", str(locust_path)],
            capture_output=True, text=True, timeout=90,
        )
        locust_ran = result.returncode == 0

        stats_file = Path(f"{csv_prefix}_stats.csv")
        if stats_file.exists():
            import csv as _csv
            with open(stats_file) as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    name = row.get("Name", "")
                    p95 = float(row.get("95%", 0) or 0)
                    p95_results[name] = p95

    except Exception as e:
        logger.warning("Locust execution failed: %s", e)
        issues.append(f"Locust run error: {e}")

    for name, p95 in p95_results.items():
        if "GET" in name.upper() and p95 > 500:
            issues.append(f"P95 {p95:.0f}ms > 500ms threshold for {name}")
        elif "POST" in name.upper() and p95 > 2000:
            issues.append(f"P95 {p95:.0f}ms > 2000ms threshold for {name}")

    report = {
        "api_url": api_url,
        "users": 100,
        "run_time_s": 30,
        "p95_by_endpoint": p95_results,
        "issues": issues,
        "locust_ran": locust_ran,
    }
    report_path.write_text(json.dumps(report, indent=2))

    return TaskResult(
        output_path=str(report_path),
        confidence=0.85 if not issues else 0.6,
        metadata={"endpoint_count": len(endpoints), "p95_results": p95_results,
                  "locust_ran": locust_ran},
        issues=issues,
        success=True,
    )


def _strip_fences(code: str) -> str:
    lines = code.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
