"""
WebSocket endpoint and PWA/service-worker routes for DCSP.

Extracted from main.py to keep that file under 600 lines.
The FastAPI `app` instance is imported from main_app.py (or passed in).
All routes here are registered on the shared `app` object imported from
src.api.app_instance — but to avoid circular imports we accept the app
via register_routes() called from main.py after app creation.
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


def register_routes(app: FastAPI) -> None:
    """Register all routes in this module onto the given FastAPI app."""

    from src.api.websocket_manager import MANAGER

    @app.websocket("/ws/dashboard")
    async def websocket_dashboard(websocket: WebSocket):
        # Read-only event stream — no auth required (no actions can be taken via WS).
        await MANAGER.connect(websocket)
        try:
            # Send current state on connect
            from src.api.state import JOB_HISTORY
            await websocket.send_text(json.dumps({
                "type": "init",
                "jobs": JOB_HISTORY[-20:]
            }))
            # Keep alive - listen for pings
            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text(
                        json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            MANAGER.disconnect(websocket)
        except Exception as e:
            logger.warning("WebSocket error, disconnecting: %s", e)
            MANAGER.disconnect(websocket)

    @app.get("/manifest.json")
    async def pwa_manifest():
        return {
            "name": "DCSP - Code Self-healing",
            "short_name": "DCSP",
            "description": "AI-powered CI repair pipeline",
            "start_url": "/dashboard",
            "display": "standalone",
            "background_color": "#0d1117",
            "theme_color": "#58a6ff",
            "icons": [
                {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
            ],
            "categories": ["developer tools", "productivity"],
            "shortcuts": [
                {"name": "Dashboard", "url": "/dashboard", "description": "View repair jobs"},
                {"name": "Incidents", "url": "/dashboard/incidents", "description": "View active incidents"}
            ]
        }

    @app.get("/sw.js")
    async def service_worker():
        from fastapi.responses import Response
        sw_code = """
const CACHE_NAME = 'dcsp-v1';
const CACHED_URLS = [
    '/dashboard',
    '/manifest.json'
];

self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE_NAME).then(
            cache => cache.addAll(CACHED_URLS))
    );
});

self.addEventListener('fetch', e => {
    e.respondWith(
        fetch(e.request).catch(() =>
            caches.match(e.request))
    );
});

