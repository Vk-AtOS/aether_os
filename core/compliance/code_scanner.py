"""
AetherOS Compliance Code Scanner.

Parses generated FastAPI code and checks each route against compliance frameworks.
Returns structured findings used to generate compliance reports and inject fixes.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class RouteInfo:
    method: str
    path: str
    function_name: str
    has_auth: bool           # has Depends(get_current_user) or similar
    has_rate_limit: bool     # has @limiter.limit or slowapi decorator
    has_input_validation: bool  # has Pydantic model as body param
    has_audit_log: bool      # calls audit_log or logger.info with request context
    has_error_handling: bool    # has try/except or HTTPException raises
    line_number: int
    raw_decorators: List[str] = field(default_factory=list)


@dataclass
class ComplianceFinding:
    severity: str   # "critical", "high", "medium", "low", "pass"
    framework: str  # "HIPAA", "GDPR", "SOC2", "PCI-DSS"
    rule_id: str
    rule_name: str
    description: str
    routes_affected: List[str]   # list of "METHOD /path"
    remediation: str


@dataclass
class ComplianceScanResult:
    project_name: str
    domain: str
    routes: List[RouteInfo]
    findings: List[ComplianceFinding]
    score: int   # 0-100
    scanned_file: str
    scan_timestamp: str


def scan_file(
    main_py_path: Path,
    project_name: str = "",
    domain: str = "general",
) -> ComplianceScanResult:
    """
    Main entry point. Scans a FastAPI main.py and returns compliance results.
    Handles missing files gracefully — always returns a ComplianceScanResult,
    never raises.
    """
    import datetime

    ts = datetime.datetime.utcnow().isoformat()

    if not main_py_path.exists():
        return ComplianceScanResult(
            project_name=project_name,
            domain=domain,
            routes=[],
            findings=[
                ComplianceFinding(
                    severity="critical",
                    framework="ALL",
                    rule_id="SCAN-001",
                    rule_name="Source not found",
                    description=f"Could not locate {main_py_path}",
                    routes_affected=[],
                    remediation="Ensure code generation completed successfully",
                )
            ],
            score=0,
            scanned_file=str(main_py_path),
            scan_timestamp=ts,
        )

    source = main_py_path.read_text(encoding="utf-8", errors="replace")
    routes = _extract_routes(source)
    findings = _run_compliance_checks(routes, source, domain)
    score = _calculate_score(routes, findings)

    return ComplianceScanResult(
        project_name=project_name,
        domain=domain,
        routes=routes,
        findings=findings,
        score=score,
        scanned_file=str(main_py_path),
        scan_timestamp=ts,
    )


# ---------------------------------------------------------------------------
# Route extraction
# ---------------------------------------------------------------------------

def _extract_routes(source: str) -> List[RouteInfo]:
    """Extract all FastAPI route definitions from source code."""
    routes: List[RouteInfo] = []
    lines = source.splitlines()

    route_pattern = re.compile(
        r'@(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    auth_patterns = [
        r'Depends\s*\(\s*get_current_user',
        r'Depends\s*\(\s*require_role',
        r'Authorization.*Bearer',
        r'current_user.*Depends',
        r'token.*Depends',
    ]
    rate_limit_patterns = [
        r'@limiter\.limit',
        r'slowapi',
        r'RateLimit',
        r'rate_limit',
    ]
    validation_patterns = [
        r':\s*\w+Base\b',
        r':\s*\w+Create\b',
        r':\s*\w+Schema\b',
        r':\s*\w+Request\b',
        r'Body\(',
        r'Form\(',
    ]
    audit_patterns = [
        r'audit_log',
        r'logger\.(info|warning|error)\(',
        r'log_audit',
        r'audit_trail',
    ]

    for i, line in enumerate(lines):
        m = route_pattern.search(line)
        if not m:
            continue

        method = m.group(1).upper()
        path = m.group(2)

        # Look for function def in next 3 lines
        func_name = ""
        for j in range(i + 1, min(i + 4, len(lines))):
            fm = re.search(r'async def (\w+)|def (\w+)', lines[j])
            if fm:
                func_name = fm.group(1) or fm.group(2)
                break

        # Collect function body (next 50 lines) for pattern matching
        body_end = min(i + 50, len(lines))
        body = "\n".join(lines[i:body_end])

        routes.append(RouteInfo(
            method=method,
            path=path,
            function_name=func_name,
            has_auth=any(re.search(p, body, re.IGNORECASE) for p in auth_patterns),
            has_rate_limit=any(re.search(p, body, re.IGNORECASE) for p in rate_limit_patterns),
            has_input_validation=(
                method in ("POST", "PUT", "PATCH")
                and any(re.search(p, body) for p in validation_patterns)
            ),
            has_audit_log=any(re.search(p, body, re.IGNORECASE) for p in audit_patterns),
            has_error_handling=bool(
                re.search(r'try:|except |HTTPException|raise', body)
            ),
            line_number=i + 1,
            raw_decorators=[line],
        ))

    return routes


# ---------------------------------------------------------------------------
# Compliance rule checks
# ---------------------------------------------------------------------------

# Paths that don't require authentication
_PUBLIC_PATHS = {
    "/health", "/docs", "/redoc", "/openapi.json", "/metrics",
    "/auth/login", "/auth/register", "/auth/refresh", "/",
}


def _run_compliance_checks(
    routes: List[RouteInfo],
    source: str,
    domain: str,
) -> List[ComplianceFinding]:
    findings: List[ComplianceFinding] = []

    protected_routes = [
        r for r in routes
        if r.path not in _PUBLIC_PATHS and not r.path.startswith("/auth/")
    ]
    unauth_routes = [r for r in protected_routes if not r.has_auth]

    # ── HIPAA ─────────────────────────────────────────────────────────────────
    # Always run HIPAA checks regardless of domain — they encode good baseline
    # security hygiene for any web API.

    if unauth_routes:
        findings.append(ComplianceFinding(
            severity="critical" if domain == "healthcare" else "high",
            framework="HIPAA",
            rule_id="HIPAA-TS-164.312(d)",
            rule_name="Access Control — Unique User Identification",
            description=(
                f"{len(unauth_routes)} data endpoint(s) lack authentication. "
                "HIPAA requires unique user identification for all PHI access."
            ),
            routes_affected=[f"{r.method} {r.path}" for r in unauth_routes],
            remediation=(
                "Add `Depends(get_current_user)` to all data endpoints. "
                "Verify JWT tokens include user ID in sub claim."
            ),
        ))
    else:
        findings.append(ComplianceFinding(
            severity="pass",
            framework="HIPAA",
            rule_id="HIPAA-TS-164.312(d)",
            rule_name="Access Control — Unique User Identification",
            description="All data endpoints require authentication.",
            routes_affected=[],
            remediation="",
        ))

    no_audit = [r for r in protected_routes if not r.has_audit_log]
    if no_audit:
        findings.append(ComplianceFinding(
            severity="high",
            framework="HIPAA",
            rule_id="HIPAA-TS-164.312(b)",
            rule_name="Audit Controls",
            description=(
                f"{len(no_audit)} endpoint(s) do not log access events. "
                "HIPAA requires audit records of all PHI access."
            ),
            routes_affected=[f"{r.method} {r.path}" for r in no_audit],
            remediation=(
                "Add audit logging middleware or per-endpoint logger.info calls "
                "with user ID, timestamp, and resource accessed."
            ),
        ))
    else:
        findings.append(ComplianceFinding(
            severity="pass",
            framework="HIPAA",
            rule_id="HIPAA-TS-164.312(b)",
            rule_name="Audit Controls",
            description="Audit logging present on all protected endpoints.",
            routes_affected=[],
            remediation="",
        ))

    write_routes = [r for r in routes if r.method in ("POST", "PUT", "PATCH")]
    no_validation = [r for r in write_routes if not r.has_input_validation]
    if no_validation:
        findings.append(ComplianceFinding(
            severity="high",
            framework="HIPAA",
            rule_id="HIPAA-TS-164.312(c)(1)",
            rule_name="Integrity — PHI Alteration Protection",
            description=(
                f"{len(no_validation)} write endpoint(s) lack input validation. "
                "Unvalidated input can corrupt or leak PHI data."
            ),
            routes_affected=[f"{r.method} {r.path}" for r in no_validation],
            remediation=(
                "Use Pydantic models for all request bodies. "
                "Add field validators for required PHI fields."
            ),
        ))
    else:
        findings.append(ComplianceFinding(
            severity="pass",
            framework="HIPAA",
            rule_id="HIPAA-TS-164.312(c)(1)",
            rule_name="Integrity Controls",
            description="Input validation present on all write endpoints.",
            routes_affected=[],
            remediation="",
        ))

    # ── GDPR ──────────────────────────────────────────────────────────────────

    has_delete = any(r.method == "DELETE" for r in routes)
    if not has_delete:
        findings.append(ComplianceFinding(
            severity="high",
            framework="GDPR",
            rule_id="GDPR-Art17",
            rule_name="Right to Erasure",
            description=(
                "No DELETE endpoints found. GDPR Article 17 requires the ability "
                "to delete personal data on request."
            ),
            routes_affected=["ALL"],
            remediation=(
                "Implement DELETE /users/{id} and DELETE /data/{id} endpoints "
                "that permanently remove personal data."
            ),
        ))
    else:
        findings.append(ComplianceFinding(
            severity="pass",
            framework="GDPR",
            rule_id="GDPR-Art17",
            rule_name="Right to Erasure",
            description="DELETE endpoints present.",
            routes_affected=[],
            remediation="",
        ))

    has_cors = bool(re.search(
        r'CORSMiddleware|CORS_ORIGINS|allow_origins', source
    ))
    if not has_cors:
        findings.append(ComplianceFinding(
            severity="medium",
            framework="GDPR",
            rule_id="GDPR-Art32",
            rule_name="Security of Processing — CORS",
            description=(
                "No CORS configuration found. Cross-origin requests may expose "
                "data to unauthorized domains."
            ),
            routes_affected=["ALL"],
            remediation=(
                "Add CORSMiddleware with explicit allow_origins from environment "
                "variable. Never use ['*'] in production."
            ),
        ))
    else:
        findings.append(ComplianceFinding(
            severity="pass",
            framework="GDPR",
            rule_id="GDPR-Art32",
            rule_name="CORS Configuration",
            description="CORS middleware present.",
            routes_affected=[],
            remediation="",
        ))

    # Wildcard CORS check (GDPR Art32 / SOC2 CC6.6)
    if re.search(r"allow_origins\s*=\s*\[[\"\']?\*[\"\']?\]", source):
        findings.append(ComplianceFinding(
            severity="medium",
            framework="GDPR",
            rule_id="GDPR-Art32-CORS-WILDCARD",
            rule_name="CORS Wildcard Origin",
            description=(
                "allow_origins=['*'] permits cross-origin requests from any domain. "
                "This violates the data minimisation principle for production deployments."
            ),
            routes_affected=["ALL"],
            remediation=(
                "Replace allow_origins=['*'] with "
                "os.getenv('ALLOWED_ORIGINS','http://localhost:3000').split(',') "
                "so origins come from a controlled environment variable."
            ),
        ))

    # ── SOC2 ──────────────────────────────────────────────────────────────────

    no_rate_limit = [r for r in protected_routes if not r.has_rate_limit]
    total_protected = len(protected_routes)
    if total_protected > 0 and len(no_rate_limit) > total_protected * 0.5:
        findings.append(ComplianceFinding(
            severity="medium",
            framework="SOC2",
            rule_id="SOC2-CC6.6",
            rule_name="Logical and Physical Access — Rate Limiting",
            description=(
                f"{len(no_rate_limit)}/{total_protected} endpoints lack rate limiting. "
                "This enables brute force and DoS attacks."
            ),
            routes_affected=[f"{r.method} {r.path}" for r in no_rate_limit[:10]],
            remediation=(
                "Add slowapi Limiter with default_limits=['200/day', '50/hour'] "
                "applied globally or per endpoint."
            ),
        ))
    else:
        findings.append(ComplianceFinding(
            severity="pass",
            framework="SOC2",
            rule_id="SOC2-CC6.6",
            rule_name="Rate Limiting",
            description="Rate limiting configured on majority of protected endpoints.",
            routes_affected=[],
            remediation="",
        ))

    has_https = bool(re.search(
        r'FORCE_HTTPS|HTTPSRedirect|secure.*cookie|HSTS', source, re.IGNORECASE
    ))
    findings.append(ComplianceFinding(
        severity="pass" if has_https else "medium",
        framework="SOC2",
        rule_id="SOC2-CC6.7",
        rule_name="Encryption in Transit",
        description=(
            "HTTPS enforcement configured."
            if has_https
            else (
                "No HTTPS enforcement found. Deploy behind TLS terminator "
                "(nginx + certbot) or enable HTTPSRedirectMiddleware."
            )
        ),
        routes_affected=[] if has_https else ["ALL"],
        remediation=(
            ""
            if has_https
            else "Set FORCE_HTTPS=true in production or use nginx as TLS terminator."
        ),
    ))

    # Hardcoded secrets check (SOC2 CC6.1)
    secret_pattern = re.compile(
        r'(SECRET_KEY|PASSWORD|API_KEY|TOKEN)\s*=\s*["\'][^"\']{8,}["\']',
        re.IGNORECASE,
    )
    if secret_pattern.search(source):
        findings.append(ComplianceFinding(
            severity="critical",
            framework="SOC2",
            rule_id="SOC2-CC6.1",
            rule_name="Logical Access Controls — Hardcoded Secrets",
            description=(
                "Hardcoded secret, password, or API key detected in source. "
                "These will leak if the repository is ever made public."
            ),
            routes_affected=["src/main.py"],
            remediation=(
                "Move all secrets to environment variables or a secrets manager. "
                "Use os.getenv('SECRET_KEY') and fail-fast if None at startup."
            ),
        ))
    else:
        findings.append(ComplianceFinding(
            severity="pass",
            framework="SOC2",
            rule_id="SOC2-CC6.1",
            rule_name="Hardcoded Secrets",
            description="No hardcoded secrets detected in source.",
            routes_affected=[],
            remediation="",
        ))

    # ── PCI-DSS ───────────────────────────────────────────────────────────────

    payment_routes = [
        r for r in routes
        if any(kw in r.path.lower() for kw in ("payment", "billing", "card", "checkout", "stripe"))
    ]
    if payment_routes:
        payment_unauth = [r for r in payment_routes if not r.has_auth]
        if payment_unauth:
            findings.append(ComplianceFinding(
                severity="critical",
                framework="PCI-DSS",
                rule_id="PCI-DSS-7",
                rule_name="Restrict Access to Cardholder Data",
                description=(
                    "Payment endpoint(s) found without authentication. "
                    "PCI-DSS requires strict access control for all payment flows."
                ),
                routes_affected=[f"{r.method} {r.path}" for r in payment_unauth],
                remediation=(
                    "Immediately add authentication to all payment endpoints. "
                    "Consider delegating card handling to Stripe/Razorpay to avoid "
                    "storing card data directly."
                ),
            ))
        else:
            findings.append(ComplianceFinding(
                severity="pass",
                framework="PCI-DSS",
                rule_id="PCI-DSS-7",
                rule_name="Restrict Access to Cardholder Data",
                description="All payment endpoints require authentication.",
                routes_affected=[],
                remediation="",
            ))

    return findings


# ---------------------------------------------------------------------------
# Score calculation
# ---------------------------------------------------------------------------

def _calculate_score(routes: List[RouteInfo], findings: List[ComplianceFinding]) -> int:
    if not routes:
        return 0

    critical = sum(1 for f in findings if f.severity == "critical")
    high = sum(1 for f in findings if f.severity == "high")
    medium = sum(1 for f in findings if f.severity == "medium")
    passes = sum(1 for f in findings if f.severity == "pass")

    score = 100
    score -= critical * 25
    score -= high * 15
    score -= medium * 5
    score += passes * 2
    return max(0, min(100, score))
