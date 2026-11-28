"""Route-level security checks for generated FastAPI apps.

SEC-007 route without an auth dependency (unless allow-listed as public)
SEC-008 object fetched by id with no owner / tenant filter (heuristic)
SEC-012 no security-headers middleware or proxy config
SEC-013 auth routes without rate limiting
"""
from __future__ import annotations

import ast
import re

from aether_os.core.rulepacks.base import Finding, Project, call_name, make
from aether_os.core.rulepacks.pyroutes import DEFAULT_PUBLIC, Route, collect_routes, is_public

PACK = "security"
OWNERSHIP = re.compile(r"owner|tenant|org(?:anization)?_id|user_id|current_user|created_by|account_id|workspace|"
                       r"team_id|is_admin|is_superuser|role|permission|require_|can_access|authori[sz]|check_access|"
                       r"ensure_|\buser\.id\b|\buser\b", re.I)
OWNER_DEP = re.compile(r"owner|tenant|permission|authori[sz]|can_access|check_access|member", re.I)
HEADERS = ("X-Content-Type-Options", "Content-Security-Policy", "X-Frame-Options", "Strict-Transport-Security",
           "Referrer-Policy", "frame-ancestors")
HEADER_LIBS = re.compile(r"\bsecure\.Secure\b|SecureHeaders|secweb|starlette_securityheaders|SecurityHeadersMiddleware")
AUTH_PATH = re.compile(r"login|signin|sign-in|/token\b|register|signup|sign-up|password|reset|otp|magic-link", re.I)
GLOBAL_LIMIT = re.compile(r"SlowAPIMiddleware|default_limits|RateLimitMiddleware|limit_req_zone|limit_req\b|"
                          r"FastAPILimiter|RateLimiter\(")


def _body_src(fn: ast.AST) -> str:
    return "\n".join(ast.unparse(s) for s in getattr(fn, "body", []))


def _fetches_by_id(fn: ast.AST, ids: set[str]) -> bool:
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        name = call_name(n)
        last = name.split(".")[-1]
        arg_names = {a.id for a in n.args if isinstance(a, ast.Name)} | {k.value.id for k in n.keywords if isinstance(k.value, ast.Name)}
        if last in ("get", "get_or_404", "first_or_404", "get_one", "filter_by", "find_one") and "." in name and arg_names & ids:
            return True
        if last in ("filter", "where"):
            for a in n.args:
                if isinstance(a, ast.Compare) and {x.id for x in [a.left, *a.comparators] if isinstance(x, ast.Name)} & ids:
                    return True
    return False


def _auth(p: Project, routes: list[Route], public: list[str], out: list[Finding]) -> None:
    exposed = [r for r in routes if not r.auth and not is_public(r, public)]
    if not exposed:
        return
    if not any(r.auth for r in routes):
        # No route uses auth at all: one project finding, not one per route, so the repair targets the design.
        first = exposed[0]
        out.append(make(PACK, p, "SEC-007", "high", first.file, first.line,
                        f"no route uses an auth dependency; {len(exposed)} non-public route(s) are open, e.g. "
                        + ", ".join(f"{r.method} {r.path}" for r in exposed[:5]),
                        "add router-level dependencies=[Depends(get_current_user)] and list truly public paths in the allow-list"))
        return
    # One finding per handler and path: an api_route serving 7 methods is one fix, not 7.
    grouped: dict[tuple[str, int, str], list[str]] = {}
    for r in exposed:
        grouped.setdefault((r.file, r.line, r.path), []).append(r.method)
    for (file, line, path), methods in grouped.items():
        sev = "medium" if set(methods) <= {"GET", "HEAD", "OPTIONS"} else "high"
        out.append(make(PACK, p, "SEC-007", sev, file, line, f"{', '.join(methods)} {path} has no auth dependency",
                        "add current_user: User = Depends(get_current_user) (or router dependencies), or mark the path public"))


def _idor(p: Project, routes: list[Route], public: list[str], out: list[Finding]) -> None:
    seen: set[int] = set()
    for r in routes:
        ids = {x for x in r.path_params if x == "id" or x.endswith("id")}
        if not ids or id(r.func) in seen or is_public(r, public):
            continue
        seen.add(id(r.func))
        if not _fetches_by_id(r.func, ids):
            continue
        # get_current_user only says who is asking; a dependency must name ownership to count as a check.
        if OWNERSHIP.search(_body_src(r.func)) or any(OWNER_DEP.search(d) for d in r.dep_names):
            continue
        out.append(make(PACK, p, "SEC-008", "medium", r.file, r.line,
                        f"{r.method} {r.path} loads an object by {', '.join(sorted(ids))} without an owner or tenant check",
                        "filter by owner_id == current_user.id (or tenant) and return 404 when it does not match"))


def _headers(p: Project, out: list[Finding]) -> None:
    app_file = next((f for f in p.python_files() if re.search(r"\bFastAPI\(", p.text(f))), None)
    if app_file is None:
        return
    blobs = [p.text(f) for f in p.python_files()] + [p.text(f) for f in p.files if re.search(r"nginx|caddy|\.conf$", f, re.I)]
    if any(h in b for b in blobs for h in HEADERS) or any(HEADER_LIBS.search(b) for b in blobs):
        return
    line = next((i for i, t in enumerate(p.text(app_file).splitlines(), 1) if "FastAPI(" in t), 1)
    out.append(make(PACK, p, "SEC-012", "medium", app_file, line, "no security headers (CSP, nosniff, frame options, HSTS, referrer policy)",
                    "add a middleware that sets X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy, "
                    "a Content-Security-Policy, and HSTS behind TLS (or set them in nginx)"))


def _rate_limit(p: Project, routes: list[Route], out: list[Finding]) -> None:
    blobs = [p.text(f) for f in p.files if f.endswith((".py", ".conf")) or "nginx" in f]
    if any(GLOBAL_LIMIT.search(b) for b in blobs):
        return
    for r in routes:
        if r.method != "POST" or not AUTH_PATH.search(r.path):
            continue
        decos = " ".join(ast.unparse(d) for d in r.func.decorator_list)
        if re.search(r"limit|throttl", decos + " " + " ".join(r.dep_names), re.I):
            continue
        out.append(make(PACK, p, "SEC-013", "medium", r.file, r.line, f"{r.method} {r.path} is not rate limited",
                        "add a limiter (e.g. slowapi @limiter.limit(\"5/minute\")) or a rate-limit dependency on auth routes"))


def scan_app(p: Project, public_routes: list[str] | None = None) -> list[Finding]:
    routes = collect_routes(p)
    public = list(DEFAULT_PUBLIC) if public_routes is None else list(public_routes) + ["/health", "/healthz", "/ready", "/readyz"]
    out: list[Finding] = []
    _auth(p, routes, public, out)
    _idor(p, routes, public, out)
    _headers(p, out)
    _rate_limit(p, routes, out)
    return out

