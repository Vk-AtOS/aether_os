"""Prod-readiness checks that read Python code (AST).

PRD-001 no /health      PRD-002 no /ready that checks the database
PRD-004 create_all() in the production startup path
PRD-005 DATABASE_URL not from the environment, or a SQLite default
PRD-007 print() instead of logging / no logging configuration
PRD-008 outbound HTTP call without a timeout
PRD-013 demo seed runs unconditionally at startup
"""
from __future__ import annotations

import ast
import re

from aether_os.core.rulepacks.base import Finding, Project, call_name, const_str, dotted, kw, make
from aether_os.core.rulepacks.pyroutes import _API_PREFIX, Route

PACK = "prodready"
GUARD_WORDS = re.compile(r"test|sqlite|env|debug|develop|\bdev\b|demo|seed|settings\.|environ|getenv|local", re.I)
NON_PROD_PATH = re.compile(r"(^|/)(scripts?|tests?|alembic|migrations|tools)/|(^|/)(seed\w*|conftest|manage|init_db|cli\w*)\.py$")
SEED_CALL = re.compile(r"^(?:seed\w*|\w+_seed|create_demo\w*|load_demo\w*|load_fixtures|create_sample\w*|populate\w*|insert_demo\w*)$", re.I)
LOG_CONFIG = re.compile(r"logging\.basicConfig|dictConfig|logging\.config|structlog|loguru|JsonFormatter|jsonlogger|"
                        r"python_json_logger|setup_logging|configure_logging")


def _guarded_ids(tree: ast.AST) -> set[int]:
    """Nodes inside an `if` whose condition mentions an environment / test / demo switch."""
    ids: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.If, ast.IfExp)) and GUARD_WORDS.search(ast.unparse(n.test)):
            ids |= {id(x) for x in ast.walk(n)}
    return ids


def _bare(path: str) -> str:
    return _API_PREFIX.sub("", path.rstrip("/")) or "/"


def check_health(p: Project, routes: list[Route], out: list[Finding]) -> None:
    gets = [r for r in routes if r.method == "GET"]
    health = [r for r in gets if _bare(r.path) in ("/health", "/healthz", "/livez", "/health/live", "/ping")]
    ready = [r for r in gets if _bare(r.path) in ("/ready", "/readyz", "/health/ready", "/health/db")]
    app = next((f for f in p.python_files() if "FastAPI(" in p.text(f)), routes[0].file if routes else "")
    if not health:
        out.append(make(PACK, p, "PRD-001", "high", app, 1, "no GET /health liveness endpoint",
                        "add GET /health returning {\"status\": \"ok\"} without touching dependencies"))
    db_check = re.compile(r"execute|SELECT 1|\bping\b|session|engine|connect|\bdb\b", re.I)
    if not any(db_check.search(ast.unparse(r.func)) for r in ready + health):
        at = (ready or health)[0] if (ready or health) else None
        out.append(make(PACK, p, "PRD-002", "medium", at.file if at else app, at.line if at else 1,
                        "no readiness endpoint that checks the database",
                        "add GET /ready that runs SELECT 1 on the database (and pings Redis) and returns 503 on failure"))


