"""
Extended Z3 invariant checkers for AetherOS formal verification.

Provides three additional invariants beyond the base four in z3_encoder.py:

INV-005  Multi-tenant isolation — every DB query in a multi-tenant route
          must filter by org_id, tenant_id, or equivalent column before
          returning data.

INV-006  Resource ownership — DELETE and PUT/PATCH routes that operate
          on a user-owned resource must verify ownership before mutation.
          Detected by: route has auth dependency AND uses id-based lookup
          AND has an ownership check (user_id == current_user.id or similar).

INV-007  Transaction boundary — routes that perform multiple DB writes
          (INSERT + UPDATE, or UPDATE + DELETE) must do so within a single
          session context (single `async with db` or using `await db.commit()`
          only once at the end, not interleaved).
"""
from __future__ import annotations

import ast
import logging
import re
from typing import TYPE_CHECKING

from aether_os.phases.p06b_formal_verification.route_deps import has_tenant_filter  # noqa: E402

if TYPE_CHECKING:
    from aether_os.phases.p06b_formal_verification.z3_encoder import InvariantResult, RouteInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# INV-005: Multi-tenant isolation
# ---------------------------------------------------------------------------

_TENANT_COLUMNS = frozenset({"org_id", "tenant_id", "organization_id", "workspace_id"})


def _is_tenant_target(node: ast.AST) -> bool:
    """extra["org_id"], obj.org_id or a bare org_id as an assignment target."""
    if isinstance(node, ast.Subscript):
        key = node.slice
        return isinstance(key, ast.Constant) and key.value in _TENANT_COLUMNS
    if isinstance(node, ast.Attribute):
        return node.attr in _TENANT_COLUMNS
    return isinstance(node, ast.Name) and node.id in _TENANT_COLUMNS


def _reads_tenant_column(source_text: str) -> bool:
    """True when the route reads a tenant column. Writing one does not count: an assignment to it (with its value,
    e.g. extra["org_id"] = admin.get("org_id")) or Model(org_id=...) stamps the caller's tenant on an INSERT,
    which is not a tenant query (run 22: create_user). filter_by(org_id=...) is a read (a filter)."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return any(col in source_text for col in _TENANT_COLUMNS)
    skip: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(_is_tenant_target(t) for t in targets):
                skip.update(id(n) for n in ast.walk(node))
        elif isinstance(node, ast.Call) and not (isinstance(node.func, ast.Attribute) and node.func.attr == "filter_by"):
            for kw in node.keywords:
                if kw.arg in _TENANT_COLUMNS:
                    skip.update(id(n) for n in ast.walk(kw))
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if (isinstance(node, ast.Name) and node.id in _TENANT_COLUMNS) or (
                isinstance(node, ast.Attribute) and node.attr in _TENANT_COLUMNS) or (
                isinstance(node, ast.Constant) and node.value in _TENANT_COLUMNS) or (
                isinstance(node, ast.keyword) and node.arg in _TENANT_COLUMNS):
            return True
    return False


def _source_has_tenant_filter(source_text: str) -> bool:
    """AST check on the route's source (replaces a regex that stopped at the first closing parenthesis)."""
    try:
        return has_tenant_filter(ast.parse(source_text))
    except SyntaxError as e:
        logger.warning("[z3_invariants] route source did not parse, tenant filter not detectable: %s", e)
        return False


# Patterns indicating a DB select/query is present in the source
_SELECT_RE = re.compile(
    r"(?:select|scalars|execute|fetchall|fetchone|scalar_one|scalar_one_or_none)\s*\(",
    re.IGNORECASE,
)


