"""
AetherOS — /app-preview on the DASHBOARD origin: never serves generated content.

Generated apps are served only by the preview server (gateway/preview_server.py)
on AETHER_PREVIEW_ORIGIN. Served here, their JavaScript would run same-origin
with the dashboard and could read its tokens and call the platform API as the
signed-in user.

/app-preview/* here answers 307 to the same path on the preview origin, so old
links (live_url "/app-preview/") land somewhere that explains how to open the
preview; it carries nothing, and the preview origin still demands its own
session. When the preview origin is not configured, or equals this origin,
the answer is 404 (fail closed: no redirect loop, no content).
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from aether_os.core.run_app import preview_token

router = APIRouter(tags=["app-preview"])


@router.api_route("/app-preview", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
                  include_in_schema=False)
@router.api_route("/app-preview/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
                  include_in_schema=False)
async def app_preview_elsewhere(request: Request, path: str = "") -> Response:
    """Public on purpose: it only points at the preview origin and returns no data."""
    origin = preview_token.preview_origin()
    same_host = origin and urlsplit(origin).netloc == request.headers.get("host", "").lower()
    if not origin or same_host or origin == preview_token.dashboard_origin():
        return Response("Not found", status_code=404, media_type="text/plain")
    return RedirectResponse(f"{origin}/app-preview/{path}", status_code=307)
