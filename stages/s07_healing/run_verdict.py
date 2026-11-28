"""Stage 7 verdict: did the generated app actually start and answer HTTP (KAN-247).

A run used to reach "completed" without the app ever starting: a static quality score >= 80 made s07 skip the app
start, record healing_passed=True and pass its gate unconditionally. These rules decide s07 from what happened to the
running app instead, and are pure (the HTTP sender is injected) so tests can drive them without the docker sandbox:

  * the app started: the probe's L1 (/health 200) passed;
  * every list endpoint of the spec (GET /api/<table>) answered with neither a 5xx nor a 404 (a 404 means the spec'd
    endpoint is missing; a 401/403 still proves the route exists and the app handled the request);
  * the healing loop did not end exhausted (unit tests still failing);
  * the live tests that s06 defers here (performance, accessibility, e2e) ran and passed. One that did not run or
    failed does not block the gate, but is listed under "not_verified" so the run is never reported as fully passed.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from aether_os.core.codegen.entities import normalise_entities

logger = logging.getLogger(__name__)

# send(method, url, json_body, headers) -> (status code, parsed JSON body or None); raises when nothing answers.
Sender = Callable[[str, str, Optional[Any], Optional[Dict[str, str]]], Awaitable[Tuple[int, Any]]]

# The s06 layers that need the running app, and the key their metadata has in the consolidated live-test dict.
LIVE_LAYERS = {
    "performance_testing": "perf_results",
    "accessibility_testing": "a11y_results",
    "e2e_testing": "e2e_results",
}

_PROBE_EMAIL = "s07-probe@example.com"


async def httpx_sender(method: str, url: str, body: Optional[Any] = None,
                       headers: Optional[Dict[str, str]] = None) -> Tuple[int, Any]:
    """The real sender: one HTTP request with httpx, following the /api/x -> /api/x/ redirect."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        resp = await client.request(method, url, json=body, headers=headers or {})
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, None


def spec_list_paths(raw_entities: Any) -> List[str]:
    """GET paths of the spec's entities, as the generated backend mounts them (/api/<table>, see p04a)."""
    return [f"/api/{e['table']}" for e in normalise_entities(raw_entities, drop_auth_user=True) if e.get("table")]


async def _login_token(base_url: str, send: Sender, password: str) -> str:
    """Register + log in a throw-away account so the list probes reach the handlers, not just the auth guard."""
    creds = {"email": _PROBE_EMAIL, "password": password, "name": "Probe"}
    try:
        await send("POST", f"{base_url}/api/auth/register", creds, None)
        status, body = await send("POST", f"{base_url}/api/auth/login",
                                  {"email": _PROBE_EMAIL, "password": password}, None)
    except Exception as exc:
        logger.warning("[s07] probe login failed: %s", exc)
        return ""
    if status == 200 and isinstance(body, dict):
        return str(body.get("access_token") or body.get("token") or "")
    return ""


async def probe_endpoints(base_url: str, raw_entities: Any, send: Sender, password: str) -> Dict[str, Any]:
    """GET /health and every spec'd list endpoint on the running app; passed only if each one answered properly."""
    checks: List[Dict[str, Any]] = []
    failures: List[str] = []

    async def _get(path: str, headers: Optional[Dict[str, str]]) -> Optional[int]:
        try:
            status, _ = await send("GET", f"{base_url}{path}", None, headers)
            return status
        except Exception as exc:
            failures.append(f"GET {path}: no answer ({exc})")
            checks.append({"path": path, "status": None})
            return None

    health = await _get("/health", None)
    if health is not None:
        checks.append({"path": "/health", "status": health})
        if health != 200:
            failures.append(f"GET /health returned {health}")

    token = await _login_token(base_url, send, password)
    headers = {"Authorization": f"Bearer {token}"} if token else None
    paths = spec_list_paths(raw_entities)
    for path in paths:
        status = await _get(path, headers)
        if status is None:
            continue
        checks.append({"path": path, "status": status})
        if status >= 500 or status == 404:
            failures.append(f"GET {path} returned {status}")
    return {"passed": not failures, "checks": checks, "failures": failures,
            "authenticated": bool(token), "spec_paths": paths}


def live_layer_status(consolidated: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """{layer: "passed" | "failed: why" | "not run: why"} for the three live test layers."""
    consolidated = consolidated or {}
    if consolidated.get("skipped"):
        why = consolidated.get("reason") or "skipped"
        return {key: f"not run: {why}" for key in LIVE_LAYERS}
    errored = [str(i) for i in consolidated.get("skipped_phases") or []]
    per_layer = consolidated.get("phases") or {}
    out: Dict[str, str] = {}
    for key, meta_key in LIVE_LAYERS.items():
        crash = next((i for i in errored if i.startswith(key)), None)
        meta = consolidated.get(meta_key) or {}
        data = meta.get("data") if isinstance(meta.get("data"), dict) else {}
        if crash or key not in per_layer:
            out[key] = f"not run: {crash or 'no result'}"
        elif meta.get("skipped") or data.get("skipped"):
            out[key] = f"not run: {data.get('reason') or meta.get('reason') or 'the test reported itself skipped'}"
        elif (not per_layer[key].get("success") or meta.get("passed") is False
              or int(meta.get("failed") or 0) > 0):
            issues = "; ".join(str(i) for i in per_layer[key].get("issues") or [])[:200]
            out[key] = f"failed: {issues or 'see the test output'}"
        else:
            out[key] = "passed"
    return out


def decide(heal_meta: Dict[str, Any]) -> Dict[str, Any]:
    """The s07 verdict from the healer's metadata (self_healing.json shape, quality_probe included).

    passed: the app started, its spec'd endpoints answered and healing did not end exhausted.
    """
    probe = heal_meta.get("quality_probe") or {}
    hook = probe.get("live_tests") if isinstance(probe.get("live_tests"), dict) else {}
    endpoints = hook.get("endpoints") if isinstance(hook.get("endpoints"), dict) else None
    reasons: List[str] = []

    if heal_meta.get("self_healing_exhausted") or heal_meta.get("status") in ("max_attempts_reached", "phase_timeout"):
        reasons.append(f"healing did not get the unit tests passing ({heal_meta.get('status')})")
    app_started = bool(probe.get("l1_passed"))
    if not app_started:
        why = probe.get("reason") or ("the probe never ran: unit tests were not passing"
                                      if not probe else "/health did not return 200")
        reasons.append(f"the generated app did not start and answer HTTP: {why}")
    elif endpoints is None:
        reasons.append("the spec'd endpoints were not probed on the running app")
    elif not endpoints.get("passed"):
        reasons.append("spec'd endpoints failed on the running app: " + "; ".join(endpoints.get("failures") or [])[:400])

    layers = live_layer_status(hook.get("tests") if app_started else
                               {"skipped": True, "reason": "the app did not start"})
    not_verified = [f"{key}: {status}" for key, status in layers.items() if status != "passed"]
    return {
        "passed": not reasons,
        "app_started": app_started,
        "endpoints": endpoints,
        "live_layers": layers,
        "reasons": reasons,
        "not_verified": not_verified,
    }
