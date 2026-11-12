"""
AetherOS — Agents Router (T5-07)
GET  /agents
POST /agents/{agent_name}/run
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agents"])


def _current_user():
    return Depends(get_current_user)


@router.get("/agents")
async def list_agents(user: Dict[str, Any] = _current_user()):
    """List all registered agents with their name, kind, and availability."""
    from aether_os.agents.implementations import get_agent_registry
    from aether_os.agents.base import AgentKind
    registry = get_agent_registry()
    return {
        "agents": [
            {
                "name": a.name.value,
                "kind": a.kind.value,
            }
            for a in registry._by_name.values()
        ],
        "total": len(registry._by_name),
    }


@router.post("/agents/{agent_name}/run")
async def run_agent(
    agent_name: str,
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Run a specific agent with the provided metadata context."""
    from aether_os.agents.implementations import get_agent_registry
    from aether_os.agents.base import AgentContext, AgentName
    registry = get_agent_registry()
    # Lookup by value (e.g. "policy_agent")
    agent = next(
        (a for a in registry._by_name.values() if a.name.value == agent_name),
        None,
    )
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
    ctx = AgentContext(
        project_path=req.get("project_path", "."),
        file_path=req.get("file_path"),
        workflow_id=req.get("workflow_id"),
        user_id=user.get("sub"),
        # Identity comes from the token, never from the request body.
        metadata={**req.get("metadata", {}), "org_id": user["org_id"], "role": user.get("role")},
    )
    result = await agent.run(ctx)
    return {
        "agent": result.agent_name.value,
        "status": result.status,
        "message": result.message,
        "payload": result.payload,
        "duration_ms": round(result.duration * 1000, 1),
    }
