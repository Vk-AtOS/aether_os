from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.api.auth import ACTIVE_SESSIONS

def test_job_detail_page_no_auth():
    client = TestClient(
        app, follow_redirects=False)
    r = client.get(
        "/dashboard/job/test_job_id")
    # Redirect to login
    assert r.status_code in (302, 401, 303)

def test_job_detail_page_auth():
    token = "diff_view_tok"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/dashboard/job/nonexistent_job",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    assert "Job" in r.text or \
        "job" in r.text.lower()

def test_get_job_api_not_found():
    token = "job_api_tok"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/api/jobs/does_not_exist_999",
        cookies={"session_token": token}
    )
    assert r.status_code == 404

def test_get_job_api_from_history():
    from src.api.state import JOB_HISTORY
    JOB_HISTORY.append({
        "id": "test_job_abc",
        "repo_name": "acme/api",
        "status": "success",
        "confidence": 0.91,
        "patch_diff": "--- a/x.py\n"
                 "+++ b/x.py\n"
                 "@@ -1 +1 @@\n"
                 "-old\n+new\n"
    })
    token = "job_hist_tok"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/api/jobs/test_job_abc",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["repo_name"] == "acme/api"
    # Clean up
    JOB_HISTORY.pop()

def test_job_detail_has_diff_renderer():
    token = "diff_html_tok"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/dashboard/job/fake_job",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    # Page should have diff-related HTML
    assert any(term in r.text for term in
        ["diff", "patch", "Patch",
         "Diff", "approve", "Approve"])

def test_job_api_unauthorized():
    client = TestClient(app)
    r = client.get("/api/jobs/some_job")
    assert r.status_code == 401
