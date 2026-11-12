"""Control-layer proxy: /control/* -> Velaris /control/*. Rules in gateway/velaris_proxy.py."""
from __future__ import annotations

from aether_os.gateway.velaris_proxy import Route as R, build_router

ROUTES = (
    R("GET", "/tasks", "control.tasks"),
    R("POST", "/runs", "control.start", log=("task_id",)),
    R("GET", "/pending", "control.pending"),
    R("GET", "/runs/{run_id}", "control.state"),
    R("GET", "/runs/{run_id}/report", "control.report"),
    R("POST", "/runs/{run_id}/decide", "control.decide", log=("call_hash", "approve")),
    R("POST", "/runs/{run_id}/undo", "control.undo"),
    R("POST", "/runs/{run_id}/kill", "control.kill"),
)
router = build_router("/control", "/control", ROUTES, "velaris-control")
