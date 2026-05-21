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

_SUBTASK_TIMEOUT = 150.0


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, TaskResult] = {}

    # Sub-task 1: Code Review
    try:
        from aether_os.phases.p05_code_review.task_agent import run as review_run
        sub_dir = output_dir / "code_review"
        r = await asyncio.wait_for(
            review_run(phase_input, memory_ctx, sub_dir), timeout=_SUBTASK_TIMEOUT
        )
        results["code_review"] = r
        logger.info("code_review completed: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("code_review timed out after %.0fs", _SUBTASK_TIMEOUT)
    except Exception as e:
        logger.warning("code_review failed (non-critical): %s", e)

    # Sub-task 2: Security Scan
    try:
        from aether_os.phases.p06_security.task_agent import run as security_run
        sub_dir = output_dir / "security"
        r = await asyncio.wait_for(
            security_run(phase_input, memory_ctx, sub_dir), timeout=_SUBTASK_TIMEOUT
        )
        results["security"] = r
        logger.info("security scan completed: %s", r.output_path)
    except asyncio.TimeoutError:
        logger.warning("security timed out after %.0fs", _SUBTASK_TIMEOUT)
    except Exception as e:
        logger.warning("security scan failed (non-critical): %s", e)

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

            results["compliance"] = TaskResult(
                output_path=str(pdf_path),
                confidence=scan_result.score / 100,
                metadata={
                    "score": scan_result.score,
                    "findings": len([
                        f for f in scan_result.findings if f.severity != "pass"
                    ]),
                    "routes": len(scan_result.routes),
                },
                success=True,
            )
            phase_input.input_data["compliance_pdf_path"] = str(pdf_path)
            phase_input.input_data["compliance_score"] = scan_result.score
            logger.info(
                "Compliance scan: score=%d routes=%d pdf=%s",
                scan_result.score, len(scan_result.routes), pdf_path,
            )
        else:
            logger.info("Compliance scan: no src/main.py found, skipping")

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
    G12: Inject missing compliance boilerplate into a generated src/main.py.

    Only injects what is actually absent — never duplicates existing blocks.
    Writes the file back only when at least one injection was made.
    """
    try:
        source = main_py.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("_inject_compliance: cannot read %s: %s", main_py, e)
        return

    injections: list[str] = []

    # ── Rate-limiting (SOC2-CC6.6) ────────────────────────────────────────────
    rate_pass = any(
        f.severity == "pass" and "Rate" in f.rule_name
        for f in scan_result.findings
    )
    if not rate_pass and "slowapi" not in source and "Limiter" not in source:
        rate_limit_block = (
            "\n"
            "# Compliance: Rate limiting (SOC2-CC6.6)\n"
            "from slowapi import Limiter, _rate_limit_exceeded_handler\n"
            "from slowapi.util import get_remote_address\n"
            "from slowapi.errors import RateLimitExceeded\n"
            "limiter = Limiter(\n"
            "    key_func=get_remote_address,\n"
            "    default_limits=[\"200/day\", \"50/hour\"],\n"
            ")\n"
        )
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