def _check_inv005_tenant_isolation(route: "RouteInfo") -> "InvariantResult":
    """
    Verify that routes handling multi-tenant data filter by org_id/tenant_id.

    Detection strategy:
    - Route is multi-tenant if its source text reads a tenant column; writing one (an INSERT that
      stamps org_id on the new row, run 22's create_user) does not count
    - A multi-tenant route that performs a SELECT without an org_id/tenant_id
      filter clause is VIOLATED
    - Routes without any DB query or tenant columns are N/A
    - We scan route.source_text (populated by the extended extract_routes) for:
        select(Model).where(Model.org_id == ...)  → filtered
        select(Model) without .where(org_id ...)  → missing filter = VIOLATED
    """
    source_text: str = getattr(route, "source_text", "")

    tenant_filtered = _source_has_tenant_filter(source_text) or bool(getattr(route, "has_org_id_filter", False))
    has_tenant_col = tenant_filtered or _reads_tenant_column(source_text)
    has_db_query = bool(_SELECT_RE.search(source_text))

    if not has_tenant_col or not has_db_query:
        # Not a multi-tenant route or no DB queries — invariant not applicable
        return _build_result(
            "INV-005",
            "Multi-tenant isolation: DB queries filter by org_id/tenant_id",
            route.name,
            status="N/A",
            proof_method="Route does not perform tenant-scoped DB queries — invariant not applicable",
            confidence=1.0,
        )

    if tenant_filtered:
        return _build_result(
            "INV-005",
            "Multi-tenant isolation: DB queries filter by org_id/tenant_id",
            route.name,
            status="VERIFIED",
            proof_method="static check: a .where()/.filter()/.filter_by() on a tenant column is present",
            confidence=0.9,
        )
    return _build_result(
        "INV-005",
        "Multi-tenant isolation: DB queries filter by org_id/tenant_id",
        route.name,
        status="VIOLATED",
        proof_method="static check: tenant column referenced but no where/filter on it found",
        violation_detail=(
            f"Route '{route.name}' ({route.method} {route.path}) references tenant "
            "columns (org_id/tenant_id) but no .where() filter on those columns was "
            "detected. All multi-tenant queries must be scoped to the requesting tenant."
        ),
        confidence=0.85,
    )


# ---------------------------------------------------------------------------
# INV-006: Resource ownership
# ---------------------------------------------------------------------------

# Ownership check patterns — comparison of user_id/created_by to current_user
_OWNERSHIP_RE = re.compile(
    r"(?:"
    r"(?:user_id|created_by|owner_id)\s*==\s*current_user"
    r"|current_user\.(?:id|user_id)\s*==\s*(?:user_id|created_by|owner_id|item\."
    r"(?:user_id|created_by|owner_id))"
    r"|\.user_id\s*!=\s*current_user"
    r"|raise\s+HTTPException.*403"
    r")",
    re.IGNORECASE,
)

# ID-based lookup pattern — get by id / filter by id
_ID_LOOKUP_RE = re.compile(
    r"(?:\.get\s*\(\s*(?:resource_id|item_id|obj_id|id)\b|\.where\s*\([^)]*\bid\s*==)",
    re.IGNORECASE,
)


def _check_inv006_resource_ownership(route: "RouteInfo") -> "InvariantResult":
    """
    Verify DELETE/PUT/PATCH routes check resource ownership.

    Heuristic: if a route is authenticated AND modifies a resource (PUT/PATCH/DELETE)
    AND fetches by ID, it should also compare user_id or created_by to current_user.

    Routes that are not mutation methods are N/A.
    Routes without auth are not checked here (INV-001 handles that).
    """
    if route.method not in ("DELETE", "PUT", "PATCH"):
        return _build_result(
            "INV-006",
            "Resource ownership verified before mutation",
            route.name,
            status="N/A",
            proof_method=f"Route method is {route.method} — ownership invariant only applies to DELETE/PUT/PATCH",
            confidence=1.0,
        )

    if not route.has_auth_depends:
        # INV-001 will flag this; INV-006 cannot assess ownership without auth
        return _build_result(
            "INV-006",
            "Resource ownership verified before mutation",
            route.name,
            status="N/A",
            proof_method="Route has no auth dependency — INV-001 handles unauthenticated access",
            confidence=1.0,
        )

    source_text: str = getattr(route, "source_text", "")
    has_id_lookup = bool(_ID_LOOKUP_RE.search(source_text))

    if not has_id_lookup:
        # No ID-based lookup detected — possibly bulk operation, skip
        return _build_result(
            "INV-006",
            "Resource ownership verified before mutation",
            route.name,
            status="N/A",
            proof_method="No ID-based resource lookup detected — ownership check not applicable",
            confidence=1.0,
        )

    has_ownership_check = bool(_OWNERSHIP_RE.search(source_text))

    # Also check the dedicated field set by extract_routes if available
    if getattr(route, "has_ownership_check", False):
        has_ownership_check = True

    if has_ownership_check:
        return _build_result(
            "INV-006",
            "Resource ownership verified before mutation",
            route.name,
            status="VERIFIED",
            proof_method="static check: ownership comparison present before the mutation",
            confidence=0.88,
        )
    return _build_result(
        "INV-006",
        "Resource ownership verified before mutation",
        route.name,
        status="VIOLATED",
        proof_method="static check: mutation route with ID lookup but no ownership comparison found",
        violation_detail=(
            f"Route '{route.name}' ({route.method} {route.path}) mutates a resource "
            "by ID but no ownership check (user_id == current_user.id) was detected. "
            "Add an ownership guard before performing the mutation."
        ),
        confidence=0.82,
    )


