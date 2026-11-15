"""P06 Consolidated Task Agent — code review + security scan + compliance scan."""
from __future__ import annotations
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

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

    # Sub-tasks 1, 2, and 3 run concurrently — bandit and compliance scan are
    # independent of the LLM review, cutting p06 wall-clock time by ~60%.
    from aether_os.phases.p06_review_security.subtasks import (
        run_code_review,
        run_bandit_scan,
        run_compliance_scan,
    )
    gathered = await asyncio.gather(
        run_code_review(phase_input, memory_ctx, output_dir),
        run_bandit_scan(phase_input, output_dir),
        run_compliance_scan(phase_input, output_dir),
        return_exceptions=True,
    )
    review_result, bandit_result, compliance_result = gathered

    results: Dict[str, TaskResult] = {}
    for key, res in [
        ("code_review", review_result),
        ("static_analysis", bandit_result),
        ("compliance", compliance_result),
    ]:
        if isinstance(res, Exception):
            logger.warning("[p06] %s subtask raised exception (non-fatal): %s", key, res)
        elif isinstance(res, TaskResult) and res.output_path:
            results[key] = res

    # Sub-task 2b: Domain rules + secret detection + pip-audit (CodeScanner)
    try:
        from aether_os.core.security.code_scanner import CodeScanner
        _scanner = CodeScanner()
        _sec_data = phase_input.input_data
        _sec_project_dir = _sec_data.get("project_dir", "")
        _sec_domain = _sec_data.get("domain", "general")
        if _sec_project_dir and Path(_sec_project_dir).exists():
            _scan_res = await _scanner.scan_project(_sec_project_dir, _sec_domain)
            _extra_findings = [
                {"rule_id": f.rule_id, "severity": f.severity, "message": f.message, "file": f.file_path}
                for f in _scan_res.findings
            ]
            (output_dir / "security").mkdir(parents=True, exist_ok=True)
            (output_dir / "security" / "extended_scan.json").write_text(
                json.dumps({"domain": _sec_domain, "findings": _extra_findings, "passed": _scan_res.passed}, indent=2)
            )
            logger.info("[p06] CodeScanner: %d domain/secret/pip-audit findings", len(_extra_findings))
    except Exception as _cs_exc:
        logger.warning("[p06] CodeScanner extended scan failed (non-fatal): %s", _cs_exc)

    # Sub-task 4: Per-dimension artifact critique (static analysis, fail-open)
    _accumulated: dict = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    try:
        from aether_os.phases.p06_review_security.critique_integration import run_dimension_critique
        run_dimension_critique(phase_input, _accumulated)
    except Exception as _ce:
        logger.warning("[p06] dimension critique wiring failed (non-critical): %s", _ce)

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


from aether_os.phases.p06_review_security.patcher import insert_after_imports as _insert_after_imports, insert_before_routes as _insert_before_routes
