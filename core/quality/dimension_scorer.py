"""
Per-dimension scoring functions for the AetherOS artifact critic.

Each function accepts a string of file content and returns a DimensionScore.
All scorers are fail-open: if they crash, they return score=0.5 with a finding note.
Static analysis only — no LLM calls, no I/O.
"""
from __future__ import annotations

import ast
import logging
import re

from aether_os.core.quality.dimension_critic_types import DimensionScore, PASSING_THRESHOLD

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: safe AST parse
# ---------------------------------------------------------------------------

def _parse_safe(content: str) -> ast.Module | None:
    """Return parsed AST or None; never raises."""
    try:
        return ast.parse(content)
    except SyntaxError:
        return None


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def score_correctness(content: str) -> DimensionScore:
    """Check syntax validity and obvious structural bugs."""
    findings: list[str] = []
    score = 1.0
    try:
        tree = _parse_safe(content)
        if tree is None:
            return DimensionScore(
                dimension="correctness",
                score=0.0,
                findings=["Syntax error: file cannot be parsed by ast.parse"],
                passed=False,
            )

        # Bare `raise` without exception (common LLM bug)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is None and node.cause is None:
                findings.append("Bare `raise` without exception object found")
                score -= 0.10

        # `pass` as sole function body — placeholder code
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    findings.append(f"Function `{node.name}` has only `pass` body (placeholder)")
                    score -= 0.05

        # __all__ exporting undefined names
        defined_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined_names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        defined_names.add(t.id)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for t in node.targets:
                if not (isinstance(t, ast.Name) and t.id == "__all__"):
                    continue
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            if elt.value not in defined_names:
                                findings.append(
                                    f"__all__ exports `{elt.value}` which is not defined here"
                                )
                                score -= 0.05

        score = max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning("[dimension_scorer] score_correctness crashed: %s", e)
        return DimensionScore(
            dimension="correctness", score=0.5,
            findings=[f"Critic error (fail-open): {e}"], passed=True,
        )

    return DimensionScore(
        dimension="correctness", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )


def score_security(content: str) -> DimensionScore:
    """Check for hardcoded secrets, shell=True, SQL injection, missing auth."""
    findings: list[str] = []
    score = 1.0
    try:
        if re.search(r'shell\s*=\s*True', content):
            findings.append("shell=True found in subprocess call — command injection risk")
            score -= 0.25

        if re.search(r'(?i)(password|secret|api_key|token)\s*=\s*["\'][^"\']{4,}["\']', content):
            if not re.search(r'os\.environ', content):
                findings.append("Possible hardcoded secret or password literal detected")
                score -= 0.20

        if re.search(r'f["\']SELECT|f["\']INSERT|f["\']UPDATE|f["\']DELETE', content, re.IGNORECASE):
            findings.append("f-string SQL construction detected — SQL injection risk")
            score -= 0.30

        if re.search(r'["\']\s*SELECT.*["\'\s]*\+', content, re.IGNORECASE):
            findings.append("String concatenation in SQL query detected — SQL injection risk")
            score -= 0.20

        tree = _parse_safe(content)
        if tree is not None:
            route_methods = {"get", "post", "put", "patch", "delete"}
            unprotected: list[str] = []
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for deco in node.decorator_list:
                    if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                        continue
                    if deco.func.attr.lower() not in (route_methods - {"get"}):
                        continue
                    has_depends = any(
                        isinstance(d, ast.Call)
                        and (
                            (isinstance(d.func, ast.Name) and d.func.id == "Depends")
                            or (isinstance(d.func, ast.Attribute) and d.func.attr == "Depends")
                        )
                        for d in node.args.defaults
                    )
                    if not has_depends:
                        path = (
                            str(deco.args[0].value)
                            if deco.args and isinstance(deco.args[0], ast.Constant)
                            else node.name
                        )
                        if path not in ("/health", "/metrics", "/ready", "/ping"):
                            unprotected.append(f"{deco.func.attr.upper()} {path}")

            if unprotected:
                findings.append(
                    f"Write routes without auth: {', '.join(unprotected[:3])}"
                )
                score -= 0.10 * min(3, len(unprotected)) / 3

        score = max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning("[dimension_scorer] score_security crashed: %s", e)
        return DimensionScore(
            dimension="security", score=0.5,
            findings=[f"Critic error (fail-open): {e}"], passed=True,
        )

    return DimensionScore(
        dimension="security", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )


