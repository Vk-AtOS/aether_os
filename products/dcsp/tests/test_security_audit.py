from __future__ import annotations
import pytest
import os
from src.security.audit import (
    run_security_audit,
    get_audit_summary,
    SecurityFinding,
    AuditReport,
    _check_secret_key,
    _check_webhook_secret,
    _check_database_url,
    _check_debug_mode,
    _check_docker_sandbox,
    _check_admin_password,
    _check_https
)

def test_run_audit_returns_report():
    report = run_security_audit()
    assert isinstance(report, AuditReport)
    assert len(report.findings) > 0
    assert report.run_at != ""

def test_audit_score_range():
    report = run_security_audit()
    assert 0 <= report.score <= 100

def test_audit_counts_consistent():
    report = run_security_audit()
    total = report.passed_count + report.failed_count
    assert total == len(report.findings)

def test_get_audit_summary_keys():
    report = run_security_audit()
    summary = get_audit_summary(report)
    assert "score" in summary
    assert "passed" in summary
    assert "failed" in summary
    assert "critical" in summary
    assert "findings" in summary

def test_check_secret_key_missing(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    finding = _check_secret_key()
    assert finding.passed is False
    assert finding.severity == "critical"

def test_check_secret_key_strong(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a" * 64)
    finding = _check_secret_key()
    assert finding.passed is True

def test_check_secret_key_too_short(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "tooshort")
    finding = _check_secret_key()
    assert finding.passed is False
    assert finding.severity == "high"

def test_check_webhook_secret_missing(monkeypatch):
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    finding = _check_webhook_secret()
    assert finding.passed is False

def test_check_webhook_secret_set(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "my_secret")
    finding = _check_webhook_secret()
    assert finding.passed is True

def test_check_debug_off(monkeypatch):
    monkeypatch.setenv("DEBUG", "false")
    finding = _check_debug_mode()
    assert finding.passed is True

def test_check_debug_on(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    finding = _check_debug_mode()
    assert finding.passed is False
    assert finding.severity == "high"

def test_check_admin_password_default(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "dcsp2024")  # force known default value
    finding = _check_admin_password()
    assert finding.passed is False
    assert finding.severity == "critical"

def test_check_admin_password_custom(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "sup3r$ecure!XYZ")
    finding = _check_admin_password()
    assert finding.passed is True

def test_check_https_set(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://dcsp.mycompany.com")
    finding = _check_https()
    assert finding.passed is True

def test_check_https_http(monkeypatch):
    monkeypatch.setenv("BASE_URL", "http://dcsp.mycompany.com")
    finding = _check_https()
    assert finding.passed is False
    assert finding.severity == "medium"

def test_finding_dataclass():
    f = SecurityFinding(
        severity="low",
        category="test",
        title="Test finding",
        description="desc",
        remediation="fix it"
    )
    assert f.passed is False

def test_score_perfect():
    report = AuditReport()
    for _ in range(5):
        report.add(SecurityFinding(
            severity="info",
            category="test",
            title="OK",
            description="",
            remediation="",
            passed=True
        ))
    report.compute_score()
    assert report.score == 100

def test_score_with_critical():
    report = AuditReport()
    report.add(SecurityFinding(
        severity="critical",
        category="test",
        title="Bad",
        description="",
        remediation="",
        passed=False
    ))
    report.compute_score()
    assert report.score == 80

def test_security_audit_api():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "sec_audit_tok"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/api/security/audit",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    data = r.json()
    assert "score" in data
    assert "findings" in data

def test_security_dashboard_page():
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "sec_dash_tok"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    r = client.get(
        "/dashboard/security",
        cookies={"session_token": token}
    )
    assert r.status_code == 200
    assert "Security" in r.text