self.addEventListener('push', e => {
    const data = e.data ? e.data.json() : {};
    e.waitUntil(
        self.registration.showNotification(
            data.title || 'DCSP Alert',
            { body: data.body || '', icon: '/static/icon-192.png' }
        )
    );
});
""".strip()
        return Response(content=sw_code, media_type="application/javascript")

    @app.get("/api/intelligence/predictions")
    async def get_predictions(request: Request):
        """Get failure predictions."""
        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        if not verify_session_token(token):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from src.intelligence.predictor import PREDICTOR
        results = PREDICTOR.predict_all()
        return {
            "predictions": [
                {
                    "error_type": r.error_type,
                    "language": r.language,
                    "recurrence_score": r.recurrence_score,
                    "predicted_severity": r.predicted_severity,
                    "occurrence_count": r.occurrence_count,
                    "is_likely_to_recur": r.is_likely_to_recur,
                    "contributing_repos": r.contributing_repos
                }
                for r in results
            ],
            "total": len(results)
        }

    @app.get("/api/sandbox/status")
    async def sandbox_status(request: Request):
        """Check sandbox availability."""
        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        if not verify_session_token(token):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from src.sandbox.docker_sandbox import (
            is_sandbox_available, SANDBOX_IMAGE, SANDBOX_TIMEOUT
        )
        return {
            "available": is_sandbox_available(),
            "image": SANDBOX_IMAGE,
            "timeout": SANDBOX_TIMEOUT,
            "memory": "128m"
        }

    @app.get("/api/security/audit")
    async def security_audit(request: Request):
        """Run security audit and return results."""
        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        if not verify_session_token(token):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from src.security.audit import run_security_audit, get_audit_summary
        report = run_security_audit()
        return get_audit_summary(report)

    @app.get("/api/notifications/status")
    async def notification_status(request: Request):
        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        if not verify_session_token(token):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from src.notifications.push_notifier import (
            is_notifications_enabled, list_device_tokens, get_notification_log
        )
        return {
            "enabled": is_notifications_enabled(),
            "device_count": len(list_device_tokens()),
            "recent_notifications": get_notification_log(10)
        }

    @app.post("/api/notifications/register")
    async def register_device(request: Request):
        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        user = verify_session_token(token)
        if not user:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        device_token = body.get("token", "")
        platform = body.get("platform", "web")
        from src.notifications.push_notifier import register_device_token
        ok = register_device_token(device_token, user, platform)
        return {"registered": ok}

    @app.get("/api/secrets/status")
    async def secrets_status(request: Request):
        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        if not verify_session_token(token):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from src.secrets.secret_manager import is_vault_enabled, list_secret_keys
        return {
            "vault_enabled": is_vault_enabled(),
            "vault_addr": os.getenv("VAULT_ADDR", ""),
            "secret_count": len(list_secret_keys()),
            "keys": list_secret_keys()
        }

    @app.post("/api/secrets/set")
    async def set_secret_endpoint(request: Request):
        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        if not verify_session_token(token):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        key = body.get("key", "")
        value = body.get("value", "")
        if not key or not value:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "key and value required"}, status_code=400)
        from src.secrets.secret_manager import set_local_secret
        set_local_secret(key, value)
        return {"set": True, "key": key}

    @app.post("/api/secrets/rotate")
    async def rotate_secret_endpoint(request: Request):
        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        if not verify_session_token(token):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body = await request.json()
        key = body.get("key", "")
        new_value = body.get("value", "")
        if not key or not new_value:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "key and value required"}, status_code=400)
        from src.secrets.secret_manager import rotate_secret
        ok = rotate_secret(key, new_value)
        return {"rotated": ok, "key": key}

    @app.get("/api/queue/stats")
    async def get_queue_stats_endpoint(request: Request):
        """Queue statistics endpoint."""
        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        if not verify_session_token(token):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from src.queue.worker import get_queue_stats
        return get_queue_stats()

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        token = request.cookies.get("session_token")
        from src.api.auth import verify_session_token
        if not verify_session_token(token):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from src.api.state import JOB_HISTORY
        # Search in-memory first
        for job in JOB_HISTORY:
            if job.get("id") == job_id:
                return job
        # Then search DB
        from src.db.job_repo import get_job_by_id
        from src.database import SessionLocal
        session = SessionLocal()
        try:
            job = get_job_by_id(session, job_id)
            if job:
                import json as _json
                _violations = []
                if job.violations:
                    try:
                        _violations = _json.loads(job.violations)
                    except Exception as e:
                        logger.warning("Failed to parse violations JSON for job %s: %s", job_id, e)
                        _violations = []
                return {
                    "id": str(job.id),
                    "repo_name": job.repo_name,
                    "branch": job.branch,
                    "commit_sha": job.commit_sha,
                    "success": job.success,
                    "confidence": job.confidence,
                    "error_type": getattr(job, "error_type", ""),
                    "patch_diff": job.patch_diff,
                    "timestamp": str(job.timestamp),
                    "sandbox_result": job.sandbox_result,
                    "explanation": job.explanation,
                    "ci_system": job.ci_system,
                    "detected_language": job.detected_language,
                    "escalated": job.escalated,
                    "approved": job.approved,
                    "approved_pr_url": job.approved_pr_url,
                    "slm_generated": job.slm_generated,
                    "source": job.source,
                    "fingerprint": job.fingerprint,
                    "violations": _violations,
                    "patch_edited": job.patch_edited,
                }
        finally:
            session.close()
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Job not found"}, status_code=404)
