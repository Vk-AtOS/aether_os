"""
AetherOS — Factory Ops Router
Extracted from gateway/api.py (inline routes → APIRouter).

Routes (core run operations):
  GET  /templates
  GET  /pipeline/status/{run_id}
  POST /pipeline/approve/{ticket_id}

See also:
  factory_start_router.py    — POST /factory/start, POST /factory/estimate
  factory_intake_router.py   — upload/fetch/import routes
  factory_analytics_router.py — search, quality-trend, deployments
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.policy_guard import enforce

logger = logging.getLogger(__name__)
router = APIRouter(tags=["factory"])


def _current_user():
    return Depends(get_current_user)


# ── Pydantic models ───────────────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    ticket_id: str
    decision: str  # "approve" | "deny"
    reason: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/pipeline/status/{run_id}")
async def get_pipeline_status(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get status of a pipeline run."""
    from aether_os.core.audit.ledger import get_ledger
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return detail


@router.post("/pipeline/approve/{ticket_id}")
async def approve_action(
    ticket_id: str,
    req: ApproveRequest,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Approve or deny a human-gated pipeline action via DecisionEngine (member or above)."""
    from aether_os.core.decisions.decision_engine import AlreadyDecided, get_decision_engine
    await enforce("decision.decide", user)
    engine = get_decision_engine()
    approved = req.decision in ("approve", "approved", "yes", True)
    try:
        decision = await engine.resolve(
            decision_id=ticket_id,
            org_id=user.get("org_id", ""),
            approved=approved,
            choice=req.reason,
        )
    except (LookupError, PermissionError):
        # one answer for "no such id" and "another organisation's id": ids cannot be probed (KAN-69 F12)
        raise HTTPException(status_code=404, detail="Decision not found") from None
    except AlreadyDecided as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return {
        "ticket_id": ticket_id,
        "decision":  "approved" if approved else "denied",
        "decided_by": user.get("sub"),
        "reason":    req.reason,
        "timestamp": time.time(),
        "status":    decision.status,
    }


@router.get("/templates")
async def list_templates(user: Dict[str, Any] = _current_user()):
    """Return available project templates."""
    return {"templates": [
        {"id": "saas", "name": "SaaS App", "description": "Multi-tenant SaaS with auth, billing, and dashboard", "domain": "saas", "icon": "🏢"},
        {"id": "ecommerce", "name": "E-Commerce", "description": "Product catalog, cart, orders, and payments", "domain": "ecommerce", "icon": "🛒"},
        {"id": "dashboard", "name": "Analytics Dashboard", "description": "Data visualisation, charts, and KPI tracking", "domain": "analytics", "icon": "📊"},
        {"id": "api", "name": "REST API", "description": "Clean REST API with auth, rate limiting, and docs", "domain": "api", "icon": "⚡"},
        {"id": "cms", "name": "CMS / Blog", "description": "Content management with rich text editor and media", "domain": "cms", "icon": "✍️"},
        {"id": "social", "name": "Social Platform", "description": "User profiles, posts, follows, and notifications", "domain": "social", "icon": "👥"},
        {"id": "marketplace", "name": "Marketplace", "description": "Two-sided marketplace with listings and transactions", "domain": "marketplace", "icon": "🏪"},
        {"id": "healthcare", "name": "Healthcare", "description": "Patient records, appointments, and HIPAA compliance", "domain": "healthcare", "icon": "🏥"},
        {"id": "fintech", "name": "FinTech", "description": "Transactions, wallets, and financial reporting", "domain": "fintech", "icon": "💳"},
        {"id": "iot", "name": "IoT Dashboard", "description": "Device management, telemetry streams, and alerts", "domain": "iot", "icon": "📡"},
        {"id": "lms", "name": "Learning Management", "description": "Courses, lessons, quizzes, and student progress", "domain": "education", "icon": "🎓"},
        {"id": "custom", "name": "Custom", "description": "Describe your own requirements from scratch", "domain": "general", "icon": "🛠️"},
    ]}
