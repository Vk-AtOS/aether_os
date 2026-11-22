"""Route enumeration for FastAPI 0.16x / Starlette 1.x.

FastAPI 0.16x no longer copies an included router's routes into the parent: every include_router() call appends
one opaque `_IncludedRouter` to `app.routes`, and the prefixed APIRoutes exist only as "effective route contexts"
built from it. Two things that used to be true are not any more:

  * `for r in app.routes` sees top-level routes, Mounts and `_IncludedRouter` objects (no path, no methods), so
    every walk over it silently skips almost the whole API;
  * `request.scope["route"]` is the APIRoute object as declared inside its router, so its `.path` lacks every
    include prefix ("/{run_id}" instead of "/factory/runs/{run_id}").

Use `iter_routes(app.routes)` for the first and `route_template(scope)` for the second.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional

from fastapi.routing import iter_route_contexts


def iter_routes(routes: Iterable[Any]) -> List[Any]:
    """Every route the app serves, included routers flattened. Each item has the served `path` (all include
    prefixes applied), `methods`, `endpoint`, `name`, and for API routes the effective `dependant` and
    `dependencies` (router-level dependencies included), as the app really serves them."""
    return list(iter_route_contexts(list(routes)))


def route_template(scope: Mapping[str, Any]) -> Optional[str]:
    """Path template of the route that is handling this request, with every include prefix, or None."""
    route = scope.get("route")
    ctx = (scope.get("fastapi") or {}).get("effective_route_context")
    if route is not None and ctx is not None and getattr(ctx, "original_route", None) is route:
        effective = getattr(ctx, "starlette_route", None) or ctx
        path = getattr(effective, "path", None)
        if path:
            return path
    return getattr(route, "path", None)
