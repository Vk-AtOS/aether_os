from fastapi.testclient import TestClient
from src.api.main import app
from src.api.auth import ACTIVE_SESSIONS
from src.database import SessionLocal
from src.db.audit_repo import get_audit_logs, save_audit_log
import pytest

client = TestClient(app)

@pytest.fixture
def auth_cookie():
    token = "test_token_compliance"
    ACTIVE_SESSIONS[token] = "admin"
    return {"session_token": token}

def test_compliance_endpoint_requires_auth():
    response = client.get("/dashboard/compliance", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["location"]

def test_compliance_export_csv_returns_file(auth_cookie):
    response = client.get("/api/compliance/export?format=csv", cookies=auth_cookie)
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment; filename=compliance_report.csv" in response.headers["content-disposition"]

def test_compliance_export_pdf_returns_file(auth_cookie):
    response = client.get("/api/compliance/export?format=pdf", cookies=auth_cookie)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment; filename=compliance_report.pdf" in response.headers["content-disposition"]

def test_audit_log_saves_on_approve(auth_cookie):
    # Need a job ID to approve
    # Create a fake job in DB/Memory for testing? 
    # Or just use a random ID, it might fail 404 but audit might log?
    # The code: update_job_approval returns True/False.
    # If job not found, it raises 404.
    
    # We should seed a job first
    from src.api.state import add_job_to_history
    import uuid
    job_id = str(uuid.uuid4())
    add_job_to_history({
        "id": job_id, 
        "repo_name": "test/repo", 
        "timestamp": "2023-01-01T00:00:00", 
        "success": True, 
        "approved": None,
        "patch_diff": "..."
    })
    
    response = client.post(f"/dashboard/approve/{job_id}", cookies=auth_cookie)
    assert response.status_code == 200
    
    session = SessionLocal()
    logs = get_audit_logs(session, limit=10, action_filter="approve_job")
    session.close()
    
    # Find our log
    found = False
    for log in logs:
        if log.job_id == job_id and log.actor == "admin":
            found = True
            break
    assert found

def test_audit_log_saves_on_reject(auth_cookie):
    from src.api.state import add_job_to_history
    import uuid
    job_id = str(uuid.uuid4())
    add_job_to_history({
        "id": job_id, 
        "repo_name": "test/repo", 
        "timestamp": "2023-01-01T00:00:00", 
        "success": True, 
        "approved": None,
        "patch_diff": "..."
    })
    
    response = client.post(f"/dashboard/reject/{job_id}", cookies=auth_cookie)
    assert response.status_code == 200
    
    session = SessionLocal()
    logs = get_audit_logs(session, limit=10, action_filter="reject_job")
    session.close()
    
    found = False
    for log in logs:
        if log.job_id == job_id and log.actor == "admin":
            found = True
            break
    assert found
