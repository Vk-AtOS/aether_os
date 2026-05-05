from dataclasses import dataclass, field
from typing import List, Optional
import asyncio
import re
import os
import json
import subprocess
from pathlib import Path

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
            print(f"Bandit scan failed: {e}")

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
        if domain == "fintech":
            for root, _, files in os.walk(project_dir):
                for file in files:
                    if file.endswith(".py"):
                        path = Path(root) / file
                        content = path.read_text()
                        if "credit_card" in content and "encrypt" not in content:
                            findings.append(Finding(
                                severity="HIGH",
                                rule_id="FINTECH_NO_ENCRYPTION",
                                file_path=str(path),
                                line_number=0,
                                message="Potential unencrypted credit card data"
                            ))

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
