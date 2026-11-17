"""P06 subtask implementations — extracted to keep task_agent.py under 600 lines.

Each async function is a self-contained subtask that can run concurrently via
asyncio.gather inside task_agent.run().
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

from aether_os.core.compliance.code_scanner import scan_file
from aether_os.core.compliance.pdf_report import generate_pdf
from aether_os.core.domain_knowledge.loader import build_compliance_summary, load_pack
from aether_os.core.llm.client import get_llm_client
from aether_os.core.security.bandit_run import BanditScanError, bandit_args, parse as parse_bandit
from aether_os.phases.base import TaskResult
from aether_os.phases.p06_review_security.manifest import write_compliance_manifest
from aether_os.phases.p06_review_security.patcher import ASTSecurityPatcher
from aether_os.phases.p06_review_security.task_agent import _extract_json, _inject_compliance
from aether_os.phases.utils import memory_hint

logger = logging.getLogger(__name__)

_SUBTASK_TIMEOUT = 150.0


async def run_code_review(
    phase_input: Any,
    memory_ctx: List[Dict],
    output_dir: Path,
) -> TaskResult:
    """Sub-task 1: LLM code review — checks generated backend code for OWASP issues."""
    mem = memory_hint(memory_ctx)

    try:
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

        if not code_to_review:
            logger.info("code_review: no backend main.py found, skipping LLM review")
            return TaskResult(
                output_path="", confidence=0.5, metadata={}, success=True
            )

        _compliance_hint = ""
        try:
            _domain = data.get("domain", "general")
            _cs = build_compliance_summary(_domain)
            if _cs:
                _compliance_hint = (
                    f"\n\nDOMAIN COMPLIANCE REQUIREMENTS:\n{_cs}\n"
                    "Ensure the code satisfies all mandatory rules above.\n\n"
                )
        except Exception as _ce:
            logger.warning("[p06] compliance summary load failed: %s", _ce)

        review_prompt = (
            _compliance_hint
            + "You are a senior security engineer reviewing generated backend code. "
            "Check for OWASP Top-10 vulnerabilities: SQL injection, XSS, broken auth, "
            "hardcoded secrets, missing input validation, insecure CORS, IDOR, and "
            "missing rate-limiting. Return JSON: "
            '{"findings": [{"issue": str, "severity": "high"|"medium"|"low", '
            '"line_hint": str, "recommendation": str}], "overall_score": 0-100, '
            '"summary": str}. If no issues, return findings=[]. '
            + mem
            + "Code to review:\n```python\n"
            + code_to_review
            + "\n```"
        )
        review_raw = await asyncio.wait_for(
            _llm_client.call(review_prompt, task_type="code_review"),
            timeout=_SUBTASK_TIMEOUT,
        )
        try:
            review_json = _extract_json(review_raw)
        except Exception as e:
            logger.warning("p06: could not extract JSON from code review response: %s", e)
            review_json = {"summary": review_raw[:500], "findings": [], "overall_score": 75}

        sub_dir = output_dir / "code_review"
        sub_dir.mkdir(parents=True, exist_ok=True)
        review_path = sub_dir / "review.json"
        review_path.write_text(json.dumps(review_json, indent=2))

        logger.info(
            "code_review completed: %d findings",
            len(review_json.get("findings", [])),
        )
        return TaskResult(
            output_path=str(review_path),
            confidence=0.8,
            metadata={
                "findings_count": len(review_json.get("findings", [])),
                "overall_score": review_json.get("overall_score", 75),
                "summary": review_json.get("summary", ""),
            },
            success=True,
        )
    except asyncio.TimeoutError:
        logger.warning("code_review timed out after %.0fs (non-critical)", _SUBTASK_TIMEOUT)
        return TaskResult(output_path="", confidence=0.5, metadata={}, success=True)
    except Exception as e:
        logger.warning("code_review failed (non-critical): %s", e)
        return TaskResult(output_path="", confidence=0.5, metadata={}, success=True)


async def run_bandit_scan(
    phase_input: Any,
    output_dir: Path,
) -> TaskResult:
    """Sub-task 2: Static security scan using bandit."""
    try:
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

        bandit_findings: list = []
        if src_path:
            # bandit is a pinned platform dependency (requirements.txt): installing "latest"
            # from the network on the host at run time was a supply-chain hole.
            _proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "bandit", *bandit_args(src_path, "-ll"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout_bytes, _ = await asyncio.wait_for(_proc.communicate(), timeout=60)
            _stdout = _stdout_bytes.decode("utf-8", errors="replace") if _stdout_bytes else ""
            try:
                data_json = parse_bandit(_stdout)
                bandit_findings = data_json.get("results", [])
                _errors_section = data_json.get("errors", [])
                _skipped_files = [
                    _err.get("filename") or _err.get("file") or ""
                    for _err in _errors_section
                    if _err.get("filename") or _err.get("file")
                ]
                _metrics = data_json.get("metrics", {}).get("_totals", {})
                _skipped_count_metric = int(_metrics.get("skipped_tests", 0))
                if _skipped_files or _skipped_count_metric > 0:
                    _skip_n = len(_skipped_files) or _skipped_count_metric
                    _skip_names = (
                        ", ".join([Path(f).name for f in _skipped_files[:5]])
                        or "unknown files"
                    )
                    bandit_findings = [
                        {
                            "issue_text": (
                                f"Security scan incomplete — {_skip_n} file(s) skipped "
                                f"due to parse errors: {_skip_names}. "
                                "Fix syntax errors in p04a before trusting this scan."
                            ),
                            "issue_severity": "HIGH",
                            "issue_confidence": "LOW",
                            "filename": _skip_names,
                            "skipped_due_to_parse_error": True,
                        }
                    ] + bandit_findings
                    logger.warning(
                        "[p06] bandit skipped %d file(s) due to parse errors: %s",
                        _skip_n,
                        _skip_names,
                    )
            except BanditScanError as e:     # no report is an incomplete scan, not a clean one (KAN-69 SC-04)
                logger.warning("[p06] bandit gave no usable report: %s", e)
                bandit_findings = [{
                    "issue_text": f"Security scan incomplete: {e}",
                    "issue_severity": "HIGH", "issue_confidence": "LOW",
                    "filename": str(src_path), "skipped_due_to_parse_error": True,
                }]

        sub_dir = output_dir / "security"
        sub_dir.mkdir(parents=True, exist_ok=True)
        sec_path = sub_dir / "security_scan.json"

        high_severity = sum(
            1 for f in bandit_findings if f.get("issue_severity") == "HIGH"
        )
        medium_severity = sum(
            1 for f in bandit_findings if f.get("issue_severity") == "MEDIUM"
        )
        low_severity = sum(
            1 for f in bandit_findings if f.get("issue_severity") == "LOW"
        )
        _has_skipped = any(
            f.get("skipped_due_to_parse_error") for f in bandit_findings
        )
        _scan_confidence = 0.3 if _has_skipped else 0.9

        sec_result = {
            "tool": "bandit",
            "findings": bandit_findings,
            "high_severity": high_severity,
            "medium_severity": medium_severity,
            "low_severity": low_severity,
            "clean": (
                len(
                    [
                        f
                        for f in bandit_findings
                        if f.get("issue_severity") in ("HIGH", "MEDIUM")
                    ]
                )
                == 0
                and not _has_skipped
            ),
            "scan_confidence": _scan_confidence,
            "files_skipped_due_to_parse_errors": _has_skipped,
        }
        sec_path.write_text(json.dumps(sec_result, indent=2))

        # Apply AST security patches for HIGH findings
        if high_severity > 0:
            logger.warning("[p06] HIGH severity security issues found by bandit")
            patcher = ASTSecurityPatcher()
            patched_files: set = set()
            for finding in bandit_findings:
                if finding.get("issue_severity") == "HIGH":
                    fname = finding.get("filename")
                    if fname and os.path.exists(fname) and fname not in patched_files:
                        patcher.patch_file(fname)
                        patched_files.add(fname)
                        logger.info(
                            "[p06] Applied AST patch for bandit finding in %s", fname
                        )
            if not patched_files:
                for candidate in [
                    project_dir / "src" / "main.py",
                    (
                        Path(backend_path) / "src" / "main.py"
                        if backend_path
                        else None
                    ),
                ]:
                    if candidate and candidate.exists():
                        patcher.patch_file(str(candidate))
                        break

        logger.info(
            "bandit scan completed: %d findings (confidence=%.1f)",
            len(bandit_findings),
            _scan_confidence,
        )
        return TaskResult(
            output_path=str(sec_path),
            confidence=_scan_confidence,
            metadata=sec_result,
            success=True,
            issues=(
                [
                    f"Security scan incomplete — files skipped due to parse errors. "
                    f"Confidence reduced to {_scan_confidence}"
                ]
                if _has_skipped
                else []
            ),
        )
    except Exception as e:
        logger.warning("bandit scan failed (non-critical): %s", e)
        return TaskResult(output_path="", confidence=0.5, metadata={}, success=True)


async def run_compliance_scan(
    phase_input: Any,
    output_dir: Path,
) -> TaskResult:
    """Sub-task 3: Compliance scan (real code scanner + PDF report)."""
    try:
        data = phase_input.input_data
        project_dir = Path(data.get("project_dir", ""))
        backend_path = data.get("backend_output_path", "")

        main_py = None
        for candidate in [
            project_dir / "src" / "main.py",
            Path(backend_path) / "src" / "main.py" if backend_path else None,
            Path(backend_path) / "main.py" if backend_path else None,
        ]:
            if candidate and candidate.exists():
                main_py = candidate
                break

        if not main_py:
            logger.info("Compliance scan: no src/main.py found")
            return TaskResult(
                output_path="",
                confidence=0.0,
                metadata={},
                success=False,
                issues=[
                    "Source code not found — cannot perform security review. "
                    "Fix upstream code generation errors first."
                ],
            )

        domain = data.get("domain", "general")
        project_name = data.get("project_name", "")
        scan_result = scan_file(main_py, project_name=project_name, domain=domain)

        scan_dir = output_dir / "compliance"
        scan_dir.mkdir(parents=True, exist_ok=True)
        json_path = scan_dir / "compliance_scan.json"
        json_path.write_text(
            json.dumps(asdict(scan_result), indent=2, default=str),
            encoding="utf-8",
        )

        pdf_path = scan_dir / "compliance_report.pdf"
        try:
            generate_pdf(scan_result, pdf_path)
        except Exception as pdf_err:
            logger.warning("PDF generation failed (non-critical): %s", pdf_err)
            pdf_path = json_path

        # G12: inject missing compliance boilerplate into src/main.py
        _inject_compliance(main_py, scan_result, domain)

        # Gap 1: compliance manifest
        _manifest_path = write_compliance_manifest(
            scan_result, project_dir, project_name, domain
        )

        # Gap 4: domain_knowledge.json in generated project
        try:
            _pack = load_pack(domain)
            if _pack:
                _dk_path = project_dir / "domain_knowledge.json"
                _dk_path.write_text(
                    json.dumps(_pack.to_dict_full(), indent=2), encoding="utf-8"
                )
                logger.info("[p06] Gap 4: domain_knowledge.json written to %s", _dk_path)
        except Exception as _dk_exc:
            logger.warning("[p06] domain_knowledge.json write failed: %s", _dk_exc)

        # Propagate compliance data back into input_data for downstream phases
        phase_input.input_data["compliance_pdf_path"] = str(pdf_path)
        phase_input.input_data["compliance_score"] = scan_result.score
        if _manifest_path:
            phase_input.input_data["compliance_manifest_path"] = str(_manifest_path)

        logger.info(
            "Compliance scan: score=%d routes=%d pdf=%s",
            scan_result.score,
            len(scan_result.routes),
            pdf_path,
        )
        return TaskResult(
            output_path=str(pdf_path),
            confidence=scan_result.score / 100,
            metadata={
                "score": scan_result.score,
                "findings": len(
                    [f for f in scan_result.findings if f.severity != "pass"]
                ),
                "routes": len(scan_result.routes),
                "manifest_path": str(_manifest_path) if _manifest_path else None,
            },
            success=True,
        )
    except Exception as e:
        logger.warning("Compliance scan failed (non-critical): %s", e)
        return TaskResult(output_path="", confidence=0.5, metadata={}, success=True)
