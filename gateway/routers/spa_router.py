"""
AetherOS — Dashboard SPA Router
GET /dashboard           — serve the React SPA index.html
GET /dashboard/{path}    — serve static assets or fall back to index.html
"""
from __future__ import annotations

import logging
import os
import pathlib

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["spa"])

# Resolve dashboard dist relative to this file:
# __file__ = .../gateway/routers/spa_router.py
# dist     = .../dashboard/dist/
_DIST = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../dashboard/dist")
)

_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


def _file_inside(base: str, rel: str):
    """Real path of base/rel if it is a file that really lives under base, else None.

    A plain startswith(base) also accepted a sibling such as dist-old/ or dist_secrets/, and
    isfile follows links out of the tree; the resolved path must be inside the resolved base.
    """
    root = os.path.realpath(base)
    target = os.path.realpath(os.path.join(root, rel))
    if os.path.commonpath([root, target]) == root and target != root and os.path.isfile(target):
        return target
    return None


if os.path.isdir(_DIST):
    logger.debug("SPA router: dashboard dist found at %s", _DIST)

    @router.get("/dashboard", include_in_schema=False)
    @router.get("/dashboard/{path:path}", include_in_schema=False)
    async def _dashboard_spa(request: Request, path: str = ""):
        _index = os.path.join(_DIST, "index.html")
        if path:
            candidate = _file_inside(_DIST, path)
            if candidate:
                return FileResponse(candidate)
        # Inject CSP nonce into index.html <script> tags (M-10)
        nonce = getattr(request.state, "csp_nonce", "")
        try:
            html = pathlib.Path(_index).read_text(encoding="utf-8")
            if nonce:
                html = html.replace("<script ", f'<script nonce="{nonce}" ')
                html = html.replace("<script>", f'<script nonce="{nonce}">')
            return HTMLResponse(html, headers=_NO_CACHE)
        except Exception as e:
            logger.warning("spa_router: could not read index.html, falling back to FileResponse: %s", e)
            return FileResponse(_index, headers=_NO_CACHE)

else:
    logger.warning("SPA router: dashboard dist not found at %s — /dashboard routes will return 404", _DIST)

    @router.get("/dashboard", include_in_schema=False)
    @router.get("/dashboard/{path:path}", include_in_schema=False)
    async def _dashboard_spa_missing(request: Request, path: str = ""):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=404,
            content={"detail": "Dashboard not built. Run: cd dashboard && npm run build"},
        )
