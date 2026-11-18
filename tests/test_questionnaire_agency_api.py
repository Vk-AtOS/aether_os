"""KAN-152: the agency-side questionnaire routes: member+ only (links are bearer capabilities), tenant scoped,
stage validated, the share link uses the public origin, and the respondent's submit shows up in the list."""
import pytest

STAGE = "s01_intake"


def _run(gw, org, rid):
    gw.sql("INSERT INTO runs (id, org_id, command, status, started_at, cost, run_version) "
           "VALUES (?, ?, 'x', 'running', 0, 0, 1)", (rid, org.org_id))


def test_send_list_submit_roundtrip_with_public_origin_link(gw, monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    org = gw.register("qsend")
    _run(gw, org, "qrun-1")
    r = gw.client.post("/runs/qrun-1/questionnaire/send", headers=org.auth,
                       json={"stage_id": STAGE, "respondent_email": "c@client.com", "respondent_name": "C"})
    assert r.status_code == 200, r.text
    url = r.json()["share_url"]
    assert url.startswith("https://app.example.com/api/questionnaire/") and r.json()["email_sent"] is False
    token = url.rsplit("/", 1)[1]
    listed = gw.client.get("/runs/qrun-1/questionnaires", headers=org.auth).json()
    assert [(q["status"], q["respondent_email"]) for q in listed] == [("sent", "c@client.com")]
    # The respondent answers through the public link; the agency list then shows completed.
    questions = gw.client.get("/questionnaire-stages", headers=org.auth).json()
    qs = next(s for s in questions if s["id"] == STAGE)["questions"]
    answers = {q["id"]: "x" for q in qs if q.get("required")}
    assert gw.client.post(f"/questionnaire/{token}/submit", json={"answers": answers}).status_code == 200
    assert gw.client.get("/runs/qrun-1/questionnaires", headers=org.auth).json()[0]["status"] == "completed"


def test_viewer_refused_everywhere_and_other_org_cannot_touch_the_run(gw):
    org, other = gw.register("qrole"), gw.register("qother")
    _run(gw, org, "qrun-2")
    viewer = gw.user_with_role("viewer", org.org_id)
    body = {"stage_id": STAGE, "respondent_email": "c@client.com"}
    assert gw.client.get("/runs/qrun-2/questionnaires", headers=viewer.auth).status_code == 403
    assert gw.client.post("/runs/qrun-2/questionnaire/send", headers=viewer.auth, json=body).status_code == 403
    assert gw.client.post("/runs/qrun-2/questionnaire/fill", headers=viewer.auth, json={"stage_id": STAGE, "answers": {}}).status_code == 403
    assert gw.client.get("/questionnaire-stages", headers=viewer.auth).status_code == 403
    assert gw.client.get("/runs/qrun-2/questionnaires", headers=other.auth).status_code == 403
    assert gw.client.post("/runs/qrun-2/questionnaire/send", headers=other.auth, json=body).status_code == 403


@pytest.mark.parametrize("body", [
    {"stage_id": "nope", "respondent_email": "c@client.com"},
    {"stage_id": STAGE, "respondent_email": "not-an-email"},
    {"stage_id": "", "respondent_email": "c@client.com"},
])
def test_send_validates_stage_and_email(gw, body):
    org = gw.register("qvalid")
    rid = f"qrun-v-{org.org_id[:8]}"
    _run(gw, org, rid)
    assert gw.client.post(f"/runs/{rid}/questionnaire/send", headers=org.auth, json=body).status_code == 422


def test_fill_on_behalf_stores_answers_and_requires_the_required_ones(gw):
    org = gw.register("qfill")
    _run(gw, org, "qrun-4")
    assert gw.client.post("/runs/qrun-4/questionnaire/fill", headers=org.auth, json={"stage_id": STAGE, "answers": {}}).status_code == 422
    stages = gw.client.get("/questionnaire-stages", headers=org.auth).json()
    qs = next(s for s in stages if s["id"] == STAGE)["questions"]
    ok = gw.client.post("/runs/qrun-4/questionnaire/fill", headers=org.auth,
                        json={"stage_id": STAGE, "answers": {q["id"]: "v" for q in qs if q.get("required")}})
    assert ok.status_code == 200, ok.text
    assert gw.client.get("/runs/qrun-4/questionnaires", headers=org.auth).json()[0]["status"] == "completed"


def test_share_token_is_stored_hashed_and_never_logged_or_listed(gw, monkeypatch, caplog):
    """KAN-69 F18: the database holds a hash, the log holds no token, the list returns no link, and a leaked
    hash does not open the link. A stored value is never itself a credential: rows that held the plain token
    were hashed by the hash_legacy_plaintext_tokens migration (KAN-131), so a plain value left in the column
    opens nothing."""
    import hashlib
    import logging
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    org = gw.register("qhash")
    _run(gw, org, "qrun-h")
    with caplog.at_level(logging.INFO):
        r = gw.client.post("/runs/qrun-h/questionnaire/send", headers=org.auth,
                           json={"stage_id": STAGE, "respondent_email": "c@client.com", "respondent_name": "C"})
    token = r.json()["share_url"].rsplit("/", 1)[1]
    assert token not in caplog.text
    stored = gw.sql("SELECT access_token FROM questionnaire_sessions WHERE run_id = 'qrun-h'")[0][0]
    assert stored == hashlib.sha256(token.encode()).hexdigest() != token
    assert "share_url" not in gw.client.get("/runs/qrun-h/questionnaires", headers=org.auth).json()[0]
    assert gw.client.get(f"/questionnaire/{token}/status").status_code == 200
    assert gw.client.get(f"/questionnaire/{stored}/status").status_code == 404          # the hash is not a credential
    gw.sql("UPDATE questionnaire_sessions SET access_token = 'legacyplaintexttoken' WHERE run_id = 'qrun-h'")
    assert gw.client.get("/questionnaire/legacyplaintexttoken/status").status_code == 404