def score_performance(content: str) -> DimensionScore:
    """Check for N+1 patterns and missing pagination."""
    findings: list[str] = []
    score = 1.0
    try:
        all_calls = re.findall(r'\.all\(\)', content)
        limit_calls = re.findall(r'\.limit\(', content)
        if len(all_calls) > len(limit_calls):
            excess = len(all_calls) - len(limit_calls)
            findings.append(
                f"{excess} use(s) of .all() without .limit() — unbounded query risk"
            )
            score -= min(0.30, 0.10 * excess)

        list_endpoints = re.findall(r'@(?:app|router)\.get\(["\'][^"\']*["\']\)', content)
        if list_endpoints and not re.search(r'\bskip\b|\blimit\b|\boffset\b|\bpage\b', content):
            findings.append("GET endpoints present but no pagination params (skip/limit/offset/page)")
            score -= 0.20

        tree = _parse_safe(content)
        if tree is not None:
            for node in ast.walk(tree):
                if not isinstance(node, ast.For):
                    continue
                for inner in ast.walk(node):
                    if inner is node or not isinstance(inner, ast.For):
                        continue
                    if any(kw in ast.dump(inner) for kw in ["query", "filter", "get", "execute"]):
                        findings.append("Nested loop with DB call — possible N+1 query")
                        score -= 0.10
                        break

        score = max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning("[dimension_scorer] score_performance crashed: %s", e)
        return DimensionScore(
            dimension="performance", score=0.5,
            findings=[f"Critic error (fail-open): {e}"], passed=True,
        )

    return DimensionScore(
        dimension="performance", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )


def score_architecture(content: str) -> DimensionScore:
    """Check that routers delegate to services, not direct DB ops; no god-files."""
    findings: list[str] = []
    score = 1.0
    try:
        is_router = bool(
            re.search(r'APIRouter\(\)|@router\.(get|post|put|patch|delete)', content)
        )

        if is_router:
            tree = _parse_safe(content)
            if tree is not None:
                route_methods = {"get", "post", "put", "patch", "delete"}
                db_in_router: list[str] = []
                _db_patterns = [
                    (r"'attr'\s*:\s*'query'", "db.query()"),
                    (r"'attr'\s*:\s*'execute'", "db.execute()"),
                    (r"'attr'\s*:\s*'add'", "db.add()"),
                    (r"'attr'\s*:\s*'commit'", "db.commit()"),
                    (r"'attr'\s*:\s*'filter'", ".filter()"),
                ]
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    is_route = any(
                        isinstance(d, ast.Call)
                        and isinstance(d.func, ast.Attribute)
                        and d.func.attr.lower() in route_methods
                        for d in node.decorator_list
                    )
                    if not is_route:
                        continue
                    func_src = ast.dump(node)
                    for pattern, label in _db_patterns:
                        if re.search(pattern, func_src):
                            db_in_router.append(f"`{node.name}` uses {label} directly")
                            break

                if db_in_router:
                    findings.append(
                        "DB ops directly in router handler(s): " + "; ".join(db_in_router[:3])
                    )
                    score -= min(0.35, 0.07 * len(db_in_router))

        has_models = bool(re.search(r'class \w+\(Base\)', content))
        has_routes = bool(re.search(r'@(?:app|router)\.(get|post|put|patch|delete)', content))
        if has_models and has_routes:
            findings.append("Models and routes in same file — violates single-responsibility")
            score -= 0.15

        score = max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning("[dimension_scorer] score_architecture crashed: %s", e)
        return DimensionScore(
            dimension="architecture", score=0.5,
            findings=[f"Critic error (fail-open): {e}"], passed=True,
        )

    return DimensionScore(
        dimension="architecture", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )


def score_database(content: str) -> DimensionScore:
    """Check FK constraints, Decimal for money, nullable intent, tablename."""
    findings: list[str] = []
    score = 1.0
    try:
        money_floats = re.findall(
            r'(?i)(price|amount|cost|fee|balance|salary|revenue|total)\s*=\s*Column\(Float',
            content,
        )
        if money_floats:
            findings.append(
                f"Monetary field(s) use Float not Decimal/Numeric: {money_floats[:3]}"
            )
            score -= 0.20

        fk_cols = re.findall(r'ForeignKey\(["\'][^"\']+["\']\)', content)
        if fk_cols and not re.search(r'relationship\(', content):
            findings.append(
                f"{len(fk_cols)} ForeignKey column(s) without relationship() found"
            )
            score -= 0.15

        if re.search(r'primary_key\s*=\s*True.*nullable\s*=\s*True', content):
            findings.append("Primary key column has nullable=True — likely a model error")
            score -= 0.20

        if re.search(r'class \w+\(Base\)', content) and not re.search(r'__tablename__', content):
            findings.append("SQLAlchemy model class without __tablename__")
            score -= 0.15

        score = max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning("[dimension_scorer] score_database crashed: %s", e)
        return DimensionScore(
            dimension="database", score=0.5,
            findings=[f"Critic error (fail-open): {e}"], passed=True,
        )

    return DimensionScore(
        dimension="database", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )


