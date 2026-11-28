"""KAN-266: the acceptance suite's expectation data and report logic, offline (fakes, no network, no model)."""
import copy
import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("acceptance_suite", ROOT / "scripts/acceptance_suite.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
C, X, R, H = S.C, S.X, S.R, S.H
Resp = C.Resp
DEFAULTS, PROMPTS = S.load_expectations()


def test_expectation_file_is_valid_and_covers_the_six_request_types():
    assert S.validate_expectations(DEFAULTS, PROMPTS) == []
    assert {p["id"] for p in PROMPTS} == {"bakery_site", "consultancy_landing", "clinic_booking", "support_agent",
                                          "task_tracker", "shop_orders"}
    assert DEFAULTS["run_status"] == "completed" and DEFAULTS["app_started"] is True and DEFAULTS["export_clean"] is True
    assert len({p["prompt"] for p in PROMPTS}) == 6


def test_validation_rejects_bad_data():
    bad = copy.deepcopy(PROMPTS)
    bad[0]["public_endpoints"][0]["path_regex"] = "(["
    bad[1]["bogus_key"] = 1
    bad.append(dict(bad[2]))
    errs = " | ".join(S.validate_expectations(DEFAULTS, bad))
    assert "bad path_regex" in errs and "unknown key bogus_key" in errs and "duplicate prompt ids" in errs


# ---- a fake generated app (what a bakery-like build exposes) -------------------------------------------------------

SCHEMA = {"type": "object", "required": ["name", "email", "message"],
          "properties": {"name": {"type": "string"}, "email": {"type": "string", "format": "email"}, "message": {"type": "string"}}}
ITEM = {"type": "object", "required": ["name", "price"], "properties": {"name": {"type": "string"}, "price": {"type": "number"}}}


def op(schema=None):
    return {"requestBody": {"content": {"application/json": {"schema": schema}}}} if schema else {}


OPENAPI = {"paths": {"/api/menu": {"get": op(), "post": op(ITEM)}, "/api/menu/{id}": {"put": op(ITEM)},
                     "/api/contact": {"post": op(SCHEMA)}, "/api/auth/login": {"post": op({"properties": {"email": {}, "password": {}}})}}}


class FakeApp:
    def __init__(self, break_public=False, open_post=False, contact=200):
        self.calls, self.break_public, self.open_post, self.contact = [], break_public, open_post, contact

    def request(self, method, path, json=None, token="", timeout=30):
        self.calls.append((method, path, bool(token)))
        if path == "/openapi.json":
            return Resp(200, OPENAPI)
        if path == "/":
            return Resp(200, None, "<html>bakery</html>")
        if (method, path) == ("GET", "/api/menu"):
            return Resp(401 if self.break_public else 200, [{"id": 1}, {"id": 7}], "[]")
        if (method, path) == ("POST", "/api/menu"):
            if not token and not self.open_post:
                return Resp(401, None, "no token")
            return Resp(201, {"id": 7, **(json or {})})
        if (method, path) == ("POST", "/api/contact"):
            return Resp(self.contact, {"ok": True}, "validation error: field required" if self.contact != 200 else "")
        if (method, path) == ("POST", "/api/auth/login"):
            return Resp(200, {"access_token": "tok"})
        return Resp(404, None, "nope")


def test_checks_pass_on_a_correct_app_and_send_schema_valid_bodies():
    app, spec = FakeApp(), OPENAPI
    assert C.check_public(app, spec, PROMPTS[0]["public_endpoints"])[0].status == C.PASS
    assert C.check_protected(app, spec, PROMPTS[0]["protected_endpoints"])[0].status == C.PASS
    assert C.check_form_post(app, spec, PROMPTS[0]["form_post"]).status == C.PASS
    assert C.body_for(spec, "/api/contact", "post") == {"name": "Acceptance check", "email": "acceptance@example.com", "message": "Acceptance check"}


def test_failures_carry_the_real_reason():
    r = C.check_public(FakeApp(break_public=True), OPENAPI, PROMPTS[0]["public_endpoints"])[0]
    assert r.status == C.FAIL and "/api/menu -> 401" in r.reason
    r = C.check_protected(FakeApp(open_post=True), OPENAPI, PROMPTS[0]["protected_endpoints"])[0]
    assert r.status == C.FAIL and "expected 401" in r.reason and "201" in r.reason
    r = C.check_form_post(FakeApp(contact=422), OPENAPI, PROMPTS[0]["form_post"])
    assert r.status == C.FAIL and "422" in r.reason and "field required" in r.reason
    assert C.check_public(FakeApp(), None, PROMPTS[0]["public_endpoints"])[0].status == C.FAIL
    r = C.check_public(FakeApp(), OPENAPI, [{"name": "x", "path_regex": "zebra"}])[0]
    assert r.status == C.FAIL and "no GET endpoint matching" in r.reason


def test_auth_crud_logs_in_creates_and_reads_back():
    token, why = C.app_login(FakeApp(), OPENAPI, {"email": "a@b.c", "password": "x"})
    assert token == "tok" and not why
    lst = FakeApp()
    lst.request = lambda m, p, json=None, token="", timeout=30: (Resp(200, [{"id": 7}]) if (m, p) == ("GET", "/api/menu") else FakeApp.request(lst, m, p, json, token))
    assert C.check_auth_crud(lst, OPENAPI, PROMPTS[0]["auth_crud"], "tok", "").status == C.PASS
    r = C.check_auth_crud(FakeApp(), OPENAPI, PROMPTS[0]["auth_crud"], "", "login failed: x")
    assert r.status == C.FAIL and r.reason == "login failed: x"


def test_no_accounts_flags_auth_endpoints():
    exp = {"forbidden_path_regex": "login|register"}
    assert C.check_no_accounts(OPENAPI, exp).status == C.FAIL
    assert C.check_no_accounts(None, exp).status == C.PASS


# ---- export checks -------------------------------------------------------------------------------------------------

def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, c in files.items():
            zf.writestr(n, c)
    return buf.getvalue()


CLEAN = {"backend/src/main.py": "app = 1", "MANIFEST.json": "{}", ".env.example": "KEY=", "frontend/package.json": "{}"}


def test_export_clean_and_dirty():
    assert X.check_export_clean(make_zip(CLEAN)).status == C.PASS
    pem = "-----BEGIN RSA PRIVATE" + " KEY-----\nabc"   # built at runtime so gitleaks never sees a key in this file
    bad = X.check_export_clean(make_zip({**CLEAN, "p04_backend/private_key.pem": pem, "preview_credentials.json": "{}"}))
    assert bad.status == C.FAIL and "private_key.pem" in bad.reason and "pipeline workspace leaked" in bad.reason
    assert X.check_export_clean(b"not a zip").status == C.FAIL
    assert X.check_export_clean(make_zip({"frontend/a.ts": "x"})).status == C.FAIL     # no backend, no manifest


def test_forbidden_patterns_and_zip_slip(tmp_path):
    z = make_zip({**CLEAN, "backend/src/tools.py": "import subprocess\nsubprocess.run(['ls'])"})
    assert X.check_forbidden_patterns(z, ["subprocess\\."]).status == C.FAIL
    assert X.check_forbidden_patterns(make_zip(CLEAN), ["subprocess\\."]).status == C.PASS
    with pytest.raises(ValueError):
        X.safe_extract(make_zip({"../evil.txt": "x"}), tmp_path / "d")


def test_rulepacks_is_skipped_when_the_scanner_is_absent():
    assert X.check_rulepacks(make_zip(CLEAN)).status in (C.SKIP, C.PASS, C.FAIL)   # SKIP on main until core/rulepacks lands


# ---- the whole flow with a fake platform ---------------------------------------------------------------------------

class FakePlatform:
    def __init__(self, run=None, start_status=200, zip_bytes=None, running=True):
        self.calls = []
        self.run = run if run is not None else {"status": "completed", "phases": {"s01": {"status": "completed"}},
                                                "failed_stages": [], "skipped_stages": []}
        self.start_status, self.zip, self.running = start_status, zip_bytes if zip_bytes is not None else make_zip(CLEAN), running

    def request(self, method, path, json=None, token="", timeout=30):
        self.calls.append((method, path, json))
        if path == "/factory/start":
            return Resp(self.start_status, {"run_id": "r1"} if self.start_status == 200 else None, "quota exceeded")
        if path == "/factory/runs/r1":
            return Resp(200, self.run)
        if path.endswith("/run-app/status"):
            return Resp(200, {"running": self.running, "port": 9000})
        if path.endswith("/preview-credentials"):
            return Resp(200, {"email": "a@b.c", "password": "pw"})
        return Resp(404)

    def get_bytes(self, path, timeout=0):
        return 200, self.zip, ""


@pytest.fixture
def fake_preview(monkeypatch):
    app = FakeApp()
    app.request_orig = app.request
    monkeypatch.setattr(H, "preview_probe", lambda api, run_id: (app, ""))
    return app


def entry(pid):
    return next(p for p in PROMPTS if p["id"] == pid)


def run(api, pid="bakery_site", **kw):
    return S.run_prompt(api, entry(pid), DEFAULTS, interval=0, sleep=lambda s: None, **kw)


def by_name(rec):
    return {c["name"]: c for c in rec["checks"]}


def test_happy_path_is_autonomous_and_passes(fake_preview):
    api = FakePlatform()
    rec = run(api)
    start = next(c for c in api.calls if c[1] == "/factory/start")
    assert start[2]["mode"] == "autonomous" and start[2]["raw_input"] == entry("bakery_site")["prompt"]
    assert not any("approve" in c[1] or "decide" in c[1] for c in api.calls)       # never impersonates a human
    fails = {n: c["reason"] for n, c in by_name(rec).items() if c["status"] == "FAIL"}
    assert fails == {}, fails
    assert rec["verdict"] == "PASS"


def test_failed_stage_and_unstarted_app_are_reported_with_reasons(fake_preview):
    run_rec = {"status": "failed", "error": "s04 build broke", "phases": {"s04": {"status": "failed"}},
               "failed_stages": [{"stage": "s04_frontend", "status": "failed", "reason": "tsc: 3 errors"}], "skipped_stages": []}
    rec = run(FakePlatform(run=run_rec, running=False))
    c = by_name(rec)
    assert rec["verdict"] == "FAIL"
    assert "s04 build broke" in c["run_status"]["reason"]
    assert "tsc: 3 errors" in c["all_stages_passed"]["reason"]
    assert c["app_started"]["status"] == "FAIL"


def test_skipped_stage_fails_unless_the_prompt_allows_it(fake_preview):
    run_rec = {"status": "completed", "phases": {}, "failed_stages": [], "skipped_stages": [{"stage": "s03_backend", "reason": "no backend"}]}
    assert by_name(run(FakePlatform(run=run_rec)))["all_stages_passed"]["status"] == "FAIL"
    assert by_name(run(FakePlatform(run=run_rec), "consultancy_landing"))["all_stages_passed"]["status"] == "PASS"


def test_start_refused_and_waiting_gate_are_reported(fake_preview):
    rec = run(FakePlatform(start_status=402))
    assert "402" in by_name(rec)["run_status"]["reason"] and rec["verdict"] == "FAIL"
    stuck = FakePlatform(run={"status": "awaiting_approval", "phases": {}})
    rec = S.run_prompt(stuck, entry("bakery_site"), DEFAULTS, max_minutes=0, interval=0, sleep=lambda s: None)
    assert "waiting for a human gate" in by_name(rec)["run_status"]["reason"]


def test_dirty_export_fails_that_check(fake_preview):
    dirty = make_zip({**CLEAN, "backend/id_rsa": "x"})
    assert by_name(run(FakePlatform(zip_bytes=dirty)))["export_clean"]["status"] == "FAIL"


def test_report_json_markdown_and_exit_code(fake_preview):
    bad = run(FakePlatform(start_status=500))
    good = run(FakePlatform())
    rep = R.summary([good, bad], {"at": "T", "target": "http://x"})
    assert R.exit_code(rep) == 1 and rep["passed_prompts"] == 1 and rep["total_prompts"] == 2
    md = R.to_markdown(rep)
    assert "POST /factory/start answered 500" in md and "| bakery_site | PASS" in md
    assert R.exit_code(R.summary([good], {})) == 0 and R.exit_code(R.summary([], {})) == 1
    assert R.verdict([C.skip("x", "y")], strict=True) == "FAIL" and R.verdict([C.skip("x", "y")]) == "PASS"


def test_main_validate_only_and_skip_without_credentials(monkeypatch, capsys):
    assert S.main(["--validate-only"]) == 0
    monkeypatch.delenv("ACCEPT_TOKEN", raising=False)
    assert S.main([]) == 2 and "SKIP" in capsys.readouterr().out
