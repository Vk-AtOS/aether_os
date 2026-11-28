"""
AST resolution of FastAPI route dependencies for the static invariant checks (KAN-254).

The old scan only looked at the route function's own Depends(...) defaults, so it flagged routes that are guarded
one level up (APIRouter(dependencies=[...]), include_router(..., dependencies=[...])), guarded through an
Annotated alias (CurrentUser = Annotated[User, Depends(get_current_user)]) or guarded by a custom dependency
(require_role(...), require_admin, a local function that itself depends on get_current_user). It also found tenant
filters with a regex that stopped at the first ")". Everything here walks the AST instead.

Public routes: a route is intentionally public when it carries a `@public_route` decorator, is listed in a
module-level PUBLIC_ROUTES list ("POST /auth/login" or just "/health"), or is in the allowlist passed to the encoder.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

AUTH_DEP_NAMES = frozenset({
    "get_current_user", "get_current_active_user", "get_current_admin", "get_current_superuser",
    "require_auth", "require_admin", "require_role", "require_roles", "require_admin_role",
    "require_permission", "require_permissions", "require_scope", "current_user", "oauth2_scheme", "security",
})
# Names like get_current_tenant_user / require_manager are the project's own auth dependencies.
AUTH_DEP_PREFIXES = ("get_current_", "require_")
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
_TENANT_COLUMNS = frozenset({"org_id", "tenant_id", "organization_id", "workspace_id"})
PUBLIC_DECORATOR = "public_route"


def _leaf_name(node: ast.AST) -> str:
    """get_current_user, auth.get_current_user and require_role("x") all reduce to the callable's last name."""
    if isinstance(node, ast.Call):
        return _leaf_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_auth_name(name: str, local_auth: Set[str]) -> bool:
    return bool(name) and (name in AUTH_DEP_NAMES or name in local_auth or name.startswith(AUTH_DEP_PREFIXES))


def _is_depends_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _leaf_name(node.func) in ("Depends", "Security")


def expr_is_auth(expr: Optional[ast.AST], local_auth: Set[str], alias_auth: Set[str]) -> bool:
    """True for Depends(<auth>), Annotated[T, Depends(<auth>)], an auth alias name, or a list/tuple holding any."""
    if expr is None:
        return False
    if _is_depends_call(expr):
        return any(_is_auth_name(_leaf_name(a), local_auth) for a in expr.args[:1])  # type: ignore[attr-defined]
    if isinstance(expr, ast.Subscript) and _leaf_name(expr.value) == "Annotated":
        return any(expr_is_auth(n, local_auth, alias_auth) for n in ast.walk(expr.slice) if n is not expr.slice
                   and _is_depends_call(n))
    if isinstance(expr, ast.Name):
        return expr.id in alias_auth or expr.id in AUTH_DEP_NAMES
    if isinstance(expr, (ast.List, ast.Tuple)):
        return any(expr_is_auth(e, local_auth, alias_auth) for e in expr.elts)
    return False


@dataclass
class RouterFacts:
    prefix: str = ""
    auth: bool = False


@dataclass
class ModuleDeps:
    """Per-module facts: which local callables/aliases imply authentication, router prefixes and router-level deps."""
    local_auth: Set[str] = field(default_factory=set)
    alias_auth: Set[str] = field(default_factory=set)
    routers: Dict[str, RouterFacts] = field(default_factory=dict)
    imports: Dict[str, Tuple[str, str]] = field(default_factory=dict)   # local name -> (module stem, original name)
    public_routes: List[str] = field(default_factory=list)


def _const_str(node: Optional[ast.AST]) -> str:
    return str(node.value) if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def _kw(call: ast.Call, name: str) -> Optional[ast.expr]:
    return next((k.value for k in call.keywords if k.arg == name), None)


def analyse_module(tree: ast.Module) -> ModuleDeps:
    deps = ModuleDeps()
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            stem = n.module.split(".")[-1]
            for a in n.names:
                deps.imports[a.asname or a.name] = (stem, a.name)
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            value = n.value
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if isinstance(value, ast.Call) and _leaf_name(value.func) in ("APIRouter", "FastAPI"):
                for nm in names:
                    deps.routers[nm] = RouterFacts(prefix=_const_str(_kw(value, "prefix")))
            if "PUBLIC_ROUTES" in names and isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                deps.public_routes += [s for s in (_const_str(e) for e in value.elts) if s]

    # Fixpoint: a local function depends on auth when any of its (or its inner function's) parameters does;
    # an alias is auth when it wraps one. Aliases and functions feed each other, so iterate to stability.
    changed = True
    while changed:
        changed = False
        for n in ast.walk(tree):
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                ann_value = n.value
                if expr_is_auth(ann_value, deps.local_auth, deps.alias_auth):
                    for t in targets:
                        if isinstance(t, ast.Name) and t.id not in deps.alias_auth:
                            deps.alias_auth.add(t.id)
                            changed = True
        for f in funcs:
            if f.name in deps.local_auth:
                continue
            if any(_param_is_auth(p, d, deps) for sub in ast.walk(f)
                   if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                   for p, d in _params_with_defaults(sub)):
                deps.local_auth.add(f.name)
                changed = True

    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Call):
            if _leaf_name(n.value.func) in ("APIRouter", "FastAPI"):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                auth = expr_is_auth(_kw(n.value, "dependencies"), deps.local_auth, deps.alias_auth)
                for t in targets:
                    if isinstance(t, ast.Name):
                        deps.routers[t.id].auth = auth
    return deps