def check_code(p: Project, out: list[Finding]) -> None:
    db_url_read = False
    for rel in p.python_files():
        tree = p.tree(rel)
        if tree is None:
            continue
        text = p.text(rel)
        guarded = _guarded_ids(tree)
        prod_path = not NON_PROD_PATH.search(rel)
        prints = 0
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr == "create_all" and "metadata" in dotted(n.value) \
                    and prod_path and id(n) not in guarded:
                out.append(make(PACK, p, "PRD-004", "medium", rel, n.lineno, "metadata.create_all() runs in the production path",
                                "create and change tables with Alembic migrations (alembic upgrade head) only"))
            if not isinstance(n, ast.Call):
                continue
            name = call_name(n)
            if name == "print" and prod_path:
                prints += 1
            if name.endswith(("getenv", "environ.get")) and n.args and const_str(n.args[0]) == "DATABASE_URL":
                db_url_read = True
                default = const_str(n.args[1]) if len(n.args) > 1 else const_str(kw(n, "default"))
                if default and default.startswith("sqlite"):
                    out.append(make(PACK, p, "PRD-005", "high", rel, n.lineno, "DATABASE_URL falls back to SQLite",
                                    "require DATABASE_URL (os.environ['DATABASE_URL']); SQLite only in tests"))
            if name.split(".")[-1] in ("create_engine", "create_async_engine") and n.args:
                lit = const_str(n.args[0])
                if lit is not None and id(n) not in guarded and prod_path:
                    out.append(make(PACK, p, "PRD-005", "high" if lit.startswith("sqlite") else "medium", rel, n.lineno,
                                    "database URL hard-coded in create_engine()", "pass settings.DATABASE_URL read from the environment"))
            _timeouts(p, rel, n, name, out)
        if prints:
            line = next((i for i, t in enumerate(text.splitlines(), 1) if re.match(r"\s*print\(", t)), 1)
            out.append(make(PACK, p, "PRD-007", "low", rel, line, f"{prints} print() call(s) in application code",
                            "use logging.getLogger(__name__) so output is levelled and structured"))
        db_url_read |= _settings_db_url(p, rel, tree, out)
        if "DATABASE_URL" in text and re.search(r"environ\[\s*['\"]DATABASE_URL", text):
            db_url_read = True
    uses_sql = any(re.search(r"^\s*(?:from|import) (?:sqlalchemy|sqlmodel)", p.text(f), re.M) for f in p.python_files())
    if uses_sql and not db_url_read:
        engines = [f for f in p.python_files() if re.search(r"create_(?:async_)?engine", p.text(f))]
        out.append(make(PACK, p, "PRD-005", "medium", (engines or p.python_files())[0], 1,
                        "DATABASE_URL is not read from the environment",
                        "read DATABASE_URL via pydantic-settings or os.environ"))
    app = next((f for f in p.python_files() if "FastAPI(" in p.text(f)), None)
    if app and not any(LOG_CONFIG.search(p.text(f)) for f in p.python_files()):
        out.append(make(PACK, p, "PRD-007", "low", app, 1, "no logging configuration",
                        "configure logging once at startup (level from LOG_LEVEL, JSON formatter in production)"))
    _seed(p, out)


def _settings_db_url(p: Project, rel: str, tree: ast.AST, out: list[Finding]) -> bool:
    """pydantic-settings `database_url: str = "sqlite:///..."`. Returns True when the class declares the field."""
    found = False
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef) or not any("Settings" in dotted(b) for b in cls.bases):
            continue
        for b in cls.body:
            if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name) and b.target.id.lower() == "database_url":
                found = True
                default = const_str(b.value)
                if isinstance(b.value, ast.Call) and call_name(b.value).endswith("Field"):
                    default = const_str(b.value.args[0]) if b.value.args else const_str(kw(b.value, "default"))
                if default and default.startswith("sqlite"):
                    out.append(make(PACK, p, "PRD-005", "high", rel, b.lineno, "settings default DATABASE_URL is SQLite",
                                    "give database_url no default so a missing value fails at startup"))
    return found


def _timeouts(p: Project, rel: str, n: ast.Call, name: str, out: list[Finding]) -> None:
    timeout = kw(n, "timeout")
    if re.fullmatch(r"requests\.(get|post|put|patch|delete|head|options|request)", name) and timeout is None:
        out.append(make(PACK, p, "PRD-008", "medium", rel, n.lineno, f"{name}() without timeout (waits forever)",
                        "pass timeout=10 (or a settings value) and handle requests.Timeout"))
    elif name in ("urllib.request.urlopen", "urlopen") and timeout is None and len(n.args) < 3:
        out.append(make(PACK, p, "PRD-008", "medium", rel, n.lineno, "urlopen() without timeout", "pass timeout=10"))
    elif re.match(r"(httpx|aiohttp)\.", name) and isinstance(timeout, ast.Constant) and timeout.value is None:
        out.append(make(PACK, p, "PRD-008", "medium", rel, n.lineno, f"{name}(timeout=None) disables the timeout",
                        "use a finite timeout, e.g. httpx.Timeout(10.0)"))


def _startup_funcs(tree: ast.AST) -> list[ast.AST]:
    funcs = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decos = " ".join(ast.unparse(d) for d in n.decorator_list)
            if "startup" in decos or n.name in ("lifespan", "startup", "on_startup") or "asynccontextmanager" in decos and "lifespan" in n.name:
                funcs.append(n)
    return funcs


def _seed(p: Project, out: list[Finding]) -> None:
    for rel in p.python_files():
        tree = p.tree(rel)
        if tree is None or NON_PROD_PATH.search(rel):
            continue
        guarded = _guarded_ids(tree)
        scopes = _startup_funcs(tree)
        if "FastAPI(" in p.text(rel):
            scopes.append(ast.Module(body=[s for s in tree.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], type_ignores=[]))
        for scope in scopes:
            for n in ast.walk(scope):
                if isinstance(n, ast.Call) and SEED_CALL.match(call_name(n).split(".")[-1] or "") and id(n) not in guarded:
                    out.append(make(PACK, p, "PRD-013", "high", rel, n.lineno, f"{call_name(n)}() runs on every startup, including production",
                                    "run demo seeding only when an explicit flag is set (if settings.SEED_DEMO:), never by default"))
