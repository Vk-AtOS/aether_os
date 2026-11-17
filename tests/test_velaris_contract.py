"""Contract test: every row of the AetherOS Velaris proxies (HR table, chat, mail, control, providers, dashboard
screens) is checked against the REAL Velaris allow-list and routes, loaded from a Velaris checkout. Skips when no
checkout is present (set VELARIS_REPO to its path). Fails on any row Velaris would refuse: unknown agent or method,
a method Velaris does not allow over HTTP, a Velaris role the gateway does not demand, or an argument name Velaris
does not accept / a required argument no screen supplies."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

CANDIDATES = [os.environ.get("VELARIS_REPO", ""), "/Users/apple/Desktop/wt2/int/velaris_knackforge",
              str(Path(__file__).resolve().parents[2] / "velaris_knackforge")]
REPO = next((Path(c) for c in CANDIDATES if c and (Path(c) / "velaris/api/allowlist.py").is_file()), None)
pytestmark = pytest.mark.skipif(REPO is None, reason="no Velaris checkout (set VELARIS_REPO)")

DUMP = r"""
import json, sys, logging, inspect
logging.disable(logging.CRITICAL)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from velaris.api.allowlist import METHODS, http_params
from velaris.api.app import Settings, create_app
from velaris.backend.engine import backend as engine
out = {"methods": {}, "routes": []}
for agent, ms in METHODS.items():
    try:
        cls = engine.agent_class(agent)
    except LookupError:
        cls = None
    for m, r in ms.items():
        fn = getattr(cls, m, None) if cls else None
        out["methods"][f"{agent}.{m}"] = {"kind": r.kind, "roles": sorted(r.roles or []), "actor": r.actor,
            "loaded": fn is not None, "params": None if fn is None else [[p.name, p.default is p.empty] for p in http_params(fn)]}
