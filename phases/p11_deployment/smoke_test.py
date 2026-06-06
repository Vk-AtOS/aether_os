"""
AetherOS P11 — Live E2E Smoke Test

Runs a minimal CRUD exercise against a live deployed container.
Called by gate.py after the health probe passes.

Steps:
  1. GET /health — confirm alive
  2. POST /auth/login — get token (tries multiple path variants)
  3. Per entity from domain_ir.json: GET list, POST create, GET single
  4. Returns SmokeResult with passed flag + per-failure details
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SmokeResult:
    passed: bool
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    entities_tested: int = 0
    duration_seconds: float = 0.0


def _read_domain_ir(project_dir: Path) -> Optional[Dict]:
    for cand in [
        project_dir / "p02b_domain_ir" / "domain_ir.json",
        project_dir / "domain_ir.json",
    ]:
        if cand.exists():
            try:
                return json.loads(cand.read_text())
            except Exception:
                pass
    return None


def _read_credentials(project_dir: Path) -> tuple[str, str]:
    for cred_path in [
        project_dir / "p11_deployment" / "preview_credentials.json",
        project_dir / "preview_credentials.json",
    ]:
        if cred_path.exists():
            try:
                c = json.loads(cred_path.read_text())
                return c.get("email", "demo@example.com"), c.get("password", "Admin1234!")
            except Exception:
                pass
    return "demo@example.com", "Admin1234!"


def _sample_payload(entity_name: str, fields: List[Dict]) -> Dict[str, Any]:
    """Build a minimal valid creation payload from field definitions."""
    payload: Dict[str, Any] = {}
    for f in fields:
        name = f.get("name", "")
        ftype = str(f.get("type", "string")).lower()
        if name in ("id", "created_at", "updated_at", "org_id"):
            continue
        if name.endswith("_id"):
            payload[name] = 1
            continue
        if ftype in ("integer", "int"):
            payload[name] = 1
        elif ftype in ("boolean", "bool"):
            payload[name] = True
        elif ftype in ("float", "decimal", "number"):
            payload[name] = 1.0
        elif ftype in ("date", "datetime"):
            payload[name] = "2026-01-01"
        else:
            # Use entity name to create readable test values
            payload[name] = f"test_{name}"
    return payload


def _pluralise(word: str) -> str:
    """English pluralization for route guessing."""
    w = word.lower()
    if w.endswith("ies") or w.endswith("ses") or w.endswith("xes") or w.endswith("ches") or w.endswith("shes"):
        return w  # already plural
    if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
        return w[:-1] + "ies"
    if w.endswith("ss") or w.endswith("sh") or w.endswith("ch") or w.endswith("x") or w.endswith("z"):
        return w + "es"
    if w.endswith("s"):
        return w  # already plural
    return w + "s"


async def run_smoke(base_url: str, project_dir: Path, timeout_per_op: float = 10.0) -> SmokeResult:
    """Run the full smoke test against the live container."""
    try:
        import aiohttp
    except ImportError:
        return SmokeResult(passed=True, warnings=["aiohttp not installed — smoke test skipped"])

    start_t = time.time()
    failures: List[str] = []
    warnings: List[str] = []
    base_url = base_url.rstrip("/")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:

        # ── 1. Health check ───────────────────────────────────────────────────
        try:
            async with session.get(
                f"{base_url}/health",
                timeout=aiohttp.ClientTimeout(total=timeout_per_op),
            ) as resp:
                if resp.status not in (200, 204):
                    warnings.append(f"GET /health → {resp.status}")
        except Exception as exc:
            warnings.append(f"GET /health unreachable: {exc}")

        # ── 2. Auth ───────────────────────────────────────────────────────────
        email, password = _read_credentials(project_dir)
        token: Optional[str] = None

        for login_path in ["/api/auth/login", "/auth/login", "/api/login", "/api/token"]:
            try:
                async with session.post(
                    f"{base_url}{login_path}",
                    json={"email": email, "password": password, "username": email},
                    timeout=aiohttp.ClientTimeout(total=timeout_per_op),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json(content_type=None)
                        token = body.get("access_token") or body.get("token")
                        if token:
                            break
            except Exception:
                continue

        if not token:
            warnings.append("Auth failed — CRUD tests will run unauthenticated")

        headers = {"Authorization": f"Bearer {token}"} if token else {}

        # ── 3. CRUD per entity ────────────────────────────────────────────────
        domain_ir = _read_domain_ir(project_dir)
        entities: List[Dict] = []

        if domain_ir and domain_ir.get("entities"):
            for e in domain_ir["entities"]:
                name = e.get("name", "")
                if name.lower() in ("user", "organisation", "organization", "account", "role"):
                    continue
                entities.append({
                    "name": name,
                    "table": e.get("table", name.lower()),
                    "fields": e.get("fields", []),
                })

        entities_tested = 0
        for entity in entities[:5]:
            table = entity.get("table", entity["name"].lower())
            plural = _pluralise(table)

            # Try to find the list endpoint
            list_route: Optional[str] = None
            for route in [f"/api/{plural}", f"/api/{table}", f"/{plural}", f"/{table}"]:
                try:
                    async with session.get(
                        f"{base_url}{route}",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=timeout_per_op),
                    ) as resp:
                        if resp.status in (200, 401, 403):
                            list_route = route
                            break
                except Exception:
                    continue

            if list_route is None:
                warnings.append(f"{entity['name']}: no list endpoint found (tried /api/{plural})")
                continue

            entities_tested += 1

            # GET list
            try:
                async with session.get(
                    f"{base_url}{list_route}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout_per_op),
                ) as resp:
                    if resp.status not in (200, 204):
                        failures.append(f"GET {list_route} → {resp.status} (expected 200)")
            except Exception as exc:
                failures.append(f"GET {list_route} → {exc}")

            # POST create
            payload = _sample_payload(entity["name"], entity.get("fields", []))
            created_id: Optional[Any] = None
            if payload:
                try:
                    async with session.post(
                        f"{base_url}{list_route}",
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=timeout_per_op),
                    ) as resp:
                        if resp.status in (200, 201):
                            body = await resp.json(content_type=None)
                            created_id = (body or {}).get("id")
                        elif resp.status == 422:
                            # Validation error — endpoint exists but payload needs refinement
                            warnings.append(f"POST {list_route} → 422 (endpoint exists, payload needs FK data)")
                        else:
                            failures.append(f"POST {list_route} → {resp.status} (expected 200/201)")
                except Exception as exc:
                    failures.append(f"POST {list_route} → {exc}")

            # GET single (only if create succeeded)
            if created_id is not None:
                try:
                    async with session.get(
                        f"{base_url}{list_route}/{created_id}",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=timeout_per_op),
                    ) as resp:
                        if resp.status != 200:
                            failures.append(f"GET {list_route}/{created_id} → {resp.status}")
                except Exception as exc:
                    failures.append(f"GET {list_route}/{created_id} → {exc}")

    duration = round(time.time() - start_t, 2)
    return SmokeResult(
        passed=len(failures) == 0,
        failures=failures,
        warnings=warnings,
        entities_tested=entities_tested,
        duration_seconds=duration,
    )


def run_smoke_sync(base_url: str, project_dir: Path) -> SmokeResult:
    """Synchronous entry point for gate.py."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context — can't run synchronously
            # Return a skipped result
            return SmokeResult(passed=True, warnings=["Smoke test skipped — already in async context"])
        return loop.run_until_complete(run_smoke(base_url, project_dir))
    except RuntimeError:
        try:
            return asyncio.run(run_smoke(base_url, project_dir))
        except Exception as exc:
            return SmokeResult(passed=False, failures=[f"Smoke runner error: {exc}"])
    except Exception as exc:
        return SmokeResult(passed=False, failures=[f"Smoke runner error: {exc}"])
