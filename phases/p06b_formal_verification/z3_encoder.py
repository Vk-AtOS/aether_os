"""
Z3 SMT Encoder for FastAPI route invariants.

Encodes four security invariants as Z3 constraints and checks whether they
can be violated (SAT = violation found; UNSAT = invariant holds).

Invariants checked:
  INV-001  Auth gate          — every route with Depends(get_current_user) cannot
                                be reached without a valid JWT
  INV-002  Input safety       — every route uses Pydantic models or typed params,
                                no raw request.body() calls
  INV-003  State machine      — routes with ALLOWED_TRANSITIONS have no code path
                                that bypasses the transition guard
  INV-004  SQL safety         — no string interpolation (f-string) in SQLAlchemy
                                queries (parameterised queries only)
  INV-005  Tenant isolation   — multi-tenant routes filter by org_id/tenant_id
                                (checkers in z3_invariants.py)
  INV-006  Resource ownership — DELETE/PUT/PATCH routes verify user ownership
                                before mutation (checkers in z3_invariants.py)
  INV-007  Tx boundary        — routes with multiple DB writes commit only once
                                at the end (checkers in z3_invariants.py)

Graceful degradation:
  - try/except blocks, async generators, dynamic attribute access: marked
    UNVERIFIABLE and skipped — the phase never crashes the pipeline.
  - If z3 itself is unavailable the module raises ImportError at load time
    so the task_agent can catch it and return PARTIAL.
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

from aether_os.phases.p06b_formal_verification.route_deps import (
    _kw,
    analyse_module,
    expr_is_auth,
    function_has_auth_param,
    has_public_marker,
    has_tenant_filter,
    in_public_allowlist,
    route_decorator,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RouteInfo:
    """Extracted facts about a single FastAPI route function."""
    name: str
    path: str
    method: str
    has_auth_depends: bool = False       # effective auth: own, decorator, router or include-level dependency
    is_declared_public: bool = False     # @public_route, PUBLIC_ROUTES or the allowlist: intentionally unauthenticated
    has_pydantic_body: bool = False      # request body is a Pydantic model
    has_raw_body: bool = False           # request.body() / request.json() call
    has_transition_guard: bool = False   # references ALLOWED_TRANSITIONS
    has_f_string_sql: bool = False       # f-string used inside .execute() / .query()
    is_unverifiable: bool = False        # complex pattern Z3 cannot model
    unverifiable_reason: str = ""
    source_lines: List[int] = field(default_factory=list)
    # INV-005/006/007 fields (populated by extended extract_routes scan)
    has_org_id_filter: bool = False      # select has .where(org_id == ...)
    has_ownership_check: bool = False    # DELETE/PATCH checks user ownership
    multi_db_commits: int = 0            # number of await db.commit() calls
    source_text: str = ""               # raw source text for regex-based checks


@dataclass
class InvariantResult:
    """Result of checking one invariant for one route."""
    invariant_id: str
    invariant_name: str
    route_name: str
    status: str                  # "VERIFIED" | "VIOLATED" | "UNVERIFIABLE" | "N/A"
    proof_method: str
    violation_detail: Optional[str] = None
    solver_time_ms: int = 0
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# AST-based route scanner
# ---------------------------------------------------------------------------

_SQL_CALL_NAMES = frozenset({
    "execute",
    "query",
    "raw",
    "text",
    "exec_driver_sql",
})


def _has_try_except(node: ast.AST) -> bool:
    """Return True if the node tree contains a try/except — marks unverifiable."""
    for child in ast.walk(node):
        if isinstance(child, ast.Try):
            return True
    return False


def _has_async_generator(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.YieldFrom):
            return True
        if isinstance(child, ast.Yield) and isinstance(node, ast.AsyncFunctionDef):
            return True
    return False


def _has_dynamic_attr(node: ast.AST) -> bool:
    """Detect getattr() calls that suggest dynamic dispatch."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name) and func.id == "getattr":
                return True
    return False


