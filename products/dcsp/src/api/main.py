"""
FastAPI app entry point for DCSP API.
"""
from __future__ import annotations
from license_check import verify_license; verify_license()

# Load .env before any other import so AWS_* and LLM_BACKEND are available.
from dotenv import load_dotenv
load_dotenv()

import logging as _logging
_logging.basicConfig(level=_logging.INFO, format="%(name)s - %(levelname)s - %(message)s")
logger = _logging.getLogger(__name__)

import os
import redis
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from src.api.webhook import router as webhook_router
from src.api.dashboard import router as dashboard_router, auth_dashboard_router
import src.api.dashboard_views      # noqa: F401 — registers incident/github/security routes
import src.api.dashboard_analytics  # noqa: F401 — registers analytics + intelligence routes
import src.api.dashboard_compliance # noqa: F401 — registers compliance + audit routes
import src.api.dashboard_admin      # noqa: F401 — registers admin tenant + api-key routes
import src.api.dashboard_jobs         # noqa: F401 — registers job detail/approve/reject routes
import src.api.dashboard_jobs_metrics  # noqa: F401 — registers metrics/predictions/health routes
import src.api.dashboard_extra      # noqa: F401 — registers billing/settings/profile routes
from src.api.auth_router import router as auth_router, _REGISTER_ROUTER as _register_router
from src.api.tenant_router import router as tenant_router
from src.api.api_key_router import router as api_key_router
from src.api.incident_router import router as incident_router
from src.api.github_router import router as github_router
from src.api.predict import router as predict_router
from src.api.auth import verify_session_token
from src.database import create_all_tables, engine, SessionLocal
from src.knowledge import KnowledgeGraph
from src.notifications import GLOBAL_NOTIFICATION_ROUTER

