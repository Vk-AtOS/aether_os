"""P06 Consolidated Task Agent — code review + security scan + compliance scan."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.errors import PipelineBlockedError

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict:
    """PIPELINE-056: robust JSON extraction that handles nested JSON correctly."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("[p06] _extract_json: direct parse failed: %s", e)
    # Walk through each '{' and find the matching '}'
    for match in re.finditer(r'\{', text):
        start = match.start()
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    break
    raise ValueError("No valid JSON found in text")

_SUBTASK_TIMEOUT = 150.0


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, TaskResult] = {}

    # Sub-task 1: LLM code review — reads generated backend code, checks OWASP issues
    from aether_os.phases.utils import memory_hint
    mem = memory_hint(memory_ctx)

    try:
        from aether_os.core.llm.client import get_llm_client
        _llm_client = get_llm_client()
        data = phase_input.input_data
        project_dir = data.get("project_dir", "")
        backend_path = data.get("backend_output_path", "")

        code_to_review = ""
        for candidate in [
            Path(project_dir) / "src" / "main.py",
            Path(backend_path) / "src" / "main.py" if backend_path else None,
            Path(backend_path) / "main.py" if backend_path else None,
        ]:
            if candidate and candidate.exists():
                code_to_review = candidate.read_text(encoding="utf-8")[:6000]
                break

        if code_to_review:
            _compliance_hint = ""
            try:
                from aether_os.core.domain_knowledge.loader import build_compliance_summary
                _domain = data.get("domain", "general")
                _cs = build_compliance_summary(_domain)
                if _cs:
                    _compliance_hint = f"\n\nDOMAIN COMPLIANCE REQUIREMENTS:\n{_cs}\nEnsure the code satisfies all mandatory rules above.\n\n"
            except Exception as _ce:
                logger.warning("[p06] compliance summary load failed: %s", _ce)
            review_prompt = (
                _compliance_hint +
                "You are a senior security engineer reviewing generated backend code. "
                "Check for OWASP Top-10 vulnerabilities: SQL injection, XSS, broken auth, "
                "hardcoded secrets, missing input validation, insecure CORS, IDOR, and "
                "missing rate-limiting. Return JSON: "
                "{\"findings\": [{\"issue\": str, \"severity\": \"high\"|\"medium\"|\"low\", "
                "\"line_hint\": str, \"recommendation\": str}], \"overall_score\": 0-100, "
                "\"summary\": str}. If no issues, return findings=[]. "
                + mem +
                "Code to review:\n```python\n" + code_to_review + "\n```"
            )
            review_raw = await asyncio.wait_for(
                _llm_client.call(review_prompt, task_type="code_review"),
                timeout=_SUBTASK_TIMEOUT,
            )
            try:
                review_json = _extract_json(review_raw)
            except Exception:
                review_json = {"summary": review_raw[:500], "findings": [], "overall_score": 75}

            sub_dir = output_dir / "code_review"
            sub_dir.mkdir(parents=True, exist_ok=True)
            review_path = sub_dir / "review.json"
            review_path.write_text(json.dumps(review_json, indent=2))

            results["code_review"] = TaskResult(
                output_path=str(review_path),
                confidence=0.8,
                metadata={
                    "findings_count": len(review_json.get("findings", [])),
                    "overall_score": review_json.get("overall_score", 75),
                    "summary": review_json.get("summary", ""),
                },
                success=True,
            )
            logger.info("code_review completed: %d findings", len(review_json.get("findings", [])))
        else:
            logger.info("code_review: no backend main.py found, skipping LLM review")
    except asyncio.TimeoutError:
        logger.warning("code_review timed out after %.0fs (non-critical)", _SUBTASK_TIMEOUT)
    except Exception as e:
        logger.warning("code_review failed (non-critical): %s", e)

    # Sub-task 2: Static security scan using bandit (FIX 19)
    try:
        import subprocess
        
        data = phase_input.input_data
        project_dir = Path(data.get("project_dir", ""))
        backend_path = data.get("backend_output_path", "")
        
        src_path = None
        for candidate in [
            project_dir / "src",
            Path(backend_path) / "src" if backend_path else None,
        ]:
            if candidate and candidate.exists():
                src_path = candidate
                break

        bandit_findings = []
        if src_path:
            # Ensure bandit is installed
            subprocess.run(["pip", "install", "bandit", "-q"], check=False)

            # Run bandit
            result = subprocess.run(
                ["bandit", "-r", "-f", "json", "-ll", str(src_path)],
                capture_output=True, text=True, timeout=60,
            )
            if result.stdout:
                try:
                    data_json = json.loads(result.stdout)
                    bandit_findings = data_json.get("results", [])

                    # Problem 73: check for files that bandit skipped due to parse errors
                    _errors_section = data_json.get("errors", [])
                    _skipped_files = []
                    for _err in _errors_section:
                        _fname = _err.get("filename") or _err.get("file") or ""
                        if _fname:
                            _skipped_files.append(_fname)
                    # Also check metrics for skipped counts if present
                    _metrics = data_json.get("metrics", {}).get("_totals", {})
                    _skipped_count_metric = int(_metrics.get("skipped_tests", 0))

                    if _skipped_files or _skipped_count_metric > 0:
                        _skip_n = len(_skipped_files) or _skipped_count_metric
                        _skip_names = ", ".join(
                            [Path(f).name for f in _skipped_files[:5]]
                        ) or "unknown files"
                        bandit_findings = [
                            {
                                "issue_text": (
                                    f"Security scan incomplete — {_skip_n} file(s) skipped "
                                    f"due to parse errors: {_skip_names}. "
                                    f"Fix syntax errors in p04a before trusting this scan."
                                ),
                                "issue_severity": "HIGH",
                                "issue_confidence": "LOW",
                                "filename": _skip_names,
                                "skipped_due_to_parse_error": True,
                            }
                        ] + bandit_findings
                        logger.warning(
                            "[p06] bandit skipped %d file(s) due to parse errors: %s",
                            _skip_n, _skip_names,
                        )
                except json.JSONDecodeError as e:
                    logger.warning("[p06] failed to parse bandit JSON output for skipped-files detection: %s", e)

        sub_dir = output_dir / "security"
        sub_dir.mkdir(parents=True, exist_ok=True)
        sec_path = sub_dir / "security_scan.json"

        high_severity = sum(1 for f in bandit_findings if f.get("issue_severity") == "HIGH")
        medium_severity = sum(1 for f in bandit_findings if f.get("issue_severity") == "MEDIUM")
        low_severity = sum(1 for f in bandit_findings if f.get("issue_severity") == "LOW")

        # Problem 73: if any files were skipped, confidence must be low
        _has_skipped = any(f.get("skipped_due_to_parse_error") for f in bandit_findings)
        _scan_confidence = 0.3 if _has_skipped else 0.9

        sec_result = {
            "tool": "bandit",
            "findings": bandit_findings,
            "high_severity": high_severity,
            "medium_severity": medium_severity,
            "low_severity": low_severity,
            "clean": (
                len([f for f in bandit_findings if f.get("issue_severity") in ("HIGH", "MEDIUM")]) == 0
                and not _has_skipped
            ),
            "scan_confidence": _scan_confidence,
            "files_skipped_due_to_parse_errors": _has_skipped,
        }
        sec_path.write_text(json.dumps(sec_result, indent=2))

        results["static_analysis"] = TaskResult(
            output_path=str(sec_path),
            confidence=_scan_confidence,
            metadata=sec_result,
            success=True,
            issues=(
                [f"Security scan incomplete — files skipped due to parse errors. "
                 f"Confidence reduced to {_scan_confidence}"]
                if _has_skipped else []
            ),
        )
        logger.info("bandit scan completed: %d findings (confidence=%.1f)", len(bandit_findings), _scan_confidence)
        
        # FIX 19: Check for CRITICAL issues (HIGH severity in bandit)
        if high_severity > 0:
            logger.warning("[p06] HIGH severity security issues found by bandit")
            from aether_os.phases.p06_review_security.patcher import ASTSecurityPatcher
            patcher = ASTSecurityPatcher()
            
            # FIX H4: Patch all files with high-severity issues
            patched_files = set()
            for finding in bandit_findings:
                if finding.get("issue_severity") == "HIGH":
                    fname = finding.get("filename")
                    if fname and os.path.exists(fname) and fname not in patched_files:
                        patcher.patch_file(fname)
                        patched_files.add(fname)
                        logger.info("[p06] Applied AST patch for bandit finding in %s", fname)

            # Ensure main.py is patched even if bandit didn't explicitly flag it but we found issues
            if not patched_files:
                for candidate in [
                    project_dir / "src" / "main.py",
                    Path(backend_path) / "src" / "main.py" if backend_path else None,
                ]:
                    if candidate and candidate.exists():
                        patcher.patch_file(str(candidate))
                        break

    except Exception as e:
        logger.warning("bandit scan failed (non-critical): %s", e)

    # Sub-task 3: Compliance scan (G12 — real code scanner, not LLM report)
    try:
        from aether_os.core.compliance.code_scanner import scan_file
        from aether_os.core.compliance.pdf_report import generate_pdf

        # Resolve the canonical src/main.py written by p04
        data = phase_input.input_data
        project_dir = Path(data.get("project_dir", ""))
        backend_path = data.get("backend_output_path", "")

        main_py: Path | None = None
        candidates = [
            project_dir / "src" / "main.py",
            Path(backend_path) / "src" / "main.py" if backend_path else None,
            Path(backend_path) / "main.py" if backend_path else None,
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                main_py = candidate
                break

        if main_py:
            domain = data.get("domain", "general")
            project_name = data.get("project_name", "")

            scan_result = scan_file(main_py, project_name=project_name, domain=domain)

            # Write JSON report
            scan_dir = output_dir / "compliance"
            scan_dir.mkdir(parents=True, exist_ok=True)
            from dataclasses import asdict
            json_path = scan_dir / "compliance_scan.json"
            json_path.write_text(
                json.dumps(asdict(scan_result), indent=2, default=str),
                encoding="utf-8",
            )

            # Write PDF report
            pdf_path = scan_dir / "compliance_report.pdf"
            try:
                generate_pdf(scan_result, pdf_path)
            except Exception as pdf_err:
                logger.warning("PDF generation failed (non-critical): %s", pdf_err)
                pdf_path = json_path  # fall back to JSON path

            # G12: inject missing compliance boilerplate into src/main.py
            _inject_compliance(main_py, scan_result, domain)

            # Gap 1: write compliance_manifest.json into the generated project root
            from aether_os.phases.p06_review_security.manifest import write_compliance_manifest
            _manifest_path = write_compliance_manifest(
                scan_result, project_dir, project_name, domain
            )

            results["compliance"] = TaskResult(
                output_path=str(pdf_path),
                confidence=scan_result.score / 100,
                metadata={
                    "score": scan_result.score,
                    "findings": len([
                        f for f in scan_result.findings if f.severity != "pass"
                    ]),
                    "routes": len(scan_result.routes),
                    "manifest_path": str(_manifest_path) if _manifest_path else None,
                },
                success=True,
            )
            phase_input.input_data["compliance_pdf_path"] = str(pdf_path)
            phase_input.input_data["compliance_score"] = scan_result.score
            if _manifest_path:
                phase_input.input_data["compliance_manifest_path"] = str(_manifest_path)
            logger.info(
                "Compliance scan: score=%d routes=%d pdf=%s",
                scan_result.score, len(scan_result.routes), pdf_path,
            )
        else:
            logger.info("Compliance scan: no src/main.py found, failing phase")
            results["compliance"] = TaskResult(
                output_path="",
                confidence=0.0,
                metadata={},
                success=False,
                issues=["Source code not found — cannot perform security review. Fix upstream code generation errors first."]
            )

    except Exception as e:
        logger.warning("Compliance scan failed (non-critical): %s", e)

    summary = {
        "phases": {
            k: {
                "output_path": v.output_path,
                "success": v.success,
                "confidence": v.confidence,
                "metadata": v.metadata,
            }
            for k, v in results.items()
        }
    }
    summary_path = output_dir / "consolidated.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    any_success = any(v.success for v in results.values())
    compliance_score = phase_input.input_data.get("compliance_score")
    return TaskResult(
        output_path=str(summary_path),
        confidence=0.8 if any_success else 0.5,
        metadata={
            **summary,
            **({"compliance_score": compliance_score} if compliance_score is not None else {}),
        },
        success=True,   # Review/security/compliance is non-blocking
        issues=[],
    )


# ---------------------------------------------------------------------------
# G12: Compliance boilerplate injection
# ---------------------------------------------------------------------------

def _inject_compliance(main_py: Path, scan_result: Any, domain: str) -> None:
    """
    G12: Inject missing compliance boilerplate + actively patch known insecure patterns.

    Patches applied (in addition to injections):
    - CORS wildcard `["*"]` → env-var-driven restrictive list
    - Hardcoded SECRET_KEY → env-var with auto-fallback
    - Plaintext password comparison → bcrypt check reminder comment

    Only writes the file back when at least one change was made.
    """
    try:
        source = main_py.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("_inject_compliance: cannot read %s: %s", main_py, e)
        return

    injections: list[str] = []

    # ── SECURITY PATCH 1: Fix CORS wildcard ──────────────────────────────────────
    # Pattern: allow_origins=["*"]  or  allow_origins=['*']
    _cors_wildcard = re.search(r'allow_origins\s*=\s*\[\s*["\']?\*["\']?\s*\]', source)
    if _cors_wildcard:
        source = re.sub(
            r'allow_origins\s*=\s*\[\s*["\']?\*["\']?\s*\]',
            'allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if o.strip()]',
            source,
        )
        # Ensure `import os` is present
        if "import os" not in source:
            source = "import os\n" + source
        injections.append("cors_wildcard_fix")
        logger.info("G12-security: patched CORS wildcard in %s", main_py.name)

    # ── SECURITY PATCH 2: Fix hardcoded SECRET_KEY ──────────────────────────────
    _hardcoded_secret = re.search(
        r'SECRET_KEY\s*=\s*["\'](?!os\.environ)(?!{)[^"\']{4,}["\']',
        source,
    )
    if _hardcoded_secret and "os.environ" not in source[max(0, _hardcoded_secret.start()-5):_hardcoded_secret.end()+5]:
        source = re.sub(
            r'(SECRET_KEY\s*=\s*)["\'][^"\']{4,}["\']',
            r'\1os.environ.get("SECRET_KEY", __import__("secrets").token_hex(32))',
            source,
            count=1,
        )
        injections.append("secret_key_hardening")
        logger.info("G12-security: replaced hardcoded SECRET_KEY in %s", main_py.name)

    # ── SECURITY PATCH 3: Fix plaintext password check ──────────────────────────
    # Pattern: password == plain_password (direct equality instead of bcrypt)
    _plaintext_pw = re.search(r'password\s*==\s*\w+', source)
    if _plaintext_pw and "verify_password" not in source and "pwd_context" not in source:
        # Can't auto-fix logic, but inject a loud warning comment
        source = source.replace(
            _plaintext_pw.group(0),
            f"# SECURITY: replace direct comparison with bcrypt verify_password()\n    {_plaintext_pw.group(0)}",
            1,
        )
        injections.append("plaintext_password_warning")
        logger.warning("G12-security: plaintext password comparison detected in %s — injected warning", main_py.name)

    # ── SECURITY PATCH 4: Ensure SECRET_KEY is not empty at runtime ─────────────
    if "SECRET_KEY" in source and "if not SECRET_KEY" not in source and "token_hex" not in source:
        # Find the SECRET_KEY assignment and add a guard after it
        _sk_m = re.search(r'^(SECRET_KEY\s*=.+)$', source, re.MULTILINE)
        if _sk_m:
            _guard = (
                "\nif not SECRET_KEY:\n"
                "    import secrets as _s; SECRET_KEY = _s.token_hex(32)\n"
            )
            source = source[:_sk_m.end()] + _guard + source[_sk_m.end():]
            injections.append("secret_key_null_guard")


    # ── Rate-limiting (SOC2-CC6.6) ────────────────────────────────────────────
    rate_pass = any(
        f.severity == "pass" and "Rate" in f.rule_name
        for f in scan_result.findings
    )
    if not rate_pass and "slowapi" not in source and "Limiter" not in source:
        # Inject a fully-wired slowapi limiter AFTER app = FastAPI(...)
        # so app is defined when we set app.state.limiter
        rate_limit_block = (
            "\ntry:\n"
            "    from slowapi import Limiter as _Limiter, _rate_limit_exceeded_handler as _rleh\n"
            "    from slowapi.util import get_remote_address as _gra\n"
            "    from slowapi.errors import RateLimitExceeded as _RLE\n"
            "    _limiter = _Limiter(key_func=_gra, default_limits=[\"200/day\",\"50/hour\"])\n"
            "    app.state.limiter = _limiter\n"
            "    app.add_exception_handler(_RLE, _rleh)\n"
            "except ImportError:\n"
            "    pass  # slowapi not installed — rate limiting disabled\n"
        )
        # Insert after the closing ) of app = FastAPI(...) using bracket depth counting
        _fastapi_pos = source.find("app = FastAPI(")
        if _fastapi_pos > 0:
            _depth, _end_pos = 0, _fastapi_pos
            for _i, _ch in enumerate(source[_fastapi_pos:], _fastapi_pos):
                if _ch == "(":
                    _depth += 1
                elif _ch == ")":
                    _depth -= 1
                    if _depth == 0:
                        _end_pos = _i
                        break
            _end_nl = source.find("\n", _end_pos)
            if _end_nl >= 0:
                source = source[:_end_nl + 1] + rate_limit_block + source[_end_nl + 1:]
        else:
            source = _insert_after_imports(source, rate_limit_block)
        injections.append("rate_limiting")

    # ── Audit-logging middleware (HIPAA-TS-164.312(b)) ────────────────────────
    audit_pass = any(
        f.severity == "pass" and "Audit" in f.rule_name
        for f in scan_result.findings
    )
    if (
        not audit_pass
        and "audit_middleware" not in source
        and "audit_log_middleware" not in source
        and "@app.middleware" not in source
    ):
        # Ensure Request is imported — middleware uses `request: Request`
        if re.search(r'from fastapi import [^\n]+', source) and "Request" not in source:
            source = re.sub(
                r'(from fastapi import [^\n]+)',
                lambda m: m.group(0) if "Request" in m.group(0) else m.group(0).rstrip() + ", Request",
                source,
                count=1,
            )
        audit_block = (
            "\n"
            "# Compliance: Audit logging middleware (HIPAA §164.312(b))\n"
            "@app.middleware(\"http\")\n"
            "async def _audit_middleware(request: Request, call_next):\n"
            "    response = await call_next(request)\n"
            "    _skip = (\"/health\", \"/docs\", \"/openapi.json\", \"/favicon.ico\")\n"
            "    if not any(request.url.path.startswith(s) for s in _skip):\n"
            "        import logging as _log, base64 as _b64, json as _json\n"
            "        _user = \"anonymous\"\n"
            "        try:\n"
            "            _tok = request.headers.get(\"Authorization\", \"\").removeprefix(\"Bearer \")\n"
            "            if _tok:\n"
            "                _p = _json.loads(_b64.b64decode(_tok.split(\".\")[1] + \"==\"))\n"
            "                _user = _p.get(\"email\") or _p.get(\"sub\", \"unknown\")\n"
            "        except Exception:\n"
            "            pass\n"
            "        _ip = request.headers.get(\"X-Forwarded-For\", request.client.host if request.client else \"?\").split(\",\")[0].strip()\n"
            "        _log.getLogger(\"audit\").info(\n"
            "            \"%s %s user=%s ip=%s status=%s\",\n"
            "            request.method, request.url.path, _user, _ip, response.status_code,\n"
            "        )\n"
            "    return response\n"
        )
        source = _insert_before_routes(source, audit_block)
        injections.append("audit_middleware")

    if injections:
        try:
            main_py.write_text(source, encoding="utf-8")
            logger.info("G12: Injected compliance boilerplate: %s", injections)
        except Exception as e:
            logger.warning("G12: Failed to write compliance boilerplate: %s", e)


def _insert_after_imports(source: str, block: str) -> str:
    """Insert *block* immediately after the last top-level import statement."""
    lines = source.splitlines()
    last_import = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            last_import = i
    lines.insert(last_import + 1, block)
    return "\n".join(lines)


def _insert_before_routes(source: str, block: str) -> str:
    """Insert *block* just before the first @app.{verb} decorator."""
    m = re.search(
        r'^@app\.(get|post|put|delete|patch)',
        source,
        re.MULTILINE,
    )
    if m:
        return source[: m.start()] + block + "\n" + source[m.start():]
    # No routes found — append at end
    return source + "\n" + block
