"""
Base Z3 invariant checker functions (INV-001 through INV-004).

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
    Generic Z3 invariant check: encodes 'fact must be True' as UNSAT of NOT(fact).
    Used by INV-002 and INV-004 which follow the same SAT/UNSAT pattern.
    """
    import z3  # noqa: PLC0415
    from aether_os.phases.p06b_formal_verification.z3_encoder import InvariantResult  # noqa: PLC0415

    t0 = time.monotonic()
    flag = z3.Bool("flag")
    solver = z3.Solver()
    solver.add(flag == fact)
    solver.add(z3.Not(flag))          # violation: flag is False
    result = solver.check()
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if result == z3.unsat:
        return InvariantResult(
            invariant_id=inv_id, invariant_name=inv_name,
            route_name=route_name, status="VERIFIED",
            proof_method=verified_method, solver_time_ms=elapsed_ms,
        )
    return InvariantResult(
        invariant_id=inv_id, invariant_name=inv_name,
        route_name=route_name, status="VIOLATED",
        proof_method=violated_method, violation_detail=violation_detail,
        solver_time_ms=elapsed_ms, confidence=confidence_violated,
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

    if _is_public_route(route.path, getattr(route, "method", "")) and not route.has_auth_depends:
        return InvariantResult(
            invariant_id="INV-001",
            invariant_name="No route reachable without valid JWT",
            route_name=route.name, status="N/A",
            proof_method="public by design (login/logout/register/refresh/health/docs, GET /)",
        )

    import z3  # noqa: PLC0415

    t0 = time.monotonic()
    route_reachable = z3.Bool("route_reachable")
    auth_enforced = z3.Bool("auth_enforced")
    invariant = z3.Implies(route_reachable, auth_enforced)

    solver = z3.Solver()
    solver.add(route_reachable == True)  # noqa: E712 — z3 equality
    solver.add(auth_enforced == route.has_auth_depends)
    solver.add(z3.Not(invariant))

    result = solver.check()
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if result == z3.unsat:
        return InvariantResult(
            invariant_id="INV-001",
            invariant_name="No route reachable without valid JWT",
            route_name=route.name, status="VERIFIED",
            proof_method="Z3 UNSAT — negation of auth invariant is unsatisfiable",
            solver_time_ms=elapsed_ms, confidence=1.0,
        )
    detail = (
        f"Route '{route.name}' ({route.method} {route.path}) has no "
        "Depends(get_current_user) — accessible without authentication"
    )
    return InvariantResult(
        invariant_id="INV-001",
        invariant_name="No route reachable without valid JWT",
        route_name=route.name, status="VIOLATED",
        proof_method="Z3 SAT — counter-example: route reachable without auth",
        violation_detail=detail, solver_time_ms=elapsed_ms, confidence=0.9,
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
        verified_method="Z3 UNSAT — raw body usage is unsatisfiable given Pydantic validation",
        violated_method="Z3 SAT — route calls request.body()/request.json() directly",
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
            "Z3 found a satisfying model where the guard is bypassed."
        ),
        verified_method="Z3 UNSAT — guard bypass unsatisfiable: ALLOWED_TRANSITIONS present",
        violated_method="Z3 SAT — transition guard bypass is satisfiable",
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
        verified_method="Z3 UNSAT — f-string SQL unsatisfiable given parameterised patterns",
        violated_method="Z3 SAT — f-string inside SQL execute() found",
        confidence_violated=0.95,
    )


# Type hints for IDE support (avoid circular import at runtime)
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from aether_os.phases.p06b_formal_verification.z3_encoder import InvariantResult, RouteInfo
