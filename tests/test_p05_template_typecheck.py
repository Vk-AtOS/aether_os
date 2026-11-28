"""KAN-251: the generated frontend must type-check. `vite build` does not, so every build shipped ~10 TypeScript errors
(CrudModal keyof T, CustomerHome and Dashboard links to routes the router does not have, a CommandPalette importing
api clients that do not exist). Two different specs are generated with the real generators (no model) in both ways
p05 builds them (from the domain IR and from the architecture) and `tsc --noEmit` must report 0 errors.

The tsc test needs node/npm and the npm registry, so it runs when AETHER_TSC_E2E=1 (the nightly job sets it); the
route test below is offline and always runs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from aether_os.core.domain_ir import DomainIR, IREntity, IRField
from tests.test_p05_generated_frontend import build_frontend

F = IRField
SPECS = {
    "tracker": [
        IREntity("User", "users", [F("email", "email"), F("full_name", "string"), F("role", "enum", enum_values=["admin", "member"]),
                                   F("is_active", "boolean")]),
        IREntity("Project", "projects", [F("name", "string"), F("description", "text"),
                                         F("status", "enum", enum_values=["active", "archived"]), F("budget", "decimal")]),
        IREntity("Task", "tasks", [F("title", "string"), F("status", "enum", enum_values=["todo", "doing", "done"]),
                                   F("project_id", "fk", ref_entity="project"), F("assignee_id", "fk", ref_entity="user"),
                                   F("due_date", "date"), F("estimate", "integer")]),
    ],
    "bakery": [
        IREntity("MenuItem", "menu_items", [F("name", "string"), F("description", "text"), F("price", "decimal"),
                                            F("category", "enum", enum_values=["bread", "cake"]), F("available", "boolean")]),
        IREntity("ContactMessage", "contact_messages", [F("name", "string"), F("email", "email"), F("message", "text"),
                                                         F("sent_at", "datetime")]),
    ],
}


def _deps(root: Path) -> dict:
    pkg = json.loads((root / "package.json").read_text())
    return {"d": pkg.get("dependencies"), "dev": pkg.get("devDependencies")}


def _generate(tmp_path: Path, monkeypatch, spec: str, mode: str) -> Path:
    ents = SPECS[spec]
    arch = [{"table": e.table, "columns": ["id"] + [f.name for f in e.fields]} for e in ents]
    extra = {"architecture_json": {"database_schema": arch}}
    if mode == "ir":
        ir = DomainIR(domain="saas", app_name=spec)
        ir.entities = ents
        tmp_path.mkdir(parents=True, exist_ok=True)
        ir.save(tmp_path / "domain_ir.json")
        extra["domain_ir_path"] = str(tmp_path / "domain_ir.json")
    return build_frontend(tmp_path / mode, "saas", monkeypatch, project_name=spec, extra=extra)


@pytest.mark.parametrize("spec", sorted(SPECS))
@pytest.mark.parametrize("mode", ["ir", "arch"])
def test_customer_and_dashboard_links_name_registered_routes(tmp_path, monkeypatch, spec, mode):
    # CustomerHome linked "/projects" and Dashboard "/projects" while the dual-portal router only has "/admin/projects"
    # (customer routes exist for browsable entities only): a typed <Link> to an unregistered path does not compile.
    root = _generate(tmp_path, monkeypatch, spec, mode)
    paths = set(re.findall(r"path: '([^']+)'", (root / "src" / "App.tsx").read_text()))
    for rel in ("src/pages/CustomerHome.tsx", "src/pages/Dashboard.tsx"):
        f = root / rel
        if not f.is_file():
            continue
        for link in re.findall(r"""<Link[^>]*?\bto=['"](/[^'"]*)['"]""", f.read_text()):
            assert link in paths, f"{rel} links to {link}, App.tsx registers {sorted(paths)}"


@pytest.mark.skipif(not (os.environ.get("AETHER_TSC_E2E") and shutil.which("npm")),
                    reason="set AETHER_TSC_E2E=1 (needs node 20, npm and the registry)")
def test_generated_frontend_type_checks_with_zero_errors(tmp_path, monkeypatch):
    roots = {(s, m): _generate(tmp_path / s, monkeypatch, s, m) for s in SPECS for m in ("ir", "arch")}
    first = next(iter(roots.values()))
    subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=first, check=True, capture_output=True, timeout=900)
    failures = {}
    for key, root in roots.items():
        if root != first:
            assert _deps(root) == _deps(first)       # one install serves all: copied, not reinstalled
            shutil.copytree(first / "node_modules", root / "node_modules", symlinks=True)
        out = subprocess.run(["npx", "tsc", "--noEmit"], cwd=root, capture_output=True, text=True, timeout=600)
        if out.returncode != 0:
            failures["/".join(key)] = out.stdout.splitlines()[:12]
    assert failures == {}