def _check_f_string_sql(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    Return True if any .execute()/.query() call has an f-string argument.
    This is the SQL injection pattern we prove absence of.
    """
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_sql_call = False
        if isinstance(func, ast.Attribute) and func.attr in _SQL_CALL_NAMES:
            is_sql_call = True
        if not is_sql_call:
            continue
        for arg in node.args:
            if isinstance(arg, ast.JoinedStr):  # f-string
                return True
    return False


def _check_raw_body(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the function calls request.body() or request.json()."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Await):
            inner = node.value
            if isinstance(inner, ast.Call):
                func = inner.func
                if isinstance(func, ast.Attribute) and func.attr in ("body", "json", "form"):
                    if isinstance(func.value, ast.Name) and func.value.id == "request":
                        return True
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in ("body", "json", "form"):
                if isinstance(func.value, ast.Name) and func.value.id == "request":
                    return True
    return False


def _check_transition_guard(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if ALLOWED_TRANSITIONS is referenced inside the function."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Name) and node.id == "ALLOWED_TRANSITIONS":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "ALLOWED_TRANSITIONS":
            return True
    return False


def _is_pydantic_param(annotation: Optional[ast.expr]) -> bool:
    """
    Heuristic: a parameter is a Pydantic model if its annotation is a Name or
    Attribute (i.e. a type reference, not a primitive). Excludes common
    primitive types so we don't count int / str / bool.
    """
    _PRIMITIVES = {"int", "str", "float", "bool", "bytes", "None", "Optional",
                   "List", "Dict", "Any", "UUID", "datetime", "date"}
    if annotation is None:
        return False
    if isinstance(annotation, ast.Name):
        return annotation.id not in _PRIMITIVES
    if isinstance(annotation, ast.Attribute):
        return True
    # Optional[SomeModel] etc.
    if isinstance(annotation, ast.Subscript):
        return _is_pydantic_param(annotation.value)
    return False


def _const_arg(dec: ast.Call) -> str:
    """The route path: first positional argument or path=."""
    node = dec.args[0] if dec.args else _kw(dec, "path")
    return str(node.value) if isinstance(node, ast.Constant) else ""


def extract_routes(
    module_ast: ast.Module,
    module_key: str = "",
    included_auth: Iterable[Tuple[str, str]] = (),
    public_routes: Iterable[str] = (),
) -> List[RouteInfo]:
    """
    Walk the module AST and return RouteInfo for every FastAPI route function.

    has_auth_depends is the route's EFFECTIVE authentication: its own Depends/Annotated parameters, the route
    decorator's dependencies=[...], the router's APIRouter(dependencies=[...]) and an include_router(...,
    dependencies=[...]) elsewhere in the project (included_auth, from route_deps.collect_included_auth).
    Routes marked @public_route, listed in a module PUBLIC_ROUTES or in the public_routes allowlist are
    is_declared_public.
    """
    routes: List[RouteInfo] = []
    deps = analyse_module(module_ast)
    included = set(included_auth)
    allowlist = list(public_routes) + deps.public_routes

    for node in ast.walk(module_ast):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        dec_info = route_decorator(node)
        if dec_info is None:
            continue  # not a route function
        dec, receiver, route_method = dec_info
        raw_path = _const_arg(dec)
        facts = deps.routers.get(receiver)
        route_path = (facts.prefix if facts else "") + raw_path

        info = RouteInfo(
            name=node.name,
            path=route_path,
            method=route_method,
        )

        info.has_auth_depends = (
            function_has_auth_param(node, deps)
            or expr_is_auth(_kw(dec, "dependencies"), deps.local_auth, deps.alias_auth)
            or bool(facts and facts.auth)
            or (module_key, receiver) in included
        )
        info.is_declared_public = has_public_marker(node) or in_public_allowlist(route_method, route_path, allowlist)
        for arg in node.args.args + node.args.kwonlyargs:
            if _is_pydantic_param(arg.annotation) and not expr_is_auth(arg.annotation, deps.local_auth, deps.alias_auth):
                info.has_pydantic_body = True

        # Graceful degradation — complex patterns are unverifiable (auth above is still resolved and checked)
        unverifiable = ""
        if _has_try_except(node):
            unverifiable = "try/except block — exception paths are not modelled"
        elif _has_async_generator(node):
            unverifiable = "async generator — streaming paths are not modelled"
        elif _has_dynamic_attr(node):
            unverifiable = "dynamic attribute access (getattr) — path is not statically determinable"
        if unverifiable:
            info.is_unverifiable = True
            info.unverifiable_reason = unverifiable
            routes.append(info)
            continue

        info.has_raw_body = _check_raw_body(node)
        info.has_transition_guard = _check_transition_guard(node)
        info.has_f_string_sql = _check_f_string_sql(node)

        try:
            info.source_lines = [node.lineno, node.end_lineno or node.lineno]
        except AttributeError:
            info.source_lines = [node.lineno]

        # Extended fields for INV-005/006/007
        info.source_text = _extract_source_text(node)
        info.has_org_id_filter = has_tenant_filter(node)
        info.has_ownership_check = _check_ownership_pattern(node)
        info.multi_db_commits = _count_db_commits(node)

        routes.append(info)

    return routes


# ---------------------------------------------------------------------------
# Extended AST helpers for INV-005/006/007
# ---------------------------------------------------------------------------

_OWNERSHIP_SRC_RE = re.compile(
    r"(?:user_id|created_by|owner_id)\s*==\s*current_user"
    r"|current_user\.(?:id|user_id)\s*==\s*"
    r"|raise\s+HTTPException.*403",
    re.IGNORECASE,
)
_COMMIT_SRC_RE = re.compile(
    r"await\s+(?:db|session|conn|async_session)\s*\.\s*(?:commit|flush)\s*\(\s*\)",
    re.IGNORECASE,
)


def _extract_source_text(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """
    Convert AST node back to a best-effort source representation using ast.unparse.
    Falls back to empty string if unavailable (Python < 3.9).
    """
    try:
        return ast.unparse(node)
    except Exception as e:
        logger.warning("[z3_encoder] ast.unparse failed for %s: %s", getattr(node, "name", "<unknown>"), e)
        return ""


def _check_ownership_pattern(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if a user ownership comparison pattern is found in the function."""
    try:
        src = ast.unparse(node)
        return bool(_OWNERSHIP_SRC_RE.search(src))
    except Exception as e:
        logger.warning("[z3_encoder] constraint check failed (ownership_pattern/%s): %s", getattr(node, "name", "<unknown>"), e)
        return False


def _count_db_commits(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Count the number of await db.commit() / await db.flush() calls in the function."""
    try:
        src = ast.unparse(node)
        return len(_COMMIT_SRC_RE.findall(src))
    except Exception as e:
        logger.warning("[z3_encoder] constraint check failed (db_commits/%s): %s", getattr(node, "name", "<unknown>"), e)
        return 0


# ---------------------------------------------------------------------------
# Z3 invariant checkers (INV-001 to INV-004) — imported from z3_checkers.py
# Extended invariants (INV-005 to INV-007) are in z3_invariants.py
# ---------------------------------------------------------------------------

from aether_os.phases.p06b_formal_verification.z3_checkers import (  # noqa: E402
    _check_inv001_auth,
    _check_inv002_input,
    _check_inv003_state_machine,
    _check_inv004_sql,
)


# ---------------------------------------------------------------------------
# Main encoder class
# ---------------------------------------------------------------------------

class Z3Encoder:
    """
    Encodes FastAPI security invariants into Z3 SMT formulae and checks them.

    Usage:
        encoder = Z3Encoder(module_ast)
        results = encoder.verify_all()
    """

    def __init__(
        self,
        module_ast: ast.Module,
        module_key: str = "",
        included_auth: Iterable[Tuple[str, str]] = (),
        public_routes: Iterable[str] = (),
    ) -> None:
        self._ast = module_ast
        self._module_key = module_key
        self._included_auth = tuple(included_auth)
        self._public_routes = tuple(public_routes)
        self._routes: Optional[List[RouteInfo]] = None

    def _get_routes(self) -> List[RouteInfo]:
        if self._routes is None:
            self._routes = extract_routes(self._ast, self._module_key, self._included_auth, self._public_routes)
        return self._routes

    def verify_all(self) -> List[InvariantResult]:
        """
        Run all seven invariants across all detected routes.
        INV-001 to INV-004: base invariants (auth, input, state machine, SQL).
        INV-005 to INV-007: extended invariants (tenant isolation, ownership, tx boundary).
        Unverifiable routes are included with status=UNVERIFIABLE for all invariants.
        """
        from aether_os.phases.p06b_formal_verification.z3_invariants import (  # noqa: PLC0415
            _check_inv005_tenant_isolation,
            _check_inv006_resource_ownership,
            _check_inv007_transaction_boundary,
        )

        results: List[InvariantResult] = []
        routes = self._get_routes()

        _unverifiable_inv_list = [
            ("INV-001", "No route reachable without valid JWT"),
            ("INV-002", "All route inputs validated via Pydantic"),
            ("INV-003", "State machine transitions always guarded"),
            ("INV-004", "No f-string interpolation in SQL queries"),
            ("INV-005", "Multi-tenant isolation: DB queries filter by org_id/tenant_id"),
            ("INV-006", "Resource ownership verified before mutation"),
            ("INV-007", "Single transaction boundary per route (no mid-route commits)"),
        ]

        for route in routes:
            if route.is_unverifiable:
                # Authentication comes from dependencies, not the body, so it is still checked.
                results.append(_check_inv001_auth(route))
                for inv_id, inv_name in _unverifiable_inv_list[1:]:
                    results.append(InvariantResult(
                        invariant_id=inv_id,
                        invariant_name=inv_name,
                        route_name=route.name,
                        status="UNVERIFIABLE",
                        proof_method=f"Skipped: {route.unverifiable_reason}",
                        confidence=0.0,
                    ))
                continue

            try:
                results.append(_check_inv001_auth(route))
            except Exception as exc:
                logger.warning("[z3_encoder] INV-001 failed for %s: %s", route.name, exc)
                results.append(InvariantResult(
                    invariant_id="INV-001",
                    invariant_name="No route reachable without valid JWT",
                    route_name=route.name,
                    status="UNVERIFIABLE",
                    proof_method=f"Z3 encoding error: {exc}",
                    confidence=0.0,
                ))

            try:
                results.append(_check_inv002_input(route))
            except Exception as exc:
                logger.warning("[z3_encoder] INV-002 failed for %s: %s", route.name, exc)
                results.append(InvariantResult(
                    invariant_id="INV-002",
                    invariant_name="All route inputs validated via Pydantic",
                    route_name=route.name,
                    status="UNVERIFIABLE",
                    proof_method=f"Z3 encoding error: {exc}",
                    confidence=0.0,
                ))

            try:
                inv3 = _check_inv003_state_machine(route)
                if inv3 is not None:
                    results.append(inv3)
                else:
                    results.append(InvariantResult(
                        invariant_id="INV-003",
                        invariant_name="State machine transitions always guarded",
                        route_name=route.name,
                        status="N/A",
                        proof_method="Route does not use ALLOWED_TRANSITIONS — invariant not applicable",
                    ))
            except Exception as exc:
                logger.warning("[z3_encoder] INV-003 failed for %s: %s", route.name, exc)
                results.append(InvariantResult(
                    invariant_id="INV-003",
                    invariant_name="State machine transitions always guarded",
                    route_name=route.name,
                    status="UNVERIFIABLE",
                    proof_method=f"Z3 encoding error: {exc}",
                    confidence=0.0,
                ))

            try:
                results.append(_check_inv004_sql(route))
            except Exception as exc:
                logger.warning("[z3_encoder] INV-004 failed for %s: %s", route.name, exc)
                results.append(InvariantResult(
                    invariant_id="INV-004",
                    invariant_name="No f-string interpolation in SQL queries",
                    route_name=route.name,
                    status="UNVERIFIABLE",
                    proof_method=f"Z3 encoding error: {exc}",
                    confidence=0.0,
                ))

            try:
                results.append(_check_inv005_tenant_isolation(route))
            except Exception as exc:
                logger.warning("[z3_encoder] INV-005 failed for %s: %s", route.name, exc)
                results.append(InvariantResult(
                    invariant_id="INV-005",
                    invariant_name="Multi-tenant isolation: DB queries filter by org_id/tenant_id",
                    route_name=route.name,
                    status="UNVERIFIABLE",
                    proof_method=f"Z3 encoding error: {exc}",
                    confidence=0.0,
                ))

            try:
                results.append(_check_inv006_resource_ownership(route))
            except Exception as exc:
                logger.warning("[z3_encoder] INV-006 failed for %s: %s", route.name, exc)
                results.append(InvariantResult(
                    invariant_id="INV-006",
                    invariant_name="Resource ownership verified before mutation",
                    route_name=route.name,
                    status="UNVERIFIABLE",
                    proof_method=f"Z3 encoding error: {exc}",
                    confidence=0.0,
                ))

            try:
                results.append(_check_inv007_transaction_boundary(route))
            except Exception as exc:
                logger.warning("[z3_encoder] INV-007 failed for %s: %s", route.name, exc)
                results.append(InvariantResult(
                    invariant_id="INV-007",
                    invariant_name="Single transaction boundary per route (no mid-route commits)",
                    route_name=route.name,
                    status="UNVERIFIABLE",
                    proof_method=f"Z3 encoding error: {exc}",
                    confidence=0.0,
                ))

        return results

    def route_count(self) -> int:
        return len(self._get_routes())
