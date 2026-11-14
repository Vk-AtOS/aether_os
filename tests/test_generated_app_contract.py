"""KAN-169 acceptance: five sample apps (saas, crm, hrm, healthcare, fintech) are generated with the real generators.
Each must: start its backend, pass the import check, give a frontend the TypeScript compiler accepts (syntax and
undefined names) with every import resolved, and the frontend's calls must match the backend's route table
(method + path), including foreign-key dropdown endpoints. No model, no npm, no network."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from aether_os.tests.test_p04a_generated_backend import generate
from aether_os.tests.test_p04a_generated_hardening import run_script
from aether_os.tests.test_p05_generated_frontend import build_frontend, unresolved_imports
from aether_os.tests.test_p05_generated_frontend_hardening import sources, tsc_syntax_errors

DOMAINS = ["saas", "crm", "hrm", "healthcare", "fintech"]
_CALL = re.compile(r"""\b(?:apiClient|api)\s*\.\s*(get|post|put|patch|delete)\s*(?:<[^()]*?>)?\s*\(\s*(['"`])([^'"`]+)\2""")


def frontend_calls(root: Path):
    """(METHOD, path) of every apiClient call with a literal path, plus the CRUD helpers' endpoints in api.ts, with
    the client's /api prefix added and template parameters turned into {id}."""
    prefix = re.search(r"const API_PREFIX = '([^']*)'", (root / "src" / "lib" / "api.ts").read_text()).group(1)
    found = set()
    for f, text in sources(root / "src"):
        if f.suffix not in (".ts", ".tsx"):
            continue
        for m in _CALL.finditer(text):
            found.add((m.group(1).upper(), prefix + re.sub(r"\$\{[^}]*\}", "{id}", m.group(3))))
        for ep in re.findall(r"fkEndpoint:\s*'([^']+)'", text):
            found.add(("GET", prefix + re.sub(r"^/api(?=/)", "", ep)))     # the modal strips a leading /api
    return {(m, p.split("?")[0].rstrip("/")) for m, p in found}


def backend_routes(app):
    out = run_script(app, r'''
import main
out["routes"] = [[sorted(r.methods or []), r.path] for r in main.app.routes if hasattr(r, "methods")]
''')["routes"]
    return {(m, re.sub(r"\{[^}]*\}", "{id}", p).rstrip("/")) for methods, p in out for m in methods}


@pytest.mark.parametrize("domain", DOMAINS)
def test_generated_app_backend_starts_and_frontend_matches_it(tmp_path, monkeypatch, domain):
    monkeypatch.setenv("ENVIRONMENT", "test")
    (tmp_path / "be").mkdir()
    result, app = generate(tmp_path / "be", domain=domain, use_ir=True, monkeypatch=monkeypatch)
    # backend starts (the routes were read from the started app), imports are clean
    assert result.metadata["smoke_test"]["check_imports"] == []
    routes = backend_routes(app)
    assert ("GET", "/health") in routes and ("POST", "/api/auth/login") in routes

    root = build_frontend(tmp_path / "fe", domain, monkeypatch,
                          extra={"domain_ir_path": str(tmp_path / "be" / "domain_ir.json")})
    assert unresolved_imports(root) == []
    assert tsc_syntax_errors(root) == []

    calls = frontend_calls(root)
    assert len(calls) >= 8 and ("GET", "/api/stats") in calls, f"the call parser is broken: {sorted(calls)}"
    missing = sorted(c for c in calls if c not in routes and not c[1].startswith("/api/realtime"))
    assert missing == [], f"frontend calls the backend does not serve: {missing}"
