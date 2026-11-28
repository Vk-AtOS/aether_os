"""Static FastAPI route map for a generated project: full path, method, handler AST and whether auth applies.

Resolves `APIRouter(prefix=..., dependencies=[...])`, `include_router(x, prefix=..., dependencies=[...])` chains
across modules (by import), route-level `dependencies=`, `Depends(...)` / `Security(...)` parameters and
`Annotated[User, Depends(get_current_user)]` aliases. Nothing is imported or executed.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from aether_os.core.rulepacks.base import Project, call_name, const_str, dotted, kw

METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
AUTH_NAME = re.compile(r"current_?(?:active_?)?user|get_?user|auth(?!or)|require|verify_?(?:token|user|jwt|api)|token|login_required|"
                       r"admin|permission|role|principal|api_?key|jwt|logged_?in|owner", re.I)
AUTH_CALL = re.compile(r"current_?user|authenticate|verify_?token|decode_?(?:access_?)?token|require_\w+", re.I)


@dataclass
class Route:
    file: str
    method: str
    path: str
    func: ast.FunctionDef | ast.AsyncFunctionDef
    line: int
    auth: bool
    params: list[str] = field(default_factory=list)
    dep_names: list[str] = field(default_factory=list)

    @property
    def path_params(self) -> list[str]:
        return re.findall(r"\{(\w+)(?::[^}]*)?\}", self.path)


def _depends_target(node: ast.AST) -> str | None:
    """'get_current_user' for Depends(get_current_user) / Security(x, scopes=...); None otherwise."""
    if isinstance(node, ast.Call) and call_name(node).split(".")[-1] in ("Depends", "Security"):
        if node.args:
            return dotted(node.args[0]) or (call_name(node.args[0]) if isinstance(node.args[0], ast.Call) else "") or "?"
        return "?"
    return None


def _list_deps(node: ast.AST | None) -> list[str]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return [t for t in (_depends_target(e) for e in node.elts) if t]
    return []


def _annotated_deps(ann: ast.AST | None) -> list[str]:
    if isinstance(ann, ast.Subscript) and dotted(ann.value).split(".")[-1] == "Annotated":
        sl = ann.slice
        elts = sl.elts if isinstance(sl, ast.Tuple) else [sl]
        return [t for t in (_depends_target(e) for e in elts[1:]) if t]
    return []


def _default_deps(default: ast.AST | None, dep_vars: dict[str, str]) -> list[str]:
    """Dependency names a parameter default declares: Depends(x), a module-level Depends variable, or a
    factory call such as `_auth()` that returns Depends(...)."""
    target = _depends_target(default)
    if target:
        return [target]
    if isinstance(default, ast.Name) and default.id in dep_vars:
        return [dep_vars[default.id]]
    if isinstance(default, ast.Call) and AUTH_NAME.search(call_name(default)):
        return [call_name(default)]
    return []


def auth_aliases(p: Project) -> set[str]:
    """Module-level `CurrentUser = Annotated[User, Depends(get_current_user)]` names, project wide."""
    names = set()
    for rel in p.python_files():
        tree = p.tree(rel)
        for n in getattr(tree, "body", []):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                if any(AUTH_NAME.search(d) for d in _annotated_deps(n.value)):
                    names.add(n.targets[0].id)
    return names


def _module_index(p: Project) -> dict[str, str]:
    """dotted module path (every suffix) -> file, e.g. 'app.routers.tasks', 'routers.tasks', 'tasks'."""
    idx: dict[str, str] = {}
    for rel in p.python_files():
        parts = rel[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for i in range(len(parts)):
            idx.setdefault(".".join(parts[i:]), rel)
    return idx


def _imports(tree: ast.AST, rel: str, idx: dict[str, str]) -> dict[str, tuple[str, str | None]]:
    """local name -> (file, attribute or None) for first-party imports."""
    out: dict[str, tuple[str, str | None]] = {}
    pkg = rel.rsplit("/", 1)[0].replace("/", ".") if "/" in rel else ""
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            if n.level:
                base = pkg.split(".") if pkg else []
                base = base[: len(base) - (n.level - 1)] if n.level > 1 else base
                mod = ".".join([*base, mod] if mod else base)
            for a in n.names:
                local = a.asname or a.name
                sub = f"{mod}.{a.name}" if mod else a.name
                if sub in idx:          # `from app.routers import tasks` -> module tasks
                    out[local] = (idx[sub], None)
                elif mod in idx:        # `from app.routers.tasks import router`
                    out[local] = (idx[mod], a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name in idx:
                    out[a.asname or a.name] = (idx[a.name], None)
    return out


def collect_routes(p: Project) -> list[Route]:
    idx = _module_index(p)
    aliases = auth_aliases(p)
    routers: dict[tuple[str, str], tuple[str, bool, str]] = {}  # (file, var) -> (prefix, auth, kind)
    includes: list[tuple[tuple[str, str], tuple[str, str], str, bool]] = []  # child, parent, prefix, auth
    for rel in p.python_files():
        tree = p.tree(rel)
        if tree is None:
            continue
        imports = _imports(tree, rel, idx)
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and len(n.targets) == 1:
                kind = call_name(n.value).split(".")[-1]
                if kind in ("APIRouter", "FastAPI") and isinstance(n.targets[0], ast.Name):
                    deps = _list_deps(kw(n.value, "dependencies"))
                    routers[(rel, n.targets[0].id)] = (const_str(kw(n.value, "prefix")) or "",
                                                       any(AUTH_NAME.search(d) for d in deps), kind)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "include_router" and n.args:
                parent = (rel, dotted(n.func.value))
                target = dotted(n.args[0])
                head, _, attr = target.partition(".")
                if head in imports:
                    f, a = imports[head]
                    child = (f, attr or a or "router")
                else:
                    child = (rel, target)
                includes.append((child, parent, const_str(kw(n, "prefix")) or "",
                                 any(AUTH_NAME.search(d) for d in _list_deps(kw(n, "dependencies")))))

    def mounts(key: tuple[str, str], depth: int = 0) -> list[tuple[str, bool]]:
        prefix, auth, kind = routers.get(key, ("", False, "APIRouter"))
        ups = [(c, par, pre, a) for c, par, pre, a in includes if c == key]
        if not ups or depth > 8:
            return [(prefix, auth)]
        out = []
        for _, par, pre, a in ups:
            for ppre, pauth in mounts(par, depth + 1):
                out.append((ppre + pre + prefix, pauth or a or auth))
        return out

    routes: list[Route] = []
    for rel in p.python_files():
        tree = p.tree(rel)
        if tree is None:
            continue
        # Module-level `_current_user = Depends(get_current_user)` lets handlers write `user=_current_user`.
        dep_vars = {n.targets[0].id: _depends_target(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and _depends_target(n.value)}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in fn.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                meth = dec.func.attr
                if meth not in METHODS | {"api_route"} or not dec.args or const_str(dec.args[0]) is None:
                    continue
                var = dotted(dec.func.value)
                if (rel, var) not in routers and not re.search(r"router|app|api", var, re.I):
                    continue
                methods = [meth.upper()]
                if meth == "api_route":
                    ms = kw(dec, "methods")
                    methods = [const_str(e) or "GET" for e in getattr(ms, "elts", [])] or ["GET"]
                deps = _list_deps(kw(dec, "dependencies"))
                params, auth = [], any(AUTH_NAME.search(d) for d in deps)
                args = fn.args.args + fn.args.kwonlyargs
                defaults = [None] * (len(fn.args.args) - len(fn.args.defaults)) + list(fn.args.defaults) + list(fn.args.kw_defaults)
                for a, d in zip(args, defaults):
                    params.append(a.arg)
                    targets = _annotated_deps(a.annotation) + _default_deps(d, dep_vars)
                    deps += targets
                    ann = dotted(a.annotation) if a.annotation is not None else ""
                    if any(AUTH_NAME.search(t) for t in targets) or ann in aliases or re.search(r"current_?user", ann, re.I):
                        auth = True
                if not auth:
                    auth = any(isinstance(c, ast.Call) and AUTH_CALL.search(call_name(c)) for c in ast.walk(fn))
                for prefix, mount_auth in mounts((rel, var)):
                    for m in methods:
                        routes.append(Route(rel, m, (prefix + const_str(dec.args[0])) or "/", fn, fn.lineno,
                                            auth or mount_auth, params, deps))
    return routes


DEFAULT_PUBLIC = ("/", "/health", "/healthz", "/ready", "/readyz", "/livez", "/version", "/auth/login",
                  "/auth/register", "/auth/signup", "/auth/token", "/auth/refresh", "/login", "/register",
                  "/signup", "/token", "/refresh", "/auth/forgot-password", "/auth/reset-password")
_API_PREFIX = re.compile(r"^/api(?:/v\d+)?(?=/|$)")


def is_public(route: Route, public: list[str] | tuple[str, ...]) -> bool:
    """An entry is '/path', 'METHOD /path' or '/prefix/*'. Paths match with or without an /api[/vN] prefix."""
    path = route.path.rstrip("/") or "/"
    bare = _API_PREFIX.sub("", path) or "/"
    for entry in public:
        meth, _, pat = entry.strip().rpartition(" ")
        if meth and meth.upper() != route.method:
            continue
        pat = pat.rstrip("/") or "/"
        if pat.endswith("/*"):
            base = pat[:-2]
            if any(x == base or x.startswith(base + "/") for x in (path, bare)):
                return True
        elif pat in (path, bare):
            return True
    return False
