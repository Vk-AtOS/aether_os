"""P06 Task Agent — security scan with bandit + semgrep."""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    source_dir = data.get("project_dir", data.get("source_dir", ""))
    llm = get_llm_client()

    bandit_findings = []
    semgrep_findings = []

    # Run bandit
    if source_dir and Path(source_dir).exists():
        try:
            bandit_out = output_dir / "bandit_report.json"
            result = subprocess.run(
                ["bandit", "-r", source_dir, "-f", "json", "-o", str(bandit_out)],
                capture_output=True, text=True, timeout=60,
            )
            if bandit_out.exists():
                bandit_data = json.loads(bandit_out.read_text())
                bandit_findings = bandit_data.get("results", [])
            logger.info("Bandit: %d findings", len(bandit_findings))
        except Exception as e:
            logger.warning("Bandit failed: %s", e)

        # Run semgrep
        try:
            semgrep_out = output_dir / "semgrep_report.json"
            result = subprocess.run(
                ["semgrep", "--config=auto", source_dir, "--json"],
                capture_output=True, text=True, timeout=60,
            )
            try:
                semgrep_data = json.loads(result.stdout)
                semgrep_findings = semgrep_data.get("results", [])
            except Exception:
                semgrep_findings = []
            semgrep_out.write_text(json.dumps({"results": semgrep_findings}, indent=2))
            logger.info("Semgrep: %d findings", len(semgrep_findings))
        except Exception as e:
            logger.warning("Semgrep failed: %s", e)

    # If no source files to scan, do LLM-based review
    if not bandit_findings and not semgrep_findings:
        source_code = data.get("source_code", "")
        if not source_code and source_dir and Path(source_dir).exists():
            py_files = list(Path(source_dir).rglob("*.py"))[:5]
            source_code = "\n".join(f.read_text()[:1000] for f in py_files)
        if source_code:
            llm_findings = await llm.call_json(
                f"Perform security analysis. Check for: SQL injection, hardcoded secrets, "
                f"unsafe eval/exec, path traversal, command injection, weak crypto, SSRF.\n\n"
                f"Return JSON: {{\"issues\": [{{\"severity\": \"HIGH/MEDIUM/LOW\", "
                f"\"type\": str, \"description\": str, \"fix\": str}}], \"score\": 0-100}}\n\n"
                f"Code:\n{source_code[:5000]}",
                task_type="security_scan",
            )
            bandit_findings = [
                {"issue_severity": i.get("severity","LOW"),
                 "issue_text": i.get("description",""),
                 "issue_type": i.get("type",""),
                 "fix": i.get("fix","")}
                for i in llm_findings.get("issues", [])
            ]

    # Merge and classify
    all_findings = []
    for f in bandit_findings:
        all_findings.append({
            "tool": "bandit",
            "severity": f.get("issue_severity", "LOW").upper(),
            "description": f.get("issue_text", ""),
            "type": f.get("issue_type", ""),
            "file": f.get("filename", ""),
            "fix": f.get("fix", ""),
        })
    for f in semgrep_findings:
        all_findings.append({
            "tool": "semgrep",
            "severity": f.get("extra", {}).get("severity", "WARNING").upper(),
            "description": f.get("extra", {}).get("message", ""),
            "type": f.get("check_id", ""),
            "file": f.get("path", ""),
            "fix": "",
        })

    # Auto-fix HIGH findings
    high_findings = [f for f in all_findings if f["severity"] in ("HIGH", "ERROR")]
    for finding in high_findings[:3]:
        if finding.get("file") and Path(finding["file"]).exists():
            try:
                file_content = Path(finding["file"]).read_text()
                fixed = await llm.call(
                    f"Fix this security issue:\n{finding['description']}\n\n"
                    f"Code:\n{file_content[:3000]}\n\nReturn only fixed code.",
                    task_type="code_generation",
                )
                Path(finding["file"]).write_text(_strip_fences(fixed))
                finding["auto_fixed"] = True
            except Exception as e:
                logger.warning("Auto security fix failed: %s", e)

    # Re-run bandit to verify fixes
    remaining_high = []
    if source_dir and Path(source_dir).exists() and high_findings:
        try:
            result = subprocess.run(
                ["bandit", "-r", source_dir, "-f", "json"],
                capture_output=True, text=True, timeout=30,
            )
            recheck = json.loads(result.stdout) if result.stdout else {}
            remaining_high = [r for r in recheck.get("results", [])
                              if r.get("issue_severity", "").upper() == "HIGH"]
        except Exception:
            remaining_high = [f for f in high_findings if not f.get("auto_fixed")]

    # Write merged report
    report = {"findings": all_findings, "high_count": len(remaining_high),
              "total": len(all_findings), "auto_fixed": sum(1 for f in high_findings if f.get("auto_fixed"))}
    (output_dir / "security_report.json").write_text(json.dumps(report, indent=2))

    issues = []
    if remaining_high:
        issues.append(f"{len(remaining_high)} HIGH severity findings remain")

    return TaskResult(
        output_path=str(output_dir / "security_report.json"),
        confidence=0.9 if not remaining_high else 0.4,
        metadata={"total_findings": len(all_findings), "high_remaining": len(remaining_high)},
        issues=issues,
        success=len(remaining_high) == 0,
    )


def _strip_fences(code: str) -> str:
    lines = code.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
