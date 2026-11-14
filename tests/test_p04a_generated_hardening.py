"""KAN-169 follow-up: generated-backend hardening. Each test builds the app with the real generators and,
where behaviour matters, starts it in a subprocess (see test_p04a_generated_backend for the method)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from aether_os.tests.test_p04a_generated_backend import IR, generate, run_app

MODS = ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx")


def run_script(app, body: str, env_extra=None, timeout=120):
    """Run `body` inside the generated app (cwd = app dir, src on sys.path, SQLite). It sets `out` (a dict)."""
    for m in MODS:
        pytest.importorskip(m)
    head = ("import json, os, sys\napp_dir = sys.argv[1]; os.chdir(app_dir); sys.path.insert(0, os.path.join(app_dir, 'src'))\n"
            "os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + os.path.join(app_dir, 't.db')\nout = {}\n")
    env = {**os.environ, "ENVIRONMENT": "test", "ADMIN_PASSWORD": "Test-only-Admin-9z", **(env_extra or {})}
    p = subprocess.run([sys.executable, "-c", head + body + "\nprint('RESULT ' + json.dumps(out))", str(app)],
                       capture_output=True, text=True, env=env, timeout=timeout, cwd=str(app))
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, p.stdout[-800:] + p.stderr[-1500:]
    return json.loads(line[7:])


@pytest.mark.parametrize("use_ir", [True, False], ids=["ir", "fallback"])
def test_no_permissions_means_the_default_role_model_not_allow_all(tmp_path, monkeypatch, use_ir):
    # Decision D1: an IR / permission model with NO permissions let every signed-in user do everything (a fresh
    # registrant deleted rows). Now: admin everything, member/user read+create+update, delete admin only.
    monkeypatch.setenv("ENVIRONMENT", "test")
    _, app = generate(tmp_path, domain="crm", use_ir=use_ir, monkeypatch=monkeypatch, ir_override={**IR, "permissions": []})
    r = run_app(app, "customers,invoices")
    for ent in ("customers", "invoices"):
        assert r[f"user_list_{ent}"] == 200 and r[f"user_create_{ent}"] == 201, (ent, r)
        assert r[f"user_delete_{ent}"] == 403 and r[f"admin_delete_{ent}"] == 204, (ent, r)
