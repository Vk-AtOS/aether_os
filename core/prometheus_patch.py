"""
Monkey-patch for prometheus_fastapi_instrumentator routing.

FastAPI 0.13x adds _IncludedRouter objects to app.routes. These objects have
.matches() but no .path attribute, causing AttributeError in the prometheus
route resolver on every request. This patch wraps _get_route_name to skip
objects that don't have .path, making instrumentation degrade gracefully.

Applied once at app startup before Instrumentator().instrument(app).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def apply() -> None:
    try:
        from starlette.routing import Match
        import prometheus_fastapi_instrumentator.routing as _pfi

        def _safe_resolver(scope, routes, route_name=None):
            for route in routes:
                if not (hasattr(route, "matches") and hasattr(route, "path")):
                    continue
                try:
                    match, child_scope = route.matches(scope)
                except Exception as exc:
                    logger.debug("prometheus_patch: route.matches() failed, skipping route: %s", exc)
                    continue
                if match == Match.FULL:
                    route_name = route.path
                    child_scope = {**scope, **child_scope}
                    if hasattr(route, "routes") and route.routes:
                        child = _safe_resolver(child_scope, route.routes, route_name)
                        route_name = None if child is None else route_name + child
                    return route_name
                elif match == Match.PARTIAL and route_name is None:
                    route_name = route.path
            return route_name

        _pfi._get_route_name = _safe_resolver
    except Exception as exc:
        logger.debug("prometheus_patch.apply: library not installed or incompatible — instrumentation skipped: %s", exc)