def _params_with_defaults(fn: ast.AST) -> Iterable[Tuple[ast.arg, Optional[ast.expr]]]:
    a = fn.args  # type: ignore[attr-defined]
    pos = a.posonlyargs + a.args
    defaults: List[Optional[ast.expr]] = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    yield from zip(pos, defaults)
    yield from zip(a.kwonlyargs, a.kw_defaults)


def _param_is_auth(arg: ast.arg, default: Optional[ast.expr], deps: ModuleDeps) -> bool:
    return expr_is_auth(default, deps.local_auth, deps.alias_auth) or expr_is_auth(
        arg.annotation, deps.local_auth, deps.alias_auth)


def function_has_auth_param(fn: ast.AST, deps: ModuleDeps) -> bool:
    return any(_param_is_auth(p, d, deps) for p, d in _params_with_defaults(fn))


def collect_included_auth(modules: Dict[str, ast.Module]) -> FrozenSet[Tuple[str, str]]:
    """(module stem, router variable) pairs mounted with auth dependencies, found across the whole project:
    app.include_router(users_router, dependencies=[Depends(get_current_user)]) in main.py guards every route of
    the router defined in routers/users.py. Also covers a router mounted on an already-guarded parent router/app."""
    included: Set[Tuple[str, str]] = set()
    analysed = {stem: analyse_module(t) for stem, t in modules.items()}
    for stem, tree in modules.items():
        deps = analysed[stem]
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "include_router"
                    and n.args):
                continue
            guarded = expr_is_auth(_kw(n, "dependencies"), deps.local_auth, deps.alias_auth)
            parent = n.func.value
            if isinstance(parent, ast.Name) and deps.routers.get(parent.id, RouterFacts()).auth:
                guarded = True
            if not guarded:
                continue
            target = n.args[0]
            if isinstance(target, ast.Name):
                included.add(deps.imports.get(target.id, (stem, target.id)))
            elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                included.add((target.value.id, target.attr))   # users.router after `from routers import users`
    return frozenset(included)


# ---------------------------------------------------------------------------
# Route-level helpers
# ---------------------------------------------------------------------------

def route_decorator(fn: ast.AST) -> Optional[Tuple[ast.Call, str, str]]:
    """(decorator call, receiver variable, METHOD) for @router.get("/x") style decorators."""
    for dec in fn.decorator_list:  # type: ignore[attr-defined]
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in _HTTP_METHODS:
            recv = dec.func.value.id if isinstance(dec.func.value, ast.Name) else ""
            return dec, recv, dec.func.attr.upper()
    return None


def has_public_marker(fn: ast.AST) -> bool:
    return any(_leaf_name(d) == PUBLIC_DECORATOR for d in fn.decorator_list)  # type: ignore[attr-defined]


def _norm(path: str) -> str:
    p = "/" + path.strip().strip("/")
    return p[4:] if p.startswith("/api/") else p


def in_public_allowlist(method: str, path: str, entries: Iterable[str]) -> bool:
    """Entries are "METHOD /path" or "/path". /api prefixes are ignored on both sides because the router prefix is
    added in main.py, which this file may not see."""
    want = _norm(path)
    for entry in entries:
        parts = entry.split(None, 1)
        if len(parts) == 2 and parts[0].isalpha():
            if parts[0].upper() != method:
                continue
            ent = parts[1]
        else:
            ent = entry
        if _norm(ent) == want:
            return True
    return False


def _arg_names(call: ast.Call) -> Iterable[str]:
    """Names/attributes/strings/keywords used in the call's arguments (not in the chain it is called on)."""
    parts: List[ast.AST] = list(call.args) + list(call.keywords)
    for n in (m for part in parts for m in ast.walk(part)):
        if isinstance(n, ast.Name):
            yield n.id
        elif isinstance(n, ast.Attribute):
            yield n.attr
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.value
        elif isinstance(n, ast.keyword) and n.arg:
            yield n.arg


def has_tenant_filter(fn: ast.AST) -> bool:
    """True when the function filters a query on a tenant column: .where(...)/.filter(...)/.filter_by(...) whose
    arguments mention org_id/tenant_id/... anywhere, however deeply nested (and_(), or_(), parentheses). The old
    regex stopped at the first ")" and missed .where(and_(Model.org_id == x, ...))."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("where", "filter", "filter_by"):
            if any(name in _TENANT_COLUMNS for name in _arg_names(n)):
                return True
    return False
