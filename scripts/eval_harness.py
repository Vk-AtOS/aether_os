"""
AetherOS Eval Harness
=====================
Automated regression test that builds each golden prompt through the AetherOS
pipeline and verifies health / login / CRUD for every generated app.

Usage
-----
  python scripts/eval_harness.py --base-url http://localhost:8000
  python scripts/eval_harness.py --base-url http://localhost:8000 --concurrency 3
  python scripts/eval_harness.py --golden-idx 5                   # single prompt
  python scripts/eval_harness.py --output eval_results.json       # write JSON report

Exit codes
----------
  0  all builds healthy
  1  one or more failures
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

import httpx

from eval_golden_prompts import GOLDEN_PROMPTS

logger = logging.getLogger("eval_harness")

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class EvalResult:
    prompt_idx: int
    domain: str
    prompt: str
    run_id: Optional[str] = None
    build_passed: bool = False
    health_passed: bool = False
    login_passed: bool = False
    crud_passed: bool = False
    duration_seconds: float = 0.0
    error: str = ""
    crud_entity: str = ""
    crud_count: int = 0
    phase_confidence: Dict[str, Any] = field(default_factory=dict)
    low_confidence_phases: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

async def _login(client: httpx.AsyncClient, base_url: str,
                 email: str, password: str) -> Optional[str]:
    """Authenticate against the AetherOS platform and return a bearer token."""
    try:
        resp = await client.post(
            f"{base_url}/auth/login",
            json={"email": email, "password": password},
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as e:
        logger.warning("Platform login failed: %s", e)
        return None


async def _start_run(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    domain: str,
    prompt: str,
) -> Optional[str]:
    """Submit a new pipeline run and return its run_id."""
    try:
        resp = await client.post(
            f"{base_url}/factory/start",
            json={
                "raw_input": prompt,
                "domain": domain,
                "autonomous_mode": True,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("run_id")
    except Exception as e:
        logger.warning("start_run failed: %s", e)
        return None


async def _poll_run(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    run_id: str,
    poll_interval: float = 15.0,
    timeout: float = 900.0,
) -> Dict[str, Any]:
    """Poll GET /factory/runs/{run_id} until status is terminal or timeout."""
    terminal = {"completed", "failed", "timeout", "cancelled"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = await client.get(
                f"{base_url}/api/factory/runs/{run_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15.0,
            )
            if resp.status_code == 404:
                await asyncio.sleep(poll_interval)
                continue
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")
            if status in terminal:
                return data
        except Exception as e:
            logger.debug("poll_run %s error: %s", run_id, e)
        await asyncio.sleep(poll_interval)
    return {"status": "timeout", "run_id": run_id}


async def _check_health(
    client: httpx.AsyncClient,
    base_url: str,
    run_id: str,
) -> bool:
    """Check if the generated app's /health endpoint returns 200."""
    url = f"{base_url}/run-app/{run_id}/health"
    try:
        resp = await client.get(url, timeout=10.0)
        return resp.status_code == 200
    except Exception as e:
        logger.debug("health check %s: %s", run_id, e)
        return False


async def _check_login(
    client: httpx.AsyncClient,
    base_url: str,
    run_id: str,
    email: str,
    password: str,
) -> bool:
    """POST to the generated app's /auth/login and check for an access_token."""
    urls = [
        f"{base_url}/run-app/{run_id}/auth/login",
        f"{base_url}/run-app/{run_id}/api/auth/login",
    ]
    for url in urls:
        try:
            resp = await client.post(
                url,
                json={"email": email, "password": password},
                timeout=10.0,
            )
            if resp.status_code == 200 and resp.json().get("access_token"):
                return True
        except Exception as e:
            logger.debug("login check %s at %s: %s", run_id, url, e)
    return False