# Global knowledge graph instance
graph = KnowledgeGraph()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan event handler."""
    env = os.environ.get("ENVIRONMENT", "development")

    print("=" * 50)
    print("DCSP — Dynamic Code Self-healing Pipeline")
    print("=" * 50)

    # Check Database
    db_ok = False
    try:
        session = SessionLocal()
        session.execute(text("SELECT 1"))
        session.close()
        print("  ✓ Database: connected")
        db_ok = True
    except Exception as e:
        logger.warning("dcsp main: DB connectivity check failed: %s", e)
        print(f"  ✗ Database: disconnected ({e})")

    # Check Bedrock connectivity
    try:
        import boto3
        bedrock = boto3.client(
            "bedrock",
            region_name=os.environ.get("AWS_REGION", "ap-south-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        bedrock.list_foundation_models()
        model_id = os.environ.get("BEDROCK_MODEL_ID", "apac.anthropic.claude-3-5-sonnet-20241022-v2:0")
        print(f"  ✓ Bedrock: connected (model: {model_id})")
    except Exception as e:
        logger.warning("dcsp main: Bedrock connectivity check failed: %s", e)
        print(f"  ⚠ Bedrock: error ({e})")

    # Check Notifications
    n_count = len(GLOBAL_NOTIFICATION_ROUTER.notifiers)
    if n_count > 0:
        print(f"  ✓ Notifications: {n_count} configured")
    else:
        print("  ⚠ Notifications: none configured")

    # Check Memory
    print("  ✓ Repair memory: loaded")

    print("=" * 50)
    print("Ready. Dashboard: http://localhost:8000/dashboard")
    print("=" * 50)

    # Load knowledge graph
    try:
        graph.load()
    except Exception as e:
        logger.warning("dcsp main: could not load knowledge graph: %s", e)
        print(f"WARNING: Could not load knowledge graph: {e}")

    # Load GitHub App installations from DB into memory so they survive restarts.
    # Without this, every server restart clears _INSTALLATIONS and the UI shows
    # "not connected" even though the App is still installed on GitHub.
    try:
        from src.models import GitHubInstallation as _GHInstall
        from src.integrations.github_app import _INSTALLATIONS
        _db = SessionLocal()
        try:
            rows = _db.query(_GHInstall).filter(_GHInstall.is_active == True).all()  # noqa: E712
            for r in rows:
                iid = str(r.installation_id)
                _INSTALLATIONS[iid] = {
                    "installation_id": iid,
                    "account_login": r.account_login,
                    "account_type": r.account_type,
                    "repos": [],
                    "is_active": True,
                }
            if rows:
                print(f"  ✓ GitHub: {len(rows)} installation(s) loaded from DB")
            else:
                print("  ⚠ GitHub: no active installations in DB")
        finally:
            _db.close()
    except Exception as e:
        logger.warning("dcsp main: could not load GitHub installations from DB: %s", e)
        print(f"  ⚠ GitHub: could not load installations from DB: {e}")

    # Run database migration (create all tables)
    try:
        create_all_tables()

        # Seed admin/demo users from env if they don't exist
        try:
            from src.db.user_repo import upsert_admin_users
            upsert_admin_users()
        except Exception as e:
            logger.warning("dcsp main: could not seed admin users: %s", e)
            print(f"WARNING: Could not seed admin users: {e}")

        # Seed demo data in development mode
        env = os.environ.get("ENVIRONMENT", "development")
        if env == "development":
            try:
                from scripts.seed_demo_data import seed_demo_data
                seed_demo_data()
            except Exception as e:
                logger.warning("dcsp main: could not seed demo data: %s", e)
                print(f"WARNING: Could not seed demo data: {e}")

        # Load last 100 jobs into memory
        if db_ok:
            from src.db.job_repo import get_recent_jobs
            from src.api.state import add_job_to_history

            session = SessionLocal()
            try:
                recent = get_recent_jobs(session, limit=100)
                for job in reversed(recent):
                    violations_list = []
                    if job.violations:
                        try:
                            violations_list = json.loads(job.violations)
                        except Exception as e:
                            _logging.getLogger(__name__).warning(
                                "Could not parse violations for job %s: %s", job.id, e
                            )

                    add_job_to_history({
                        "id": job.id,
                        "timestamp": job.timestamp.isoformat(),
                        "repo_name": job.repo_name,
                        "branch": job.branch,
                        "commit_sha": job.commit_sha,
                        "ci_system": job.ci_system,
                        "detected_language": job.detected_language,
                        "success": job.success,
                        "confidence": job.confidence,
                        "escalated": job.escalated,
                        "explanation": job.explanation,
                        "patch_diff": job.patch_diff,
                        "slm_generated": job.slm_generated,
                        "approved": job.approved,
                        "violations": violations_list,
                        "approved_pr_url": job.approved_pr_url,
                        "source": job.source,
                        "fingerprint": job.fingerprint
                    })
            finally:
                session.close()
    except Exception as e:
        logger.warning("dcsp main: database initialization error: %s", e)
        print(f"WARNING: Database initialization error: {e}")

    yield


app = FastAPI(title="DCSP Repair Platform", lifespan=lifespan)

# CORS — allow configurable origins; defaults to localhost dev ports
_cors_origins = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://localhost:8000"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(_register_router)  # /register (public, no prefix)
app.include_router(auth_router)
app.include_router(webhook_router, prefix="/webhook", tags=["webhooks"])
app.include_router(dashboard_router)
app.include_router(auth_dashboard_router)
app.include_router(tenant_router)
app.include_router(api_key_router)
app.include_router(incident_router)
app.include_router(github_router)
app.include_router(predict_router)

# Billing, settings, profile routers
from src.api.billing_router import router as billing_router  # noqa: E402
from src.api.settings_router import router as settings_router  # noqa: E402
from src.api.profile_router import router as profile_router  # noqa: E402
app.include_router(billing_router)
app.include_router(settings_router)
app.include_router(profile_router)

# LLM configuration + proactive scan
from src.api.llm_router import router as llm_router    # noqa: E402
from src.api.scan_router import router as scan_router  # noqa: E402
app.include_router(llm_router)
app.include_router(scan_router)

# React SPA API — job detail, approve/reject, custom patch, stats, patterns
from src.api.react_api import router as react_api_router  # noqa: E402
app.include_router(react_api_router)

# React SPA — static assets served at /app/assets/, index.html catch-all for SPA routing.
# StaticFiles handles /app/assets/* and /app/*.{js,css,svg,ico}.
# A catch-all GET route below returns index.html for all other /app/* paths (client-side routing).
if os.path.exists("frontend/dist"):
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse as _FileResponse
    app.mount("/app/assets", StaticFiles(directory="frontend/dist/assets"), name="spa-assets")

    @app.get("/app/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):  # noqa: ARG001
        index = os.path.join("frontend", "dist", "index.html")
        if os.path.exists(index):
            return _FileResponse(index)
        from fastapi import Response
        return Response("SPA not built", status_code=404)


@app.get("/graph/stats")
async def get_graph_stats():
    """Return Knowledge Graph statistics."""
    return graph.stats()


@app.get("/health")
async def health_check():
    """Enhanced health check testing service connectivity."""
    env = os.environ.get("ENVIRONMENT", "development")

    # Check Database
    try:
        session = SessionLocal()
        session.execute(text("SELECT 1"))
        session.close()
        db_status = "connected"
    except Exception as e:
        logger.warning("dcsp main health: DB check failed: %s", e)
        db_status = "disconnected"

    # Check Redis
    redis_status = "connected"
    try:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        r.ping()
    except Exception as e:
        logger.warning("dcsp main health: Redis check failed: %s", e)
        redis_status = "unavailable"

    # Check LLM providers via the fallback chain
    llm_status = "no provider available"
    llm_provider = "none"
    _llm_backend = os.environ.get("LLM_BACKEND", "fallback")
    try:
        if _llm_backend in ("bedrock", "fallback"):
            import boto3
            bedrock = boto3.client(
                "bedrock",
                region_name=os.environ.get("AWS_REGION", "ap-south-1"),
                aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            )
            bedrock.list_foundation_models()
            llm_status = "connected"
            llm_provider = "bedrock"
    except Exception as e:
        logger.debug("dcsp main health: Bedrock check failed: %s", e)

    if llm_status != "connected" and os.environ.get("OPENROUTER_API_KEY"):
        llm_status = "connected"
        llm_provider = "openrouter"

    if llm_status != "connected":
        try:
            from src.slm.ollama_client import OllamaClient as _Oc
            if _Oc().is_available():
                llm_status = "connected"
                llm_provider = "ollama"
        except Exception as e:
            logger.debug("dcsp main health: Ollama check failed: %s", e)

    # keep backward-compat key "bedrock" in response but add llm_provider
    bedrock_status = llm_status

    return {
        "status": "ok",
        "environment": env,
        "database": db_status,
        "redis": redis_status,
        "bedrock": bedrock_status,
        "llm_provider": llm_provider,
        "notifications": {
            "slack_configured": any(n.__class__.__name__ == "SlackNotifier" for n in GLOBAL_NOTIFICATION_ROUTER.notifiers),
            "email_configured": any(n.__class__.__name__ == "EmailNotifier" for n in GLOBAL_NOTIFICATION_ROUTER.notifiers),
            "notifiers_count": len(GLOBAL_NOTIFICATION_ROUTER.notifiers)
        }
    }


# Register WebSocket, PWA, notifications, secrets, queue, and job routes.
# These are extracted to websocket_routes.py to keep this file under 600 lines.
from src.api.websocket_routes import register_routes as _register_ws_routes  # noqa: E402
_register_ws_routes(app)
