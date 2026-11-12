"""
AetherOS — /app-preview on the DASHBOARD origin: never serves generated content.

Generated apps are served only by the preview server (gateway/preview_server.py)
on AETHER_PREVIEW_ORIGIN. Served here, their JavaScript would run same-origin
with the dashboard and could read its tokens and call the platform API as the
signed-in user.

/app-preview/* here always answers 404: each run has an origin of its own
(<run-id>.<preview host>) that only POST /factory/runs/{id}/preview-session opens.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(tags=["app-preview"])


@router.api_route("/app-preview", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
                  include_in_schema=False)
@router.api_route("/app-preview/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
                  include_in_schema=False)
async def app_preview_elsewhere(request: Request, path: str = "") -> Response:
    """Public on purpose: returns no data. Generated apps live on per-run origins
    (<run-id>.<preview host>) reached only through POST /factory/runs/{id}/preview-session,
    so an old /app-preview link on the dashboard origin has nowhere to redirect to."""
    return Response("Open the preview from the dashboard.", status_code=404, media_type="text/plain")
