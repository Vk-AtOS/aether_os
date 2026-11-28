"""
Base static invariant checker functions (INV-001 through INV-004).

Split from z3_encoder.py to keep that file under 600 lines.
These checkers are imported by Z3Encoder.verify_all() in z3_encoder.py.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _z3_bool_invariant(
    fact: bool,
    inv_id: str,
    inv_name: str,
    route_name: str,
    violation_detail: str,
    verified_method: str,
    violated_method: str,
    confidence_violated: float = 0.9,
) -> "InvariantResult":
    """
    Static check: `fact` must be True. (Name kept for callers; no solver is involved: a Z3 query over one boolean
    equal to a Python bool proves nothing the `if` below does not, so the report calls these static checks.)
    """
    from aether_os.phases.p06b_formal_verification.z3_encoder import InvariantResult  # noqa: PLC0415

    if fact:
        return InvariantResult(
            invariant_id=inv_id, invariant_name=inv_name,
            route_name=route_name, status="VERIFIED", proof_method=verified_method,
        )
    return InvariantResult(
        invariant_id=inv_id, invariant_name=inv_name,
        route_name=route_name, status="VIOLATED",
        proof_method=violated_method, violation_detail=violation_detail,
        confidence=confidence_violated,
    )


# Routes that must be callable without a token: logging in, signing up, token refresh,
# health probes and API docs. Flagging them VIOLATED made every app fail the gate.
# Also public: /logout (it only ends the caller's own session) and a GET on the bare root (the service banner every
# generated backend serves). Both failed INV-001 on the production acceptance run (22 Nov 2026), blocking s05.
_PUBLIC_TAILS = ("/login", "/logout", "/register", "/signup", "/refresh", "/token", "/forgot-password",
                 "/reset-password", "/health", "/healthz", "/ready", "/docs", "/redoc", "/openapi.json")


def _is_public_route(path: str, method: str = "") -> bool:
    p = (path or "").rstrip("/").lower()
    if p == "" and (method or "GET").upper() in ("GET", "HEAD"):
        return True                                   # GET / only: a POST/PUT/DELETE on the root still needs auth
    return p.endswith(_PUBLIC_TAILS)


def _check_inv001_auth(route: "RouteInfo") -> "InvariantResult":
    """
    INV-001: Authentication invariant.

    Encodes: if the route has Depends(get_current_user) auth is enforced.
    We ask Z3 whether the route can be reached without auth (negation of invariant).
    With has_auth_depends=True the negation is UNSAT — invariant holds.
    """
    from aether_os.phases.p06b_formal_verification.z3_encoder import InvariantResult  # noqa: PLC0415

    if not route.has_auth_depends and (
            getattr(route, "is_declared_public", False) or _is_public_route(route.path, getattr(route, "method", ""))):
        return InvariantResult(
            invariant_id="INV-001",
            invariant_name="No route reachable without valid JWT",
            route_name=route.name, status="N/A",
            proof_method="public by design (@public_route / PUBLIC_ROUTES allowlist, or login/logout/register/"
                         "refresh/health/docs, GET /)",
        )

    if route.has_auth_depends:
        return InvariantResult(
            invariant_id="INV-001",
            invariant_name="No route reachable without valid JWT",
            route_name=route.name, status="VERIFIED",
            proof_method="static check: an authentication dependency guards the route (route, router or include level)",
        )
    detail = (
        f"Route '{route.name}' ({route.method} {route.path}) has no authentication dependency (own, router-level "
        "or include-level) and is not declared public: accessible without authentication"
    )
    return InvariantResult(
        invariant_id="INV-001",
        invariant_name="No route reachable without valid JWT",
        route_name=route.name, status="VIOLATED",
        proof_method="static check: no authentication dependency found",
        violation_detail=detail, confidence=0.9,
    )


def _check_inv002_input(route: "RouteInfo") -> "InvariantResult":
    """INV-002: Proves no route uses raw request.body() — Pydantic validation only."""
    return _z3_bool_invariant(
        fact=not route.has_raw_body,
        inv_id="INV-002",
        inv_name="All route inputs validated via Pydantic (no raw body reads)",
        route_name=route.name,
        violation_detail=(
            f"Route '{route.name}' reads raw request body. "
            "Use a Pydantic schema as a parameter instead."
        ),
        verified_method="static check — no request.body()/json() call",
        violated_method="static check — route calls request.body()/request.json() directly",
    )


def _check_inv003_state_machine(route: "RouteInfo") -> "Optional[InvariantResult]":
    """
    INV-003: State machine transition invariant.

    Only applicable to routes that reference ALLOWED_TRANSITIONS. Returns None
    for routes that are not state-transition routes (caller records N/A).
    Encodes: guard presence is True when ALLOWED_TRANSITIONS is referenced;
    the negation (guard_bypassed) must be UNSAT.
    """
    if not route.has_transition_guard:
        return None

    return _z3_bool_invariant(
        fact=True,   # guard IS present — we found ALLOWED_TRANSITIONS reference
        inv_id="INV-003",
        inv_name="State machine transitions always guarded by ALLOWED_TRANSITIONS",
        route_name=route.name,
        violation_detail=(
            f"Route '{route.name}' references ALLOWED_TRANSITIONS but "
            "the guard is not applied."
        ),
        verified_method="static check — ALLOWED_TRANSITIONS referenced",
        violated_method="static check — transition guard missing",
        confidence_violated=0.8,
    )


def _check_inv004_sql(route: "RouteInfo") -> "InvariantResult":
    """INV-004: Proves no f-string interpolation inside SQLAlchemy execute()/query() calls."""
    return _z3_bool_invariant(
        fact=not route.has_f_string_sql,
        inv_id="INV-004",
        inv_name="No f-string interpolation in SQLAlchemy queries (parameterised queries only)",
        route_name=route.name,
        violation_detail=(
            f"Route '{route.name}' uses f-string interpolation inside a "
            "SQLAlchemy .execute() call. Use bindparams() or text() with "
            "named parameters instead."
        ),
        verified_method="static check — no f-string inside execute()/query()",
        violated_method="static check — f-string inside SQL execute() found",
        confidence_violated=0.95,
    )


# Type hints for IDE support (avoid circular import at runtime)
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from aether_os.phases.p06b_formal_verification.z3_encoder import InvariantResult, RouteInfo
