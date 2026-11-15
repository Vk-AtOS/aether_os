"""What is up, degraded or down right now: the data behind /readyz and the dashboard's degraded-component banner.

Blast-radius design (KAN-52 checks it): Postgres down = not ready (nothing can be served). Redis down = not ready only when
REQUIRE_REDIS is true, because rate limits and revocations then cannot be trusted; otherwise degraded. Velaris and model
providers are optional: they show as degraded and never make the API unready, so guards and approvals keep working.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from sqlalchemy import text

from aether_os.core.resilience.breaker import all_breakers
from aether_os.core.resilience.bulkhead import all_bulkheads

logger = logging.getLogger(__name__)

OK, DEGRADED, DOWN = "ok", "degraded", "down"


async def check_postgres(timeout: float = 3.0) -> Dict[str, Any]:
    from aether_os.core.db import get_session_factory
    try:
        async def _probe() -> None:
            async with get_session_factory()() as s:
                await s.execute(text("SELECT 1"))
        await asyncio.wait_for(_probe(), timeout)
        return {"status": OK}
    except Exception as e:
        logger.warning("readiness: postgres probe failed: %s", type(e).__name__)
        return {"status": DOWN, "error": type(e).__name__}


async def check_redis(timeout: float = 2.0) -> Dict[str, Any]:
    from aether_os.core.pipeline_state import get_redis
    try:
        client = await asyncio.wait_for(get_redis(), timeout)
        if client is None:
            return {"status": DOWN, "error": "unreachable"}
        await asyncio.wait_for(client.ping(), timeout)
        return {"status": OK}
    except Exception as e:
        logger.warning("readiness: redis probe failed: %s", type(e).__name__)
        return {"status": DOWN, "error": type(e).__name__}


def check_velaris() -> Dict[str, Any]:
    if not os.environ.get("VELARIS_API_URL", "").strip():
        return {"status": OK, "configured": False}
    b = all_breakers().get("velaris")
    if b is None or b.state == "closed":
        return {"status": OK, "configured": True}
    return {"status": DEGRADED, "configured": True, "breaker": b.snapshot()}


def check_models() -> Dict[str, Any]:
    from aether_os.core.model_router_providers import _DEAD_MODELS, _DEAD_PROVIDERS, _is_dead
    open_ = sorted({p for (scope, p) in list(_DEAD_PROVIDERS) if _is_dead(_DEAD_PROVIDERS, scope, p)}
                   | {m for (scope, m) in list(_DEAD_MODELS) if _is_dead(_DEAD_MODELS, scope, m)})
    return {"status": DEGRADED if open_ else OK, "open_breakers": open_}


async def snapshot() -> Dict[str, Any]:
    pg, rd = await asyncio.gather(check_postgres(), check_redis())
    require_redis = os.environ.get("REQUIRE_REDIS", "false").lower() == "true" or os.environ.get("ENVIRONMENT") == "production"
    if rd["status"] == DOWN and not require_redis:
        rd = {**rd, "status": DEGRADED}
    comps = {"postgres": pg, "redis": rd, "velaris": check_velaris(), "models": check_models()}
    return {
        "ready": pg["status"] == OK and rd["status"] != DOWN,
        "degraded": sorted(k for k, v in comps.items() if v["status"] != OK),
        "components": comps,
        "breakers": [b.snapshot() for b in all_breakers().values()],
        "bulkheads": [b.snapshot() for b in all_bulkheads().values()],
    }
