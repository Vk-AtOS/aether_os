"""What a customer receives from p05 (KAN-168): the generated frontend is built with the real generators (no
model, no npm) and every import in it must resolve. npm is not run here, so this is the offline part of a
build: a relative import must name a file that exists and a package import must be declared in package.json.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from aether_os.phases.p05_frontend import task_agent

_IMPORT = re.compile(r"""(?:^|\n)\s*(?:import|export)\s+(?:[^'"\n;]*?\sfrom\s+)?['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)""")
_EXTS = (".ts", ".tsx", ".js", ".jsx", ".css", ".json")

ENTITIES = [
    {"table": "patients", "columns": ["id", "name", "email", "phone", "status", "created_at"]},
    {"table": "lead_contacts", "columns": ["id", "name", "category_id", "description", "status", "created_at"]},
    {"table": "categories", "columns": ["id", "name"]},
]


def build_frontend(tmp_path: Path, domain: str, monkeypatch) -> Path:
    monkeypatch.setenv("ENVIRONMENT", "test")

    async def no_screenshot(*a, **k):
        return False
    monkeypatch.setattr(task_agent, "take_preview_screenshot", no_screenshot)
    data = {"project_name": "Demo", "domain": domain, "architecture_json": {"database_schema": ENTITIES},
            "raw_input": "x", "autonomous_mode": True}
    pi = SimpleNamespace(input_data=data, domain=domain, project_id="p")
    result = asyncio.run(task_agent.run(pi, [], tmp_path / "p05_frontend"))
    assert result.success, result
    return Path(result.output_path)


def unresolved_imports(root: Path) -> list:
    pkg = json.loads((root / "package.json").read_text())
    declared = set(pkg.get("dependencies", {})) | set(pkg.get("devDependencies", {}))
    issues = []
    for f in sorted((root / "src").rglob("*")):
        if f.suffix not in (".ts", ".tsx", ".js", ".jsx"):
            continue
        for m in _IMPORT.finditer(f.read_text(errors="replace")):
            spec = m.group(1) or m.group(2)
            if spec.startswith(".") or spec.startswith("@/"):
                base = (f.parent / spec).resolve() if spec.startswith(".") else (root / "src" / spec[2:])
                found = [base] + [Path(str(base) + e) for e in _EXTS] + [base / ("index" + e) for e in _EXTS[:4]]
                if not any(c.is_file() for c in found):
                    issues.append(f"{f.relative_to(root)}: '{spec}' has no file")
            else:
                name = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
                if name not in declared and not name.startswith("node:"):
                    issues.append(f"{f.relative_to(root)}: package '{name}' is not in package.json")
    return sorted(set(issues))


@pytest.mark.parametrize("domain", ["saas", "healthcare", "crm", "fintech"])
def test_every_import_in_the_generated_frontend_resolves(tmp_path, monkeypatch, domain):
    # NotFoundPage imported react-router-dom (the app uses @tanstack/react-router and never declared it) and
    # every entity page imported Pagination, Skeleton and RoleGuard components that nothing wrote.
    root = build_frontend(tmp_path, domain, monkeypatch)
    assert unresolved_imports(root) == []
