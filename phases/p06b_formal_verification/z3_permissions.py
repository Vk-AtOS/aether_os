"""
INV-008 / INV-009: prove the generated permission RULE, not an AST boolean (KAN-100).

The other invariants extract a yes/no fact from the source (is there a Depends? is there a
.where(org_id)?) and ask Z3 whether that fact equals itself. This module takes the rule the
generated app actually enforces, services/permissions.py: the PERMISSIONS table plus the
decision function _has_permission(role, resource, action), and proves two properties of that
rule over the WHOLE domain, including roles, resources and actions the table never mentions:

  INV-008  Deny by default: a role that is not in the table is refused every action on every
           resource (including the "*" resource and the "*" action).
  INV-009  Read-only roles cannot mutate: a role named like a read-only one (readonly, viewer,
           guest, ...) is refused create / update / delete / write on every resource.

How the proof is made honest:
  * the decision function in the file is compared (as an AST) with the one AetherOS generates;
    if it differs the modelled rule is not the enforced rule and the result is UNVERIFIABLE;
  * the rule is encoded symbolically over finite sorts that contain a fresh "other" member for
    roles, resources and actions, so one UNSAT answer covers every unseen value;
  * Z3 decides it when installed; otherwise the same finite domain is enumerated exhaustively
    (a complete proof too, the domain being finite). proof_method says which engine ran.
"""
from __future__ import annotations

import ast
import itertools
import logging
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from aether_os.core.quality._project_root import relative_to_root, require_project_root
from aether_os.core.run_app import safe_fs
from aether_os.phases.p06b_formal_verification.z3_encoder import InvariantResult

logger = logging.getLogger(__name__)

_READ_ONLY_NAMES = frozenset({"readonly", "read_only", "viewer", "guest", "reader", "auditor"})
_MUTATING = ("create", "update", "delete", "write", "edit", "patch", "post", "put")
_OTHER = "\x00other"          # a member no table can contain: stands for every unseen name
_STAR = "*"

Table = Dict[str, Dict[str, List[str]]]
_COUNTER = itertools.count()


def _canonical_has_permission() -> str:
    """ast.dump of _has_permission as AetherOS generates it (single source of truth: the generator)."""
    from aether_os.phases.p04a_backend_codegen.helpers_permissions import _generate_permissions_service
    with tempfile.TemporaryDirectory() as tmp:
        _generate_permissions_service(Path(tmp), {"roles": ["X"], "permissions": {}})
        return _function_dump((Path(tmp) / "services" / "permissions.py").read_text(encoding="utf-8")) or ""