async def _check_crud(
    client: httpx.AsyncClient,
    base_url: str,
    run_id: str,
    token: str,
    platform_token: str,
) -> tuple[bool, str, int]:
    """Try to GET the first entity list endpoint and check for records > 0.

    Returns (passed, entity_name, record_count).
    """
    # First, look up entity list from the run detail
    try:
        resp = await client.get(
            f"{base_url}/api/factory/runs/{run_id}",
            headers={"Authorization": f"Bearer {platform_token}"},
            timeout=10.0,
        )
        run_data = resp.json() if resp.status_code == 200 else {}
    except Exception as e:
        logger.debug("crud_check: could not fetch run detail: %s", e)
        run_data = {}

    # Build a list of candidate entity endpoints
    candidates: list[str] = []
    # Check phase metadata for entities list
    phases = run_data.get("phases", {})
    for ph_name, ph_data in phases.items():
        if not isinstance(ph_data, dict):
            continue
        meta = ph_data.get("metadata", {}) or {}
        for ent in meta.get("entities", []):
            if isinstance(ent, dict) and ent.get("table"):
                candidates.append(f"/api/{ent['table']}")
            elif isinstance(ent, str):
                candidates.append(f"/api/{ent.lower()}")

    # Fallback: common guesses
    if not candidates:
        candidates = [
            "/api/contacts", "/api/products", "/api/patients", "/api/employees",
            "/api/orders", "/api/tasks", "/api/students", "/api/clients",
            "/api/vehicles", "/api/members", "/api/cases", "/api/events",
            "/api/books", "/api/jobs", "/api/users",
        ]

    app_headers = {"Authorization": f"Bearer {token}"} if token else {}
    for path in candidates[:8]:
        url = f"{base_url}/run-app/{run_id}{path}"
        try:
            resp = await client.get(url, headers=app_headers, timeout=10.0)
            if resp.status_code == 200:
                body = resp.json()
                items = (
                    body if isinstance(body, list)
                    else body.get("items") or body.get("data") or []
                )
                count = len(items) if isinstance(items, list) else 0
                entity_name = path.split("/")[-1]
                return count > 0, entity_name, count
        except Exception as e:
            logger.debug("crud_check %s %s: %s", run_id, path, e)
    return False, "", 0


# ---------------------------------------------------------------------------
# Single-run evaluator
# ---------------------------------------------------------------------------

async def evaluate_single(
    idx: int,
    domain: str,
    prompt: str,
    base_url: str,
    platform_email: str,
    platform_password: str,
    run_timeout: float = 900.0,
) -> EvalResult:
    """Run a single golden prompt end-to-end and return its EvalResult."""
    result = EvalResult(prompt_idx=idx, domain=domain, prompt=prompt)
    start = time.monotonic()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        # 1. Platform login
        platform_token = await _login(client, base_url, platform_email, platform_password)
        if not platform_token:
            result.error = "Platform login failed"
            result.duration_seconds = round(time.monotonic() - start, 1)
            return result

        # 2. Submit run
        run_id = await _start_run(client, base_url, platform_token, domain, prompt)
        if not run_id:
            result.error = "Failed to start run"
            result.duration_seconds = round(time.monotonic() - start, 1)
            return result
        result.run_id = run_id
        logger.info("[%d] run_id=%s started", idx, run_id)

        # 3. Poll to completion
        run_data = await _poll_run(
            client, base_url, platform_token, run_id,
            poll_interval=15.0, timeout=run_timeout,
        )
        status = run_data.get("status", "unknown")
        result.build_passed = status == "completed"
        if not result.build_passed:
            result.error = f"Run ended with status={status}"
            result.duration_seconds = round(time.monotonic() - start, 1)
            # Capture confidence trail even on failure
            result.phase_confidence = run_data.get("phase_confidence", {})
            result.low_confidence_phases = run_data.get("low_confidence_phases", [])
            return result

        # Capture confidence trail from run data
        result.phase_confidence = run_data.get("phase_confidence", {})
        result.low_confidence_phases = run_data.get("low_confidence_phases", [])

        # 4. Health check
        result.health_passed = await _check_health(client, base_url, run_id)

        # 5. Login check — try to get an app token
        app_email, app_password = os.environ.get("EVAL_APP_EMAIL", ""), os.environ.get("EVAL_APP_PASSWORD", "")
        result.login_passed = bool(app_email and app_password) and await _check_login(
            client, base_url, run_id, app_email, app_password)
        app_token = ""
        if result.login_passed:
            # Re-run to capture the token for CRUD
            try:
                for url in [
                    f"{base_url}/run-app/{run_id}/auth/login",
                    f"{base_url}/run-app/{run_id}/api/auth/login",
                ]:
                    r = await client.post(
                        url,
                        json={"email": app_email, "password": app_password},
                        timeout=10.0,
                    )
                    if r.status_code == 200:
                        app_token = r.json().get("access_token", "")
                        break
            except Exception as e:
                logger.debug("Could not re-fetch app token: %s", e)

        # 6. CRUD check
        crud_ok, entity_name, crud_count = await _check_crud(
            client, base_url, run_id, app_token, platform_token,
        )
        result.crud_passed = crud_ok
        result.crud_entity = entity_name
        result.crud_count = crud_count

    result.duration_seconds = round(time.monotonic() - start, 1)
    return result


# ---------------------------------------------------------------------------
# Batch evaluator
# ---------------------------------------------------------------------------

