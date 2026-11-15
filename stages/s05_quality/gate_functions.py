"""
Stage 5: Quality Gate — critical issue detection and per-file regeneration.

Extracted from supervisor.py to keep that file under the 600-line limit.

Public API consumed by supervisor.py:
  detect_critical_issues(backend_src, security_findings, critic_results) -> list[dict]
  regenerate_file(file_path, issue, domain_ir, project_name, llm) -> bool (async)
"""
from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Detects hardcoded secret literals in Python source code
_HARDCODED_SECRET_RE = re.compile(
    r'(password|api_key|secret)\s*=\s*["\'][^"\']{6,}["\']',
    re.IGNORECASE,
)


# Issue types that come from a scanner or reviewer (not a heuristic) and block delivery when unfixed.
_BLOCKING_TYPES = ("security_finding", "hardcoded_secret")


def finding_severity(finding: dict) -> str:
    """Lower-case severity of a finding: bandit writes issue_severity, the LLM review severity."""
    return str(finding.get("severity") or finding.get("issue_severity") or "").lower()


def blocking_findings(unresolved: list[dict]) -> list[str]:
    """Descriptions of unresolved High/Critical findings from a scanner or the security review."""
    return [
        i["description"] for i in unresolved
        if i.get("issue_type") in _BLOCKING_TYPES and i.get("severity") in ("high", "critical")
    ]


def detect_critical_issues(
    backend_src: Optional[Path],
    security_findings: list,
    critic_results: dict,
) -> list[dict]:
    """Scan generated backend code and security findings for critical issues.

    Returns a list of dicts:
        {"file": Path, "issue_type": str, "description": str, "severity": str}

    Never raises — returns [] on any error, logs warnings.
    """
    if backend_src is None:
        logger.warning("[s05] detect_critical_issues: backend_src is None — skipping scan")
        return []

    issues: list[dict] = []

    # ── 1. High/critical security findings from LLM security review ──────────
    for finding in security_findings:
        if not isinstance(finding, dict):
            continue
        sev = finding_severity(finding)
        desc = str(finding.get("description", finding.get("detail", "")))
        if sev in ("critical", "high") or "sql injection" in desc.lower():
            file_hint = finding.get("file", "")
            target = Path(file_hint) if file_hint else backend_src
            issues.append({
                "file": target,
                "issue_type": "security_finding",
                "description": desc or f"Severity={sev} finding from security review",
                "severity": sev or "high",
            })

    # ── 2. Per-file static analysis ────────────────────────────────────────────
    if not backend_src.exists():
        logger.warning("[s05] detect_critical_issues: backend_src does not exist: %s", backend_src)
        return issues

    py_files = [
        p for p in backend_src.rglob("*.py")
        if "__pycache__" not in str(p) and ".venv" not in str(p)
    ]

    for py_file in py_files:
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("[s05] cannot read %s for critical scan: %s", py_file, e)
            continue

        _scan_security_dimension(py_file, content, issues)
        _scan_hardcoded_secrets(py_file, content, issues)
        _scan_missing_auth(py_file, content, issues)

    return issues


def _scan_security_dimension(py_file: Path, content: str, issues: list[dict]) -> None:
    """Append a critical issue if this file's Security dimension score is below 0.5."""
    try:
        from aether_os.core.quality.dimension_scorer import score_security
        sec_score = score_security(content)
        if sec_score.score < 0.5:
            issues.append({
                "file": py_file,
                "issue_type": "security_dimension_low",
                "description": (
                    f"Security dimension score {sec_score.score:.2f} < 0.50 in {py_file.name}: "
                    + "; ".join(sec_score.findings[:2])
                ),
                "severity": "high",
            })
    except Exception as e:
        logger.warning("[s05] dimension scorer failed on %s: %s", py_file.name, e)


def _scan_hardcoded_secrets(py_file: Path, content: str, issues: list[dict]) -> None:
    """Append a critical issue if hardcoded secret literals are found."""
    if _HARDCODED_SECRET_RE.search(content) and "os.environ" not in content:
        issues.append({
            "file": py_file,
            "issue_type": "hardcoded_secret",
            "description": (
                f"Hardcoded secret literal (password/api_key/secret=) found in {py_file.name}"
            ),
            "severity": "critical",
        })


