from dataclasses import dataclass
from typing import List, Optional
import asyncio
import logging
import re
import os
import json
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Domain-specific rules: (rule_id, regex_pattern, message, severity)
_DOMAIN_RULES: dict[str, list[tuple[str, str, str, str]]] = {
    "fintech": [
        ("FINTECH_UNENCRYPTED_CARD", r"credit_card(?!.*encrypt)", "Potential unencrypted credit card data", "HIGH"),
        ("FINTECH_PLAINTEXT_PAN", r"card_number\s*=\s*[\"'][0-9]{13,19}[\"']", "Hardcoded PAN detected", "CRITICAL"),
        ("FINTECH_WEAK_JWT", r"algorithm\s*=\s*[\"']HS256[\"']", "HS256 JWT — prefer RS256 for production", "MEDIUM"),
        ("FINTECH_SQL_PARAM", r"SELECT.*WHERE.*%s|SELECT.*WHERE.*\.format\(", "Potential SQL injection pattern", "HIGH"),
    ],
    "healthcare": [
        ("HIPAA_PHI_LOG", r"logger\.(info|debug|warning)\(.*patient|logger\.(info|debug|warning)\(.*dob", "PHI may be logged — HIPAA violation risk", "HIGH"),
        ("HIPAA_UNENCRYPTED_SSN", r"ssn\s*=|social_security", "SSN field without visible encryption", "HIGH"),
        ("HIPAA_OPEN_CORS", r'allow_origins=\["\*"\]|allow_origins=\["http', "Overly permissive CORS on healthcare API", "MEDIUM"),
        ("HIPAA_NO_AUDIT", r"def (create|update|delete).*:\n(?!.*audit|.*log_action)", "CRUD mutation without audit log", "MEDIUM"),
    ],
    "ecommerce": [
        ("PCI_PLAINTEXT_CVV", r"cvv|cvc|card_verification", "CVV/CVC field — must not store per PCI-DSS", "CRITICAL"),
        ("PCI_UNMASKED_PAN", r"card_number.*=.*str\(|print.*card_number", "PAN may be exposed in logs or response", "HIGH"),
        ("ECOM_OPEN_IDOR", r"\.get\(item_id\)|\.filter\(id=item_id\)(?!.*user_id|.*org_id)", "IDOR risk: resource not scoped to user/org", "MEDIUM"),
    ],
    "saas": [
        ("SAAS_NO_ORG_FILTER", r"select\(.*Model\)(?!.*org_id)|\.all\(\)(?!.*org_id)", "Query without org_id filter — potential tenant data leak", "HIGH"),
        ("SAAS_WEAK_SECRET", r'SECRET_KEY\s*=\s*["\']change.me|SECRET_KEY\s*=\s*["\']secret', "Weak default SECRET_KEY", "CRITICAL"),
    ],
    "marketplace": [
        ("MKT_PRICE_INJECTION", r"price\s*=.*request|amount\s*=.*body\.get", "Price/amount taken from request without validation", "MEDIUM"),
        ("MKT_SELF_BID", r"def.*bid.*:(?!.*seller_id.*buyer_id|.*user.*listing\.seller)", "Bid endpoint may not prevent self-bidding", "MEDIUM"),
    ],
}


_AUDIT_CACHE: dict = {}   # (path, mtime_ns, size) -> (monotonic time, findings); pip-audit is slow
_AUDIT_TTL_S = 3600.0
_AUDIT_CACHE_MAX = 256


def _run_pip_audit(project_dir: str) -> list["Finding"]:
    """Run pip-audit against requirements.txt; return findings for known CVEs (cached 1 h)."""
    req_file = Path(project_dir) / "requirements.txt"
    if not req_file.exists():
        return []
    st = req_file.stat()
    key = (str(req_file), st.st_mtime_ns, st.st_size)
    hit = _AUDIT_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _AUDIT_TTL_S:
        return list(hit[1])
    findings = _run_pip_audit_uncached(req_file)
    if len(_AUDIT_CACHE) >= _AUDIT_CACHE_MAX:
        _AUDIT_CACHE.pop(next(iter(_AUDIT_CACHE)), None)
    _AUDIT_CACHE[key] = (time.monotonic(), list(findings))
    return findings


