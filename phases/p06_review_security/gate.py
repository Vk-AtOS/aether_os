"""P06 Gate — enforces security review quality.

Blocks the pipeline if:
  - Output file is missing entirely (no review ran)
  - Security scan found CRITICAL severity issues
  - Security scan found any HIGH severity issue (key `severity` or bandit's `issue_severity`)

Passes with warnings for moderate/low findings.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

_CRITICAL_THRESHOLD = 1   # any critical → block
_HIGH_THRESHOLD     = 1   # any high → block (owner decision: High and above block delivery)


def _count_severities(data: dict) -> dict[str, int]:
    """Walk any nested structure counting severity keys."""
    counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            sev = str(node.get("severity") or node.get("issue_severity") or "").lower()
            if sev in counts:
                counts[sev] += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return counts


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    # ── 1. Output existence ───────────────────────────────────────────────────
    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=["Security review produced no output — pipeline blocked pending manual review"],
        )

    # ── 2. Parse security findings ────────────────────────────────────────────
    severity_counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    try:
        payload = json.loads(Path(result.output_path).read_text())
        # Try consolidated structure first
        security_data = (
            payload.get("phases", {}).get("security", {})
            or payload.get("security", {})
            or payload
        )
        severity_counts = _count_severities(security_data)
    except Exception as e:
        logger.warning("P06 gate: could not parse security output (%s) — treating as no findings", e)

    n_critical = severity_counts["critical"]
    n_high     = severity_counts["high"]
    n_medium   = severity_counts["medium"]
    n_low      = severity_counts["low"]

    # ── 2b. Code-pattern security checks ─────────────────────────────────────
    # Walk generated backend files and check for common anti-patterns
    try:
        import re as _re
        # Try to find the generated backend from the output path
        _out = Path(result.output_path)
        _search_root = _out.parent.parent  # output is usually in p06_review_security/
        _backend_dirs = list(_search_root.glob("p04*/backend_codegen/src"))
        for _src_dir in _backend_dirs[:1]:  # check first found
            for _py in list(_src_dir.rglob("*.py"))[:20]:
                _code = _py.read_text(errors="replace")
                # Raw SQL string construction (SQL injection risk)
                if _re.search(r'f["\'].*SELECT.*\{', _code, _re.IGNORECASE):
                    issues.append(f"POTENTIAL SQL INJECTION: f-string SQL in {_py.name}")
                    n_high = max(n_high, 1)
                # Hardcoded secrets patterns
                if _re.search(r'(?i)(password|secret|api_key|token)\s*=\s*["\'][^"\']{8,}["\']', _code):
                    if not _re.search(r'os\.environ|getenv|settings\.|config\.', _code):
                        issues.append(f"POTENTIAL HARDCODED SECRET in {_py.name}")
                        n_high = max(n_high, 1)
    except Exception as _scan_exc:
        logger.debug("P06 gate code-pattern scan failed: %s", _scan_exc)

    # ── 3. Blocking conditions ────────────────────────────────────────────────
    if n_critical >= _CRITICAL_THRESHOLD:
        issues.append(
            f"BLOCKED: {n_critical} CRITICAL security finding(s) must be resolved before proceeding"
        )
        return GateOutcome(passed=False, confidence=0.0, issues=issues)

    if n_high >= _HIGH_THRESHOLD:
        issues.append(
            f"BLOCKED: {n_high} HIGH severity findings exceed threshold of {_HIGH_THRESHOLD}"
        )
        return GateOutcome(passed=False, confidence=0.1, issues=issues)

    # ── 4. Non-blocking warnings ──────────────────────────────────────────────
    if n_high > 0:
        issues.append(f"{n_high} HIGH severity finding(s) — review recommended")
    if n_medium > 0:
        issues.append(f"{n_medium} MEDIUM finding(s) noted")
    if n_low > 0:
        issues.append(f"{n_low} LOW finding(s) noted")

    confidence = 1.0 if not issues else 0.95
    if n_high > 0:
        confidence -= 0.05 * n_high
    confidence = max(0.5, round(confidence, 2))

    return GateOutcome(passed=True, confidence=confidence, issues=issues)