def _scan_missing_auth(py_file: Path, content: str, issues: list[dict]) -> None:
    """Append critical issues for any route decorator without a Depends( auth dependency."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return  # score_security already reports this; avoid double-report
    except Exception as e:
        logger.warning("[s05] AST parse failed for auth scan on %s: %s", py_file.name, e)
        return

    route_methods = {"get", "post", "put", "patch", "delete"}
    public_paths = {"/health", "/metrics", "/ready", "/ping"}

    try:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                    continue
                if deco.func.attr.lower() not in route_methods:
                    continue
                has_depends = any(
                    isinstance(d, ast.Call)
                    and (
                        (isinstance(d.func, ast.Name) and d.func.id == "Depends")
                        or (isinstance(d.func, ast.Attribute) and d.func.attr == "Depends")
                    )
                    for d in node.args.defaults
                )
                if not has_depends:
                    path_arg = (
                        str(deco.args[0].value)
                        if deco.args and isinstance(deco.args[0], ast.Constant)
                        else node.name
                    )
                    if path_arg not in public_paths:
                        issues.append({
                            "file": py_file,
                            "issue_type": "missing_auth",
                            "description": (
                                f"{deco.func.attr.upper()} {path_arg} in {py_file.name} "
                                "has no Depends( — missing auth dependency"
                            ),
                            "severity": "high",
                        })
    except Exception as e:
        logger.warning("[s05] AST walk for auth check failed on %s: %s", py_file.name, e)


async def regenerate_file(
    file_path: Path,
    issue: dict,
    domain_ir: dict,
    project_name: str,
    llm: Any,
) -> bool:
    """LLM-repair one file to fix the given critical issue.

    Reads current content, builds a targeted prompt, calls the LLM,
    validates syntax + security improvement, writes on success.
    Calls learn_from_repair() so the fix becomes a future auto-validator.

    Returns True on success, False on any failure.
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning("[s05] regenerate_file: cannot read %s: %s", file_path, e)
        return False

    issue_type = issue.get("issue_type", "unknown")
    description = issue.get("description", "")

    prompt = (
        f"You are a senior Python security engineer reviewing generated FastAPI code.\n\n"
        f"PROJECT: {project_name}\n"
        f"FILE: {file_path.name}\n"
        f"CRITICAL ISSUE ({issue_type}): {description}\n\n"
        f"Apply the minimal fix to eliminate this issue. Rules:\n"
        f"- If hardcoded_secret: replace literal with os.environ.get('VAR_NAME', '')\n"
        f"- If missing_auth: add current_user: dict = Depends(get_current_user) parameter\n"
        f"- If security_dimension_low: remove f-string SQL, shell=True, or other findings\n"
        f"- If security_finding: apply the security fix described\n"
        f"Return ONLY the corrected Python file content, no markdown fences.\n\n"
        f"CURRENT FILE CONTENT:\n{content}"
    )

    fixed_content: Optional[str] = None
    try:
        fixed_content = await llm.call(prompt, task_type="code_generation", max_tokens=4000)
    except Exception as e:
        logger.warning("[s05] regenerate_file: LLM call failed for %s: %s", file_path.name, e)
        return False

    if not fixed_content or not fixed_content.strip():
        logger.warning("[s05] regenerate_file: LLM returned empty content for %s", file_path.name)
        return False

    stripped = _strip_markdown_fences(fixed_content)

    # Validate syntax
    try:
        ast.parse(stripped)
    except SyntaxError as e:
        logger.warning(
            "[s05] regenerate_file: LLM result has syntax error for %s: %s", file_path.name, e
        )
        return False

    # Validate that Security dimension score improved (for security-specific issues)
    if not _security_score_improved(content, stripped, file_path.name, issue_type):
        return False

    # Write fixed content
    try:
        file_path.write_text(stripped, encoding="utf-8")
    except Exception as e:
        logger.warning("[s05] regenerate_file: write failed for %s: %s", file_path.name, e)
        return False

    _record_repair_learning(file_path, issue_type, domain_ir, project_name)
    logger.info("[s05] regenerated %s to fix %s", file_path.name, issue_type)
    return True


def _strip_markdown_fences(content: str) -> str:
    """Remove leading ```python / ``` and trailing ``` if present."""
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        return "\n".join(inner)
    return stripped


def _security_score_improved(
    original: str, fixed: str, filename: str, issue_type: str
) -> bool:
    """Return True if security score improved or issue type doesn't require improvement."""
    security_sensitive = {"security_dimension_low", "hardcoded_secret"}
    if issue_type not in security_sensitive:
        return True
    try:
        from aether_os.core.quality.dimension_scorer import score_security
        orig_score = score_security(original).score
        new_score = score_security(fixed).score
        if new_score <= orig_score:
            logger.warning(
                "[s05] regenerate_file: security score did not improve for %s "
                "(was=%.2f now=%.2f) — rejecting",
                filename, orig_score, new_score,
            )
            return False
    except Exception as e:
        logger.warning(
            "[s05] regenerate_file: score comparison failed for %s (continuing): %s", filename, e
        )
    return True


def _record_repair_learning(
    file_path: Path, issue_type: str, domain_ir: dict, project_name: str
) -> None:
    """Fire-and-forget: record this repair in the learning loop. Non-critical."""
    try:
        from aether_os.core.repair_learning import BugClass, RepairEvent, learn_from_repair

        _BUG_CLASS_MAP: dict[str, BugClass] = {
            "hardcoded_secret": BugClass.HARDCODED_SECRET,
            "missing_auth": BugClass.MISSING_AUTH,
            "security_dimension_low": BugClass.SQL_INJECTION,
            "security_finding": BugClass.SQL_INJECTION,
        }
        bug_class = _BUG_CLASS_MAP.get(issue_type, BugClass.SQL_INJECTION)
        domain = (domain_ir or {}).get("domain_name", project_name)
        event = RepairEvent(
            bug_class=bug_class,
            domain=domain,
            entity=file_path.stem,
            file_path=str(file_path),
            fix_applied=f"s05 auto-repair: {issue_type}",
        )
        learn_from_repair(event)
    except Exception as e:
        logger.warning("[s05] regenerate_file: learn_from_repair failed (non-critical): %s", e)