def score_api(content: str) -> DimensionScore:
    """Check HTTP method correctness, URL naming, response_model coverage."""
    findings: list[str] = []
    score = 1.0
    try:
        tree = _parse_safe(content)
        if tree is None:
            return DimensionScore(
                dimension="api", score=0.5,
                findings=["Cannot parse file — skipping API analysis"], passed=True,
            )

        route_methods = {"get", "post", "put", "patch", "delete"}
        routes_found: list[tuple[str, str]] = []
        handlers_total = 0
        handlers_with_response_model = 0

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                    continue
                method = deco.func.attr.lower()
                if method not in route_methods:
                    continue
                path = (
                    str(deco.args[0].value)
                    if deco.args and isinstance(deco.args[0], ast.Constant)
                    else ""
                )
                routes_found.append((method, path))
                handlers_total += 1
                if any(kw.arg == "response_model" for kw in deco.keywords):
                    handlers_with_response_model += 1

        if routes_found:
            delete_via_post = [p for m, p in routes_found if m == "post" and "delete" in p.lower()]
            if delete_via_post:
                findings.append(
                    f"DELETE operations via POST: {delete_via_post[:2]} — use DELETE verb"
                )
                score -= 0.15

            camel_paths = [p for _, p in routes_found if re.search(r'[a-z][A-Z]', p)]
            if camel_paths:
                findings.append(
                    f"camelCase URL paths: {camel_paths[:2]} — use kebab-case or snake_case"
                )
                score -= 0.10

        if handlers_total > 0 and (handlers_with_response_model / handlers_total) < 0.5:
            findings.append(
                f"Only {handlers_with_response_model}/{handlers_total} route(s) have response_model"
            )
            score -= 0.15

        score = max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning("[dimension_scorer] score_api crashed: %s", e)
        return DimensionScore(
            dimension="api", score=0.5,
            findings=[f"Critic error (fail-open): {e}"], passed=True,
        )

    return DimensionScore(
        dimension="api", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )


def score_observability(content: str) -> DimensionScore:
    """Check for logger usage, except blocks missing log calls."""
    findings: list[str] = []
    score = 1.0
    try:
        has_logging = bool(re.search(r'import logging|from logging', content))
        has_logger = bool(re.search(r'logger\s*=\s*logging\.getLogger', content))

        if not has_logging:
            findings.append("logging module not imported — no observability")
            score -= 0.25
        elif not has_logger:
            findings.append("logging imported but no logger = logging.getLogger(...) found")
            score -= 0.10

        tree = _parse_safe(content)
        if tree is not None:
            bare_excepts: list[str] = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                body_src = ast.dump(ast.Module(body=node.body, type_ignores=[]))
                has_log = bool(
                    re.search(
                        r"'attr'\s*:\s*'(warning|error|exception|critical|info|debug)'",
                        body_src,
                    )
                )
                has_raise = any(
                    isinstance(s, ast.Raise)
                    for s in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                )
                if not has_log and not has_raise:
                    exc_type = (
                        node.type.id
                        if node.type and isinstance(node.type, ast.Name)
                        else "Exception"
                    )
                    bare_excepts.append(exc_type)

            if bare_excepts:
                findings.append(
                    f"{len(bare_excepts)} except block(s) with no log or re-raise: {bare_excepts[:3]}"
                )
                score -= min(0.30, 0.05 * len(bare_excepts))

        score = max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning("[dimension_scorer] score_observability crashed: %s", e)
        return DimensionScore(
            dimension="observability", score=0.5,
            findings=[f"Critic error (fail-open): {e}"], passed=True,
        )

    return DimensionScore(
        dimension="observability", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )


def score_testing(content: str) -> DimensionScore:
    """Check seed data density and /health endpoint presence."""
    findings: list[str] = []
    score = 1.0
    try:
        is_seed = bool(
            re.search(r'def seed|def create_seed|insert.*seed|seed_data', content, re.IGNORECASE)
        )
        is_main = bool(re.search(r'app\s*=\s*FastAPI', content))

        if is_seed:
            _exclude = {
                "FastAPI(", "APIRouter(", "Request(", "Response(", "Depends(",
                "Session(", "Column(", "String(", "Integer(", "Float(", "Boolean(",
                "DateTime(", "ForeignKey(", "Enum(", "Text(", "Numeric(", "Decimal(",
            }
            instantiations = [
                i for i in re.findall(r'\b[A-Z]\w+\(', content)
                if i not in _exclude
            ]
            if len(instantiations) < 10:
                findings.append(
                    f"Seed file has only {len(instantiations)} record(s) — target is 20 per entity"
                )
                score -= 0.30
            elif len(instantiations) < 20:
                findings.append(
                    f"Seed file has {len(instantiations)} record(s) — consider 20 for demo data"
                )
                score -= 0.10

        if is_main:
            if not re.search(r'["\']\/health["\']|path\s*=\s*["\']\/health["\']', content):
                findings.append("/health endpoint not found — required for liveness probes")
                score -= 0.25

        score = max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning("[dimension_scorer] score_testing crashed: %s", e)
        return DimensionScore(
            dimension="testing", score=0.5,
            findings=[f"Critic error (fail-open): {e}"], passed=True,
        )

    return DimensionScore(
        dimension="testing", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )
