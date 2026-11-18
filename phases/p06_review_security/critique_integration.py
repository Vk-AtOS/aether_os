"""
P06 dimension-critique integration — runs per-artifact critic after LLM security review.

Kept in a separate file because task_agent.py is at the 580-line limit.
Called from task_agent.py with 3 lines after the compliance sub-task completes.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from aether_os.core.run_app import safe_fs

logger = logging.getLogger(__name__)


def run_dimension_critique(
    phase_input: Any,
    accumulated_context: Dict[str, Any],
) -> None:
    """
    Run per-dimension artifact critique on the generated project src directory.

    Stores results in accumulated_context["dimension_critique"] and logs warnings
    for any artifact that fails or has critical dimension failures.

    This function is fail-open: if the critic module is unavailable or crashes,
    it logs a warning and returns without modifying accumulated_context.
    """
    try:
        from aether_os.core.quality.dimension_critic import critique_directory
    except ImportError as e:
        logger.warning("[p06/critique] dimension_critic not available (skipping): %s", e)
        return

    try:
        data = phase_input.input_data
        project_dir = data.get("project_dir", "")
        backend_path = data.get("backend_output_path", "")

        # Resolve the directory that contains the generated Python source
        src_dir: str = ""
        for candidate in [
            Path(project_dir) / "src",
            Path(backend_path) / "src" if backend_path else None,
            Path(backend_path) if backend_path else None,
            Path(project_dir),
        ]:
            if not candidate or not project_dir:
                continue
            try:  # only a real directory under the run directory (no link on the way)
                real = safe_fs.is_real_dir(project_dir, candidate.relative_to(project_dir))
            except ValueError:
                continue
            if real:
                src_dir = str(candidate)
                break

        if not src_dir:
            logger.info("[p06/critique] No source directory found — skipping dimension critique")
            return

        logger.info("[p06/critique] Running dimension critique on: %s", src_dir)
        reports = critique_directory(src_dir, root=project_dir)

        if not reports:
            logger.info("[p06/critique] No Python files found to critique in %s", src_dir)
            return

        # Warn on failing artifacts
        for report in reports:
            if not report.passed:
                logger.warning(
                    "[p06/critique] FAILED: %s (overall=%.2f, critical=%s)",
                    Path(report.artifact_path).name,
                    report.overall_score,
                    report.critical_failures,
                )
            elif report.critical_failures:
                logger.warning(
                    "[p06/critique] CRITICAL dimensions in %s: %s",
                    Path(report.artifact_path).name,
                    report.critical_failures,
                )

        # Store serializable dict in accumulated_context
        accumulated_context["dimension_critique"] = [asdict(r) for r in reports]

        # Summary stats for quick inspection
        passed = sum(1 for r in reports if r.passed)
        avg_score = sum(r.overall_score for r in reports) / len(reports) if reports else 0.0
        accumulated_context["dimension_critique_summary"] = {
            "total_artifacts": len(reports),
            "passed": passed,
            "failed": len(reports) - passed,
            "average_overall_score": round(avg_score, 4),
        }

        logger.info(
            "[p06/critique] Summary: %d/%d passed, avg_score=%.2f",
            passed,
            len(reports),
            avg_score,
        )

    except Exception as e:
        logger.warning("[p06/critique] Dimension critique failed (non-critical): %s", e)
