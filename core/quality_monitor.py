"""
QualityMonitor — multi-layer health check for generated apps.

Layers (run in order, stop on first fatal failure):
  L1 startup  — GET /health returns 200
  L2 auth     — POST /auth/login with seeded admin credentials returns access_token
  L3 crud     — GET /<first_entity>/ with token returns list (200, list type)
  L4 data     — list response has at least 1 record (seed ran)

Usage::

    monitor = QualityMonitor(
        base_url="http://127.0.0.1:8765",
        admin_email="admin@example.com",
        admin_password=os.environ["ADMIN_PASSWORD"],
        entities=["Product", "Order"],
    )
    results = await monitor.run_full_check()
    failure_type = monitor.get_failure_type(results)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10.0  # seconds per probe call


@dataclass
class HealthCheckResult:
    layer: str          # "startup" | "auth" | "crud" | "data"
    passed: bool
    status_code: Optional[int]
    message: str
    latency_ms: float
    failure_type: Optional[str]  # "crash" | "auth_failure" | "empty_crud" | "seed_failure" | None


class QualityMonitor:
    """Deterministic multi-layer health prober for a running generated FastAPI app."""

    def __init__(
        self,
        base_url: str,
        admin_email: str,
        admin_password: str,  # no default: a baked-in password is how every app got the same one
        entities: Optional[List[str]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_email = admin_email
        self.admin_password = admin_password
        # Store entity names as provided; _crud_path() converts them to URL paths
        self.entities: List[str] = entities or []
        # Populated after run_full_check completes so to_dict() can read them
        self._results: List[HealthCheckResult] = []

    # ── Helpers ──────────────────────────────────────────────────────────────────

    def _crud_path(self) -> Optional[str]:
        """Return the GET list path for the first entity, or None if no entities."""
        if not self.entities:
            return None
        # "InvoiceItem" → "/invoiceitems/"  (lowercase + plural 's')
        entity = self.entities[0]
        plural = entity.lower() + "s"
        return f"/{plural}/"

    # ── Layer checks ─────────────────────────────────────────────────────────────

    async def check_startup(self) -> HealthCheckResult:
        """L1: GET /health must return 200."""
        url = f"{self.base_url}/health"
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(url)
            latency = (time.monotonic() - t0) * 1000
            passed = resp.status_code == 200
            return HealthCheckResult(
                layer="startup",
                passed=passed,
                status_code=resp.status_code,
                message="OK" if passed else f"/health returned {resp.status_code}",
                latency_ms=latency,
                failure_type=None if passed else "crash",
            )
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            logger.warning("[quality_monitor] L1 startup probe failed: %s", exc)
            return HealthCheckResult(
                layer="startup",
                passed=False,
                status_code=None,
                message=f"Connection error: {exc}",
                latency_ms=latency,
                failure_type="crash",
            )

    async def check_auth(self) -> HealthCheckResult:
        """L2: POST /auth/login must return a JSON body containing access_token."""
        url = f"{self.base_url}/auth/login"
        payload: Dict[str, Any] = {
            "email": self.admin_email,
            "password": self.admin_password,
        }
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code == 200:
                body = resp.json()
                token = body.get("access_token") or body.get("token")
                if token:
                    return HealthCheckResult(
                        layer="auth",
                        passed=True,
                        status_code=200,
                        message="access_token obtained",
                        latency_ms=latency,
                        failure_type=None,
                    )
                return HealthCheckResult(
                    layer="auth",
                    passed=False,
                    status_code=200,
                    message="200 OK but no access_token in response body",
                    latency_ms=latency,
                    failure_type="auth_failure",
                )
            return HealthCheckResult(
                layer="auth",
                passed=False,
                status_code=resp.status_code,
                message=f"Login returned {resp.status_code}: {resp.text[:200]}",
                latency_ms=latency,
                failure_type="auth_failure",
            )
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            logger.warning("[quality_monitor] L2 auth probe failed: %s", exc)
            return HealthCheckResult(
                layer="auth",
                passed=False,
                status_code=None,
                message=f"Request error: {exc}",
                latency_ms=latency,
                failure_type="auth_failure",
            )

    async def check_crud(self, token: str) -> HealthCheckResult:
        """L3: GET /<first_entity_plural>/ with bearer token must return a list (or dict with items)."""
        path = self._crud_path()
        if not path:
            return HealthCheckResult(
                layer="crud",
                passed=True,
                status_code=None,
                message="No entities configured — CRUD check skipped",
                latency_ms=0.0,
                failure_type=None,
            )
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(url, headers=headers)
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code == 200:
                body = resp.json()
                # Accept either a list response or a paginated dict with 'items'/'data' key
                is_list = isinstance(body, list) or (
                    isinstance(body, dict) and any(
                        k in body for k in ("items", "data", "results")
                    )
                )
                if is_list:
                    return HealthCheckResult(
                        layer="crud",
                        passed=True,
                        status_code=200,
                        message=f"GET {path} returned list",
                        latency_ms=latency,
                        failure_type=None,
                    )
                return HealthCheckResult(
                    layer="crud",
                    passed=False,
                    status_code=200,
                    message=f"GET {path} returned 200 but body is not a list: {str(body)[:100]}",
                    latency_ms=latency,
                    failure_type="empty_crud",
                )
            return HealthCheckResult(
                layer="crud",
                passed=False,
                status_code=resp.status_code,
                message=f"GET {path} returned {resp.status_code}: {resp.text[:200]}",
                latency_ms=latency,
                failure_type="empty_crud",
            )
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            logger.warning("[quality_monitor] L3 crud probe failed: %s", exc)
            return HealthCheckResult(
                layer="crud",
                passed=False,
                status_code=None,
                message=f"Request error: {exc}",
                latency_ms=latency,
                failure_type="empty_crud",
            )

    async def check_data(self, token: str) -> HealthCheckResult:
        """L4: The list response must contain at least 1 record (confirms seed ran)."""
        path = self._crud_path()
        if not path:
            return HealthCheckResult(
                layer="data",
                passed=True,
                status_code=None,
                message="No entities configured — data check skipped",
                latency_ms=0.0,
                failure_type=None,
            )
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(url, headers=headers)
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code != 200:
                return HealthCheckResult(
                    layer="data",
                    passed=False,
                    status_code=resp.status_code,
                    message=f"GET {path} returned {resp.status_code}",
                    latency_ms=latency,
                    failure_type="seed_failure",
                )
            body = resp.json()
            if isinstance(body, list):
                records = body
            elif isinstance(body, dict):
                records = body.get("items") or body.get("data") or body.get("results") or []
            else:
                records = []

            if records:
                return HealthCheckResult(
                    layer="data",
                    passed=True,
                    status_code=200,
                    message=f"{len(records)} record(s) found in {path}",
                    latency_ms=latency,
                    failure_type=None,
                )
            return HealthCheckResult(
                layer="data",
                passed=False,
                status_code=200,
                message=f"GET {path} returned empty list — seed may not have run",
                latency_ms=latency,
                failure_type="seed_failure",
            )
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            logger.warning("[quality_monitor] L4 data probe failed: %s", exc)
            return HealthCheckResult(
                layer="data",
                passed=False,
                status_code=None,
                message=f"Request error: {exc}",
                latency_ms=latency,
                failure_type="seed_failure",
            )

    # ── Orchestration ─────────────────────────────────────────────────────────────

    async def run_full_check(self) -> List[HealthCheckResult]:
        """Run L1→L2→L3→L4 in order, stopping on the first fatal failure.

        L1 and L2 failures are always fatal (no point checking CRUD if auth is broken).
        L3 failure short-circuits L4 (can't check data if the list endpoint is broken).
        """
        results: List[HealthCheckResult] = []

        # L1 — startup
        l1 = await self.check_startup()
        results.append(l1)
        if not l1.passed:
            logger.warning("[quality_monitor] L1 startup FAILED — %s", l1.message)
            self._results = results
            return results

        # L2 — auth (need token for L3/L4)
        l2 = await self.check_auth()
        results.append(l2)
        if not l2.passed:
            logger.warning("[quality_monitor] L2 auth FAILED — %s", l2.message)
            self._results = results
            return results

        # Extract token for downstream checks
        # We re-login to get the token value — it was already validated in L2
        token = await self._fetch_token()

        # L3 — crud list endpoint
        l3 = await self.check_crud(token)
        results.append(l3)
        if not l3.passed:
            logger.warning("[quality_monitor] L3 crud FAILED — %s", l3.message)
            self._results = results
            return results

        # L4 — seed data present
        l4 = await self.check_data(token)
        results.append(l4)
        if not l4.passed:
            logger.warning("[quality_monitor] L4 data FAILED — %s", l4.message)

        self._results = results
        return results

    async def _fetch_token(self) -> str:
        """Re-issue the login request and return the raw token string."""
        url = f"{self.base_url}/auth/login"
        payload: Dict[str, Any] = {
            "email": self.admin_email,
            "password": self.admin_password,
        }
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                body = resp.json()
                token = body.get("access_token") or body.get("token") or ""
                return token
        except Exception as exc:
            logger.warning("[quality_monitor] _fetch_token failed: %s", exc)
        return ""

    # ── Summary helpers ───────────────────────────────────────────────────────────

    def get_failure_type(self, results: List[HealthCheckResult]) -> Optional[str]:
        """Return the first failure_type encountered across results, or None if all passed."""
        for r in results:
            if not r.passed and r.failure_type:
                return r.failure_type
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialisable summary suitable for accumulated_context or metadata blobs."""
        results = self._results
        all_passed = all(r.passed for r in results)
        failure_type = self.get_failure_type(results)
        return {
            "quality_monitor": {
                "base_url": self.base_url,
                "layers_run": len(results),
                "all_passed": all_passed,
                "failure_type": failure_type,
                "layers": [
                    {
                        "layer": r.layer,
                        "passed": r.passed,
                        "status_code": r.status_code,
                        "message": r.message,
                        "latency_ms": round(r.latency_ms, 1),
                        "failure_type": r.failure_type,
                    }
                    for r in results
                ],
            }
        }