async def run_harness(
    base_url: str,
    platform_email: str,
    platform_password: str,
    concurrency: int = 3,
    golden_idx: Optional[int] = None,
    run_timeout: float = 900.0,
) -> list[EvalResult]:
    """Run all (or one) golden prompts with bounded concurrency."""
    if golden_idx is not None:
        prompts = [(golden_idx, GOLDEN_PROMPTS[golden_idx][0], GOLDEN_PROMPTS[golden_idx][1])]
    else:
        prompts = [(i, d, p) for i, (d, p) in enumerate(GOLDEN_PROMPTS)]

    sem = asyncio.Semaphore(concurrency)
    results: list[EvalResult] = []

    async def bounded(idx: int, domain: str, prompt: str) -> EvalResult:
        async with sem:
            logger.info("[%d/%d] Starting: %s…", idx + 1, len(GOLDEN_PROMPTS), prompt[:60])
            return await evaluate_single(
                idx, domain, prompt, base_url,
                platform_email, platform_password, run_timeout,
            )

    tasks = [bounded(i, d, p) for i, d, p in prompts]
    for coro in asyncio.as_completed(tasks):
        try:
            r = await coro
            results.append(r)
        except Exception as e:
            logger.warning("Unexpected task error: %s", e)

    results.sort(key=lambda r: r.prompt_idx)
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_summary(results: list[EvalResult]) -> None:
    n = len(results)
    builds  = sum(1 for r in results if r.build_passed)
    health  = sum(1 for r in results if r.health_passed)
    logins  = sum(1 for r in results if r.login_passed)
    cruds   = sum(1 for r in results if r.crud_passed)

    print()
    print("=" * 72)
    print(f"  AetherOS Eval Harness — {n} golden prompts")
    print("=" * 72)
    header = f"{'#':>3}  {'Domain':<14} {'Build':>5} {'Health':>6} {'Login':>5} {'CRUD':>4}  {'secs':>6}  Notes"
    print(header)
    print("-" * 72)
    for r in results:
        b = "PASS" if r.build_passed else "FAIL"
        h = "PASS" if r.health_passed else ("----" if not r.build_passed else "FAIL")
        l = "PASS" if r.login_passed else ("----" if not r.build_passed else "FAIL")
        c = "PASS" if r.crud_passed else ("----" if not r.build_passed else "FAIL")
        notes = r.error or (f"{r.crud_entity}({r.crud_count})" if r.crud_passed else "")
        notes = notes[:30]
        print(f"{r.prompt_idx + 1:>3}  {r.domain:<14} {b:>5} {h:>6} {l:>5} {c:>4}  {r.duration_seconds:>6.0f}  {notes}")
    print("-" * 72)
    print(f"{'TOTAL':>3}  {'':14} {builds:>4}/{n} {health:>5}/{n} {logins:>4}/{n} {cruds:>3}/{n}")
    print("=" * 72)

    low_conf_all = sorted({ph for r in results for ph in r.low_confidence_phases})
    if low_conf_all:
        print(f"\nLow-confidence phases seen: {', '.join(low_conf_all)}")
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AetherOS Eval Harness — run 20 golden prompts and report pass/fail",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--base-url", default="http://localhost:8000", help="AetherOS base URL")
    p.add_argument("--email", default="demo@aetheros.ai", help="Platform admin email")
    p.add_argument("--password", default=os.environ.get("AETHER_ADMIN_PASS", ""),
                   help="Platform admin password (default: $AETHER_ADMIN_PASS; required)")
    p.add_argument("--concurrency", type=int, default=3, help="Max parallel builds")
    p.add_argument("--golden-idx", type=int, default=None, help="Run only this prompt index (0-based)")
    p.add_argument("--output", default="", help="Write JSON report to this path")
    p.add_argument("--timeout", type=float, default=900.0, help="Per-run timeout in seconds")
    p.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.password:
        print("error: set --password or $AETHER_ADMIN_PASS", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    results = asyncio.run(
        run_harness(
            base_url=args.base_url.rstrip("/"),
            platform_email=args.email,
            platform_password=args.password,
            concurrency=args.concurrency,
            golden_idx=args.golden_idx,
            run_timeout=args.timeout,
        )
    )

    print_summary(results)

    if args.output:
        payload = [asdict(r) for r in results]
        try:
            with open(args.output, "w") as fh:
                json.dump(payload, fh, indent=2)
            print(f"Report written to {args.output}")
        except Exception as e:
            logger.warning("Could not write output file: %s", e)

    failed = sum(1 for r in results if not r.build_passed or not r.health_passed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