# ---------------------------------------------------------------------------
# INV-007: Transaction boundary safety
# ---------------------------------------------------------------------------

# Matches `await db.commit()` or `await session.commit()` or `await db.flush()`
_COMMIT_RE = re.compile(
    r"await\s+(?:db|session|conn|async_session)\s*\.\s*(?:commit|flush)\s*\(\s*\)",
    re.IGNORECASE,
)


def _check_inv007_transaction_boundary(route: "RouteInfo") -> "InvariantResult":
    """
    Verify routes with multiple writes use a single transaction boundary.

    Violated if: the route has more than one await db.commit() or await db.flush() call.
    SQLAlchemy async sessions should commit once at the end, not after each operation,
    to ensure atomicity across multiple writes.
    """
    source_text: str = getattr(route, "source_text", "")
    commit_count: int = getattr(route, "multi_db_commits", None)

    if commit_count is None:
        # Fallback: count from source text directly
        commit_count = len(_COMMIT_RE.findall(source_text))

    if commit_count == 0:
        # No commits at all — route might not write to DB
        return _build_result(
            "INV-007",
            "Single transaction boundary per route (no mid-route commits)",
            route.name,
            status="N/A",
            proof_method="No db.commit()/db.flush() calls detected — invariant not applicable",
            confidence=1.0,
        )

    if commit_count <= 1:
        return _build_result(
            "INV-007",
            "Single transaction boundary per route (no mid-route commits)",
            route.name,
            status="VERIFIED",
            proof_method=f"static check: exactly {commit_count} commit call(s)",
            confidence=0.95,
        )
    return _build_result(
        "INV-007",
        "Single transaction boundary per route (no mid-route commits)",
        route.name,
        status="VIOLATED",
        proof_method=f"static check: {commit_count} commit/flush calls found; route commits mid-operation",
        violation_detail=(
            f"Route '{route.name}' ({route.method} {route.path}) calls db.commit() or "
            f"db.flush() {commit_count} times. Multiple commits break atomicity — "
            "consolidate all writes into a single transaction and commit once at the end."
        ),
        confidence=0.93,
    )


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _build_result(
    invariant_id: str,
    invariant_name: str,
    route_name: str,
    *,
    status: str,
    proof_method: str,
    violation_detail: "str | None" = None,
    solver_time_ms: int = 0,
    confidence: float = 1.0,
) -> "InvariantResult":
    """Construct an InvariantResult without importing the full encoder at module level."""
    from aether_os.phases.p06b_formal_verification.z3_encoder import InvariantResult  # noqa: PLC0415
    return InvariantResult(
        invariant_id=invariant_id,
        invariant_name=invariant_name,
        route_name=route_name,
        status=status,
        proof_method=proof_method,
        violation_detail=violation_detail,
        solver_time_ms=solver_time_ms,
        confidence=confidence,
    )