def _function_dump(source: str) -> Optional[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_has_permission":
            return ast.dump(node)
    return None


def _table(source: str) -> Optional[Table]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target == "PERMISSIONS" and value is not None:
            try:
                table = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return None
            ok = isinstance(table, dict) and all(
                isinstance(r, str) and isinstance(p, dict)
                and all(isinstance(res, str) and isinstance(acts, list) and all(isinstance(a, str) for a in acts)
                        for res, acts in p.items())
                for r, p in table.items())
            return table if ok else None
    return None


# ── the rule, as the generated _has_permission reads ─────────────────────────────────────────────────

def _allowed_py(table: Table, role: str, resource: str, action: str) -> bool:
    """_has_permission, evaluated (used by the exhaustive engine)."""
    role_perms = table.get(role, {})
    if _STAR in role_perms and (_STAR in role_perms[_STAR] or action in role_perms[_STAR]):
        return True
    resource_perms = role_perms.get(resource, role_perms.get(_STAR, []))
    return _STAR in resource_perms or action in resource_perms


def _domains(table: Table):
    roles = list(table) + [_OTHER]
    resources = sorted({res for p in table.values() for res in p} | {_STAR, _OTHER})
    actions = sorted({a for p in table.values() for acts in p.values() for a in acts} | set(_MUTATING)
                     | {_STAR, _OTHER})
    return roles, resources, actions


def _violations_exhaustive(table: Table, roles_to_check: List[str], actions_to_check: Optional[List[str]]) -> List[tuple]:
    """Counter-examples (role, resource, action) found by enumerating the finite domain."""
    _, resources, actions = _domains(table)
    acts = actions if actions_to_check is None else actions_to_check
    return [(r, res, a) for r, res, a in itertools.product(roles_to_check, resources, acts)
            if _allowed_py(table, r, res, a)]


def _violations_z3(table: Table, roles_to_check: List[str], actions_to_check: Optional[List[str]]):
    """The same question asked of Z3 over EnumSorts. Returns the model's counter-example or None."""
    import z3  # noqa: PLC0415

    roles, resources, actions = _domains(table)
    # z3 sort/constant names are global: a unique prefix per call lets the check run many times per process
    n = next(_COUNTER)
    Role, r_c = z3.EnumSort(f"Role{n}", [f"r{n}_{i}" for i in range(len(roles))])
    Res, res_c = z3.EnumSort(f"Res{n}", [f"s{n}_{i}" for i in range(len(resources))])
    Act, act_c = z3.EnumSort(f"Act{n}", [f"a{n}_{i}" for i in range(len(actions))])
    rc = dict(zip(roles, r_c))
    sc = dict(zip(resources, res_c))
    ac = dict(zip(actions, act_c))
    role, res, act = z3.Const(f"role{n}", Role), z3.Const(f"res{n}", Res), z3.Const(f"act{n}", Act)

    def in_list(lst: List[str]):
        if _STAR in lst:
            return z3.BoolVal(True)
        return z3.Or([act == ac[x] for x in lst] or [z3.BoolVal(False)])

    per_role = []
    for name, perms in table.items():
        star = perms.get(_STAR)
        wildcard = in_list(star) if star is not None else z3.BoolVal(False)
        # resource list: the resource's own, else the "*" resource's, else nothing
        fallback = in_list(perms.get(_STAR, []))
        own = fallback
        for rname, lst in perms.items():
            if rname != _STAR:
                own = z3.If(res == sc[rname], in_list(lst), own)
        per_role.append(z3.And(role == rc[name], z3.Or(wildcard, own)))
    allowed = z3.Or(per_role or [z3.BoolVal(False)])    # a role outside the table matches no clause

    s = z3.Solver()
    s.add(z3.Or([role == rc[r] for r in roles_to_check] or [z3.BoolVal(False)]))
    if actions_to_check is not None:
        s.add(z3.Or([act == ac[a] for a in actions_to_check]))
    s.add(allowed)
    if s.check() == z3.sat:
        m = s.model()
        pick = lambda c, d: next(k for k, v in d.items() if m.eval(c, model_completion=True).eq(v))  # noqa: E731
        return (pick(role, rc), pick(res, sc), pick(act, ac))
    return None


def _prove(table: Table, roles_to_check: List[str], actions_to_check: Optional[List[str]]):
    """(counter_example_or_None, engine description, ms)."""
    t0 = time.monotonic()
    try:
        import z3  # noqa: PLC0415,F401
        cex = _violations_z3(table, roles_to_check, actions_to_check)
        engine = "Z3 UNSAT over EnumSorts that include an 'other' role/resource/action"
    except ImportError:
        found = _violations_exhaustive(table, roles_to_check, actions_to_check)
        cex = found[0] if found else None
        engine = "exhaustive enumeration of the finite domain (roles, resources, actions + an 'other' member)"
    return cex, engine, int((time.monotonic() - t0) * 1000)


def check_permission_rule(source: str, route_name: str = "services/permissions.py") -> List[InvariantResult]:
    """INV-008 and INV-009 for one generated permissions module (its source text)."""
    names = {"INV-008": "Permission rule: unknown roles are denied everything",
             "INV-009": "Permission rule: read-only roles cannot create, update or delete"}

    def unver(why: str) -> List[InvariantResult]:
        return [InvariantResult(i, n, route_name, "UNVERIFIABLE", why, confidence=0.0) for i, n in names.items()]

    table = _table(source)
    if table is None:
        return unver("PERMISSIONS is not a literal role -> resource -> actions table")
    if _function_dump(source) != _canonical_has_permission():
        return unver("_has_permission differs from the rule AetherOS models: the proof would be about another rule")

    out: List[InvariantResult] = []
    # INV-008: a role that is not in the table
    cex, engine, ms = _prove(table, [_OTHER], None)
    out.append(_result("INV-008", names["INV-008"], route_name, cex, engine, ms,
                       "a role missing from PERMISSIONS is allowed {cex}", 0.95))
    # INV-009: read-only roles, mutating actions (and the wildcard action)
    ro = [r for r in table if r.lower().replace("-", "_").replace(" ", "_") in _READ_ONLY_NAMES]
    if not ro:
        out.append(InvariantResult("INV-009", names["INV-009"], route_name, "N/A",
                                   "No read-only role (readonly/viewer/guest/...) in the table", confidence=1.0))
    else:
        cex, engine, ms = _prove(table, ro, list(_MUTATING) + [_STAR, _OTHER])
        out.append(_result("INV-009", names["INV-009"], route_name, cex, engine, ms,
                           "read-only role is allowed {cex}", 0.95))
    return out


def _result(inv: str, name: str, route: str, cex, engine: str, ms: int, template: str, conf: float) -> InvariantResult:
    if cex is None:
        return InvariantResult(inv, name, route, "VERIFIED", f"{engine}: no (role, resource, action) is allowed",
                               solver_time_ms=ms, confidence=conf)
    shown = tuple("<any other>" if x == _OTHER else x for x in cex)
    return InvariantResult(inv, name, route, "VIOLATED", f"{engine}: counter-example found",
                           violation_detail=template.format(cex=f"(role, resource, action) = {shown}"),
                           solver_time_ms=ms, confidence=conf)


def check_project_permissions(project_dir: Path) -> List[InvariantResult]:
    """Find services/permissions.py under the run directory (no link followed) and check it.
    A project without one has no ABAC rule to prove: no result."""
    root = require_project_root(project_dir)
    results: List[InvariantResult] = []
    for rel in safe_fs.walk_files(root, skip_dirs=("__pycache__", "node_modules", ".venv", ".git")):
        if rel.name == "permissions.py" and rel.parent.name == "services":
            source = safe_fs.read_text_or_none(root, relative_to_root(root, root / rel))
            if source is not None:
                results.extend(check_permission_rule(source, route_name=rel.as_posix()))
    return results
