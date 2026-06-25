from __future__ import annotations
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SecurityFinding:
    severity: str
    # "critical", "high", "medium", "low", "info"
    category: str
    title: str
    description: str
    remediation: str
    passed: bool = False


@dataclass
class AuditReport:
    findings: list[SecurityFinding] = field(default_factory=list)
    run_at: str = ""
    passed_count: int = 0
    failed_count: int = 0
    critical_count: int = 0
    high_count: int = 0
    score: int = 0
    # 0-100

    def add(self, finding: SecurityFinding) -> None:
        self.findings.append(finding)
        if finding.passed:
            self.passed_count += 1
        else:
            self.failed_count += 1
            if finding.severity == "critical":
                self.critical_count += 1
            elif finding.severity == "high":
                self.high_count += 1

    def compute_score(self) -> None:
        total = self.passed_count + self.failed_count
        if total == 0:
            self.score = 100
            return
        # Critical failures subtract 20, high subtract 10, others subtract 5
        deductions = (
            self.critical_count * 20 +
            self.high_count * 10 +
            max(0, self.failed_count - self.critical_count - self.high_count) * 5
        )
        self.score = max(0, 100 - deductions)


def _check_secret_key() -> SecurityFinding:
    key = os.getenv("SECRET_KEY", "")
    if not key or key in ("secret", "changeme", "dev-secret", "your-secret-key"):
        return SecurityFinding(
            severity="critical",
            category="secrets",
            title="Weak or missing SECRET_KEY",
            description="SECRET_KEY is not set or uses a default value.",
            remediation="Set a strong random SECRET_KEY in your .env file: openssl rand -hex 32",
            passed=False
        )
    if len(key) < 32:
        return SecurityFinding(
            severity="high",
            category="secrets",
            title="SECRET_KEY too short",
            description="SECRET_KEY should be at least 32 characters.",
            remediation="Generate a longer key: openssl rand -hex 32",
            passed=False
        )
    return SecurityFinding(
        severity="info",
        category="secrets",
        title="SECRET_KEY configured",
        description="SECRET_KEY is set.",
        remediation="",
        passed=True
    )


def _check_webhook_secret() -> SecurityFinding:
    secret = os.getenv("WEBHOOK_SECRET", "")
    if not secret:
        return SecurityFinding(
            severity="high",
            category="webhooks",
            title="WEBHOOK_SECRET not set",
            description="Without a webhook secret, anyone can send fake CI events.",
            remediation="Set WEBHOOK_SECRET in .env and configure it in your CI.",
            passed=False
        )
    return SecurityFinding(
        severity="info",
        category="webhooks",
        title="Webhook secret configured",
        description="WEBHOOK_SECRET is set.",
        remediation="",
        passed=True
    )


def _check_database_url() -> SecurityFinding:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        return SecurityFinding(
            severity="medium",
            category="database",
            title="DATABASE_URL not set",
            description="Using SQLite fallback instead of PostgreSQL.",
            remediation="Set DATABASE_URL to a PostgreSQL connection string.",
            passed=False
        )
    if "password" in url.lower() or "changeme" in url.lower():
        return SecurityFinding(
            severity="medium",
            category="database",
            title="Weak database password",
            description="DATABASE_URL may contain a weak password.",
            remediation="Use a strong, unique database password.",
            passed=False
        )
    return SecurityFinding(
        severity="info",
        category="database",
        title="Database URL configured",
        description="DATABASE_URL is set.",
        remediation="",
        passed=True
    )


def _check_debug_mode() -> SecurityFinding:
    debug = os.getenv("DEBUG", "false").lower()
    if debug in ("true", "1", "yes"):
        return SecurityFinding(
            severity="high",
            category="configuration",
            title="DEBUG mode enabled",
            description="Debug mode exposes stack traces and sensitive info.",
            remediation="Set DEBUG=false in production.",
            passed=False
        )
    return SecurityFinding(
        severity="info",
        category="configuration",
        title="DEBUG mode disabled",
        description="DEBUG is not enabled.",
        remediation="",
        passed=True
    )


def _check_docker_sandbox() -> SecurityFinding:
    enabled = os.getenv("SANDBOX_ENABLED", "")
    if not enabled or enabled.lower() in ("false", "0", "no"):
        return SecurityFinding(
            severity="medium",
            category="sandbox",
            title="Docker sandbox not enabled",
            description="Patches run without isolation. Enable Docker sandbox for safety.",
            remediation="Set SANDBOX_ENABLED=true and ensure Docker is running.",
            passed=False
        )
    return SecurityFinding(
        severity="info",
        category="sandbox",
        title="Docker sandbox enabled",
        description="Patches are validated in isolation.",
        remediation="",
        passed=True
    )


def _check_admin_password() -> SecurityFinding:
    password = os.getenv("ADMIN_PASSWORD", "dcsp2024")
    weak_passwords = {"", "admin", "password", "dcsp2024", "changeme", "123456", "dcsp"}
    if password in weak_passwords:
        return SecurityFinding(
            severity="critical",
            category="authentication",
            title="Default admin password in use",
            description="The default admin password dcsp2024 has not been changed.",
            remediation="Set ADMIN_PASSWORD to a strong unique password.",
            passed=False
        )
    return SecurityFinding(
        severity="info",
        category="authentication",
        title="Admin password changed",
        description="Admin password is not default.",
        remediation="",
        passed=True
    )


def _check_https() -> SecurityFinding:
    base_url = os.getenv("BASE_URL", "")
    if base_url.startswith("https://"):
        return SecurityFinding(
            severity="info",
            category="transport",
            title="HTTPS configured",
            description="BASE_URL uses HTTPS.",
            remediation="",
            passed=True
        )
    if base_url.startswith("http://"):
        return SecurityFinding(
            severity="medium",
            category="transport",
            title="HTTPS not configured",
            description="BASE_URL uses HTTP. Use HTTPS in production.",
            remediation="Configure a TLS certificate and set BASE_URL to https://.",
            passed=False
        )
    return SecurityFinding(
        severity="low",
        category="transport",
        title="BASE_URL not set",
        description="BASE_URL is not configured. Set it for proper redirects.",
        remediation="Set BASE_URL in .env.",
        passed=False
    )


def run_security_audit() -> AuditReport:
    """Run all security checks."""
    report = AuditReport(run_at=datetime.utcnow().isoformat())

    checks = [
        _check_secret_key,
        _check_webhook_secret,
        _check_database_url,
        _check_debug_mode,
        _check_docker_sandbox,
        _check_admin_password,
        _check_https
    ]

    for check in checks:
        try:
            finding = check()
            report.add(finding)
        except Exception as e:
            logger.error(f"Security check failed: {e}")

    report.compute_score()
    return report


def get_audit_summary(report: AuditReport) -> dict:
    return {
        "score": report.score,
        "passed": report.passed_count,
        "failed": report.failed_count,
        "critical": report.critical_count,
        "high": report.high_count,
        "run_at": report.run_at,
        "findings": [
            {
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "description": f.description,
                "remediation": f.remediation,
                "passed": f.passed
            }
            for f in report.findings
        ]
    }