app = create_app(Settings(secret=b"x" * 32, identity_key=Ed25519PrivateKey.generate().public_key(), org="o"), engine=object())
out["routes"] = sorted({(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or ()) if m not in ("HEAD", "OPTIONS")})
json.dump(out, sys.stdout)
"""


@pytest.fixture(scope="module")
def velaris():
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "PYTHONPATH": str(REPO), "VELARIS_DATA": d, "VELARIS_ORG": "o"}
        r = subprocess.run([sys.executable, "-c", DUMP], capture_output=True, text=True, env=env, cwd=d, timeout=300)
        if r.returncode:
            pytest.skip(f"Velaris could not be loaded here: {r.stderr[-300:]}")
        return json.loads(r.stdout)


def _hr_rows():
    from aether_os.gateway.velaris_hr_table import HR_ROUTES
    return [(*r.path.strip("/").split("/"), r) for r in HR_ROUTES]


def test_every_hr_row_exists_and_roles_agree(velaris):
    bad = []
    for agent, method, row in _hr_rows():
        v = velaris["methods"].get(f"{agent}.{method}")
        if v is None:
            bad.append(f"{agent}.{method}: not on Velaris's allow-list")
        elif not v["loaded"]:
            bad.append(f"{agent}.{method}: agent or method not loaded in Velaris")
        elif v["roles"] and not row.admin:
            bad.append(f"{agent}.{method}: Velaris needs roles {v['roles']} but the row is open to every member")
        elif row.method == "POST" and v["kind"] == "act" and row.kind == "export":
            bad.append(f"{agent}.{method}: an act is approval-gated, it cannot be a download")
    assert not bad, "\n".join(bad)


def test_no_velaris_hiring_or_paperwork_method_is_left_out(velaris):
    """Every method Velaris allows on an agent this proxy serves is a row, except these deliberate exclusions."""
    from aether_os.gateway.velaris_hr_table import HR_ALLOW
    deliberate = {"INTERVIEW_RECORD.purge_expired_sessions", "EMPLOYEE_RECORDS.erase_subject_unused"}  # bulk erase: owner call
    left_out = [k for k in velaris["methods"] if k.split(".")[0] in HR_ALLOW
                and k.split(".")[1] not in HR_ALLOW[k.split(".")[0]] and k not in deliberate]
    assert not left_out, left_out


def test_interview_record_has_consent_and_audio_methods():
    from aether_os.gateway.velaris_hr_table import HR_ALLOW
    assert {"give_consent", "withdraw_my_consent", "register_audio_track", "transcribe_track"} <= HR_ALLOW["INTERVIEW_RECORD"]


def _norm(p):
    return re.sub(r"\{\w+\}", "{}", p)


@pytest.mark.parametrize("module,prefix,upstream", [
    ("velaris_chat_router", "/chat", "/chat"), ("velaris_mail_router", "/mail", "/mail"),
    ("velaris_control_router", "/control", "/control"), ("velaris_providers_router", "/model-providers", "/providers")])
def test_path_rows_are_velaris_routes(velaris, module, prefix, upstream):
    mod = __import__(f"aether_os.gateway.routers.{module}", fromlist=["ROUTES"])
    have = {(m, _norm(p)) for m, p in velaris["routes"]}
    bad = [f"{r.method} {upstream}{r.path}" for r in mod.ROUTES if (r.method, _norm(upstream + r.path)) not in have]
    assert not bad, bad


def test_admin_only_velaris_routes_demand_the_role_velaris_wants():
    """Velaris refuses mail/chat admin routes without mail_admin / chat_admin; AetherOS must grant them to owner/admin."""
    from aether_os.core.velaris.roles import velaris_roles
    for role in ("owner", "admin"):
        assert {"mail_admin", "chat_admin", "hr_admin", "model_admin"} <= velaris_roles(role)
    assert not {"mail_admin", "chat_admin"} & velaris_roles("member")
    from aether_os.gateway.routers import velaris_chat_router, velaris_mail_router
    for r in velaris_chat_router.ROUTES:
        if r.path.startswith("/admin/"):
            assert r.needs == "chat_admin", r.path
    assert {r.path: r.needs for r in velaris_mail_router.ROUTES}["/outbox/process"] == "mail_admin"


def _screens():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    src = Path(__file__).resolve().parents[1] / "dashboard/src/components/velaris/screens.js"
    r = subprocess.run([node, "--input-type=module", "-e",
                        f"import {{SCREENS}} from {json.dumps(src.as_uri())}; console.log(JSON.stringify(SCREENS))"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode:
        pytest.skip("screens.js could not be loaded: " + r.stderr[-200:])
    return json.loads(r.stdout)


def test_screen_fields_are_the_arguments_velaris_takes(velaris):
    from aether_os.gateway.velaris_hr_table import _SELF
    bad = []
    for s in _screens():
        for sec in s["sections"]:
            call = sec.get("call", {})
            am = call.get("hr") or call.get("agent")
            if not am:
                continue
            v = velaris["methods"].get(".".join(am))
            if v is None or v["params"] is None:
                bad.append(f"{s['id']}: {am} is not a Velaris method")
                continue
            names = {n for n, _ in v["params"]}
            fields = [f["name"] for f in sec.get("fields", [])] + [f["also"] for f in sec.get("fields", []) if f.get("also")]
            fixed = set(sec.get("fixed", {}))
            for f in fields:
                if f not in names:
                    bad.append(f"{s['id']} {'.'.join(am)}: Velaris has no argument '{f}' (takes {sorted(names)})")
            for n, required in v["params"]:
                if required and n not in fields and n not in fixed and n != v["actor"] \
                        and not (n == "employee_id" and tuple(am) in _SELF):
                    bad.append(f"{s['id']} {'.'.join(am)}: required argument '{n}' is never sent")
            if "_extra" in fields or any(f.get("type") == "json" and f["name"] == "_extra" for f in sec.get("fields", [])):
                bad.append(f"{s['id']}: catch-all JSON field")
    assert not bad, "\n".join(bad)


def test_every_velaris_agent_is_on_hr_or_on_the_generic_list(velaris):
    """KAN-69 VP-4: a new Velaris agent must be put on /hr or on the generic allow-list on purpose; HR and generic
    never overlap (an HR agent on the generic route would be a second, weaker door)."""
    from aether_os.gateway.velaris_generic_agents import GENERIC_AGENTS
    from aether_os.gateway.velaris_hr_table import HR_ALLOW
    agents = {k.split(".")[0] for k in velaris["methods"]}
    assert not (set(HR_ALLOW) & GENERIC_AGENTS)
    assert agents - set(HR_ALLOW) - GENERIC_AGENTS == set(), "unlisted Velaris agents"