def _run_pip_audit_uncached(req_file: Path) -> list["Finding"]:
    findings: list[Finding] = []
    try:
        res = subprocess.run(
            ["pip-audit", "-r", str(req_file), "-f", "json", "--progress-spinner", "off"],
            capture_output=True, text=True, timeout=120,
        )
        if res.stdout:
            data = json.loads(res.stdout)
            for dep in data.get("dependencies", []):
                for vuln in dep.get("vulns", []):
                    findings.append(Finding(
                        severity="HIGH",
                        rule_id=f"PIP_AUDIT_{vuln.get('id', 'UNKNOWN')}",
                        file_path=str(req_file),
                        line_number=0,
                        message=f"{dep.get('name','?')} {dep.get('version','?')}: {vuln.get('description','CVE')[:120]}",
                        fix_suggestion=f"Upgrade to {vuln.get('fix_versions', ['latest'])}",
                    ))
    except FileNotFoundError:
        logger.debug("pip-audit not installed — skipping dependency vulnerability scan")
    except Exception as exc:
        logger.warning("pip-audit scan failed (non-fatal): %s", exc)
    return findings


@dataclass
class Finding:
    severity: str
    rule_id: str
    file_path: str
    line_number: int
    message: str
    fix_suggestion: Optional[str] = None

@dataclass
class ScanResult:
    passed: bool
    critical_count: int
    high_count: int
    medium_count: int
    findings: List[Finding]
    scan_duration_seconds: float

class CodeScanner:
    async def scan_project(self, project_dir: str, domain: str) -> ScanResult:
        import time
        start_time = time.time()
        findings = []

        # 1. Bandit Scan
        # Note: bandit requires installation
        try:
            res = subprocess.run(
                ["bandit", "-r", project_dir, "-f", "json", "-q"],
                capture_output=True, text=True
            )
            if res.stdout:
                data = json.loads(res.stdout)
                for issue in data.get("results", []):
                    sev = issue["issue_severity"]
                    findings.append(Finding(
                        severity=sev,
                        rule_id=issue["test_id"],
                        file_path=issue["filename"],
                        line_number=issue["line_number"],
                        message=issue["issue_text"]
                    ))
        except Exception as e:
            logger.error("Bandit scan failed: %s", e)

        # Hardcoded secret detector (Regex)
        patterns = {
            "API_KEY": r"sk-[a-zA-Z0-9]{32,}",
            "PASSWORD": r"(?i)password\s*[:=]\s*[\"'][^\"']{8,}[\"']",
            "PRIVATE_KEY": r"-----BEGIN.*PRIVATE KEY-----",
            "AWS_KEY": r"AKIA[0-9A-Z]{16}"
        }

        for root, _, files in os.walk(project_dir):
            for file in files:
                if file.endswith((".py", ".env", ".yaml", ".json")):
                    path = Path(root) / file
                    content = path.read_text(errors="ignore")
                    for line_no, line in enumerate(content.splitlines(), 1):
                        for name, pattern in patterns.items():
                            if re.search(pattern, line):
                                findings.append(Finding(
                                    severity="CRITICAL",
                                    rule_id=f"SECRET_{name}",
                                    file_path=str(path),
                                    line_number=line_no,
                                    message=f"Hardcoded {name} detected"
                                ))

        # Domain-specific checks
        domain_rules = _DOMAIN_RULES.get(domain.lower(), [])
        for root, _, files in os.walk(project_dir):
            for file in files:
                if not file.endswith(".py"):
                    continue
                path = Path(root) / file
                try:
                    content = path.read_text(errors="ignore")
                except Exception as e:
                    logger.debug("Could not read %s for domain scan: %s", path, e)
                    continue
                for rule_id, pattern, message, severity in domain_rules:
                    if re.search(pattern, content):
                        findings.append(Finding(
                            severity=severity,
                            rule_id=rule_id,
                            file_path=str(path),
                            line_number=0,
                            message=message,
                        ))

        # pip-audit: dependency vulnerability scan
        findings.extend(await asyncio.to_thread(_run_pip_audit, project_dir))  # blocking subprocess, up to 120 s

        critical = sum(1 for f in findings if f.severity == "CRITICAL")
        high = sum(1 for f in findings if f.severity == "HIGH")
        medium = sum(1 for f in findings if f.severity == "MEDIUM")

        return ScanResult(
            passed=(critical == 0),
            critical_count=critical,
            high_count=high,
            medium_count=medium,
            findings=findings,
            scan_duration_seconds=time.time() - start_time
        )
