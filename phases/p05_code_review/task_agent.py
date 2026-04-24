"""P05 Task Agent — code review with aider + Claude."""
from __future__ import annotations
import logging
import subprocess
import json
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)

SEVERITY_LEVELS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    source_dirs = data.get("source_dirs", [])
    if not source_dirs:
        source_dir = data.get("project_dir", "")
        if source_dir:
            source_dirs = [source_dir]
    llm = get_llm_client()

    # Collect all source files
    all_files: List[Path] = []
    for sd in source_dirs:
        p = Path(sd)
        if p.exists():
            all_files.extend(p.rglob("*.py"))
            all_files.extend(p.rglob("*.ts"))
            all_files.extend(p.rglob("*.js"))
    all_files = all_files[:20]  # Cap at 20 files per review

    report_path = output_dir / "review_report.md"
    findings = []

    # Try aider non-interactive review
    aider_used = False
    if all_files:
        try:
            file_args = [str(f) for f in all_files]
            result = subprocess.run(
                ["aider", "--no-git", "--yes", "--model", "claude-sonnet-4-6",
                 "--message",
                 "Review this code for: 1.Logic errors 2.Security vulnerabilities "
                 "3.Performance issues 4.Code duplication 5.Missing error handling. "
                 "Format each finding as: [SEVERITY] description. "
                 "Write findings to review_report.md",
                 *file_args],
                capture_output=True, text=True, timeout=120,
                cwd=str(output_dir),
            )
            aider_used = result.returncode == 0
        except Exception as e:
            logger.info("Aider unavailable: %s — using direct LLM review", e)

    # Direct LLM review (always run to ensure quality)
    combined_code = ""
    for f in all_files[:10]:
        try:
            combined_code += f"\n\n# File: {f.name}\n{f.read_text()[:1500]}"
        except Exception:
            pass

    if combined_code:
        review_json = await llm.call_json(
            f"Review this code. For each issue return: severity (CRITICAL/HIGH/MEDIUM/LOW), "
            f"type, description, fix. Also return overall_quality (0-10).\n\n"
            f"Code:\n{combined_code[:6000]}",
            task_type="code_generation",
        )
        findings = review_json.get("findings", review_json.get("issues", []))
        quality = review_json.get("overall_quality", 7)
    else:
        findings = []
        quality = 8

    # Apply CRITICAL and HIGH fixes automatically
    critical_high = [f for f in findings
                     if isinstance(f, dict) and f.get("severity", "").upper() in ("CRITICAL", "HIGH")]
    for issue in critical_high[:3]:
        fix_hint = issue.get("fix", "")
        if fix_hint and all_files:
            for src_file in all_files[:3]:
                try:
                    old_content = src_file.read_text()
                    fixed = await llm.call(
                        f"Fix this {issue.get('severity')} issue in the code:\n"
                        f"Issue: {issue.get('description','')}\n"
                        f"Fix hint: {fix_hint}\n\n"
                        f"Code:\n{old_content[:3000]}\n\n"
                        f"Return only the fixed code, no explanation.",
                        task_type="code_generation",
                    )
                    src_file.write_text(_strip_fences(fixed))
                    logger.info("Auto-fixed %s issue in %s", issue.get("severity"), src_file.name)
                    break
                except Exception as e:
                    logger.warning("Auto-fix failed: %s", e)

    # Write report
    md = [f"# Code Review Report\n\n**Overall Quality:** {quality}/10\n\n## Findings\n"]
    for f in findings:
        if isinstance(f, dict):
            md.append(f"### [{f.get('severity','?')}] {f.get('type','Issue')}")
            md.append(f"**Description:** {f.get('description','')}")
            md.append(f"**Fix:** {f.get('fix','')}\n")
    report_path.write_text("\n".join(md))

    critical_count = len([f for f in findings
                          if isinstance(f, dict) and f.get("severity","").upper() == "CRITICAL"])
    issues = []
    if critical_count > 0:
        issues.append(f"{critical_count} CRITICAL issues remain in review report")

    return TaskResult(
        output_path=str(report_path),
        confidence=min(quality / 10.0, 0.95),
        metadata={"findings": len(findings), "critical": critical_count,
                  "quality_score": quality, "aider_used": aider_used},
        issues=issues,
        success=critical_count == 0,
    )


def _strip_fences(code: str) -> str:
    lines = code.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
