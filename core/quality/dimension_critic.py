"""
Per-Dimension Artifact Critic — public API for scoring generated files on 8 engineering dimensions.

Dimensions (each 0.0–1.0, weights in dimension_critic_types.DIMENSION_WEIGHTS):
  correctness(0.25), security(0.20), performance(0.10), architecture(0.10),
  database(0.10), api(0.10), observability(0.10), testing(0.05)

PASSING_THRESHOLD = 0.65   — overall weighted score must reach this to pass
CRITICAL_THRESHOLD = 0.40  — any single dimension below this is a critical failure

Static analysis only — no LLM calls. Runs on every generated artifact, must be fast.

Scoring functions live in dimension_scorer.py to keep each file under the 600-line limit.
Data classes and constants live in dimension_critic_types.py.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

from aether_os.core.quality.dimension_critic_types import (
    CRITICAL_THRESHOLD,
    DIMENSION_WEIGHTS,
    FRONTEND_DIMENSION_WEIGHTS,
    PASSING_THRESHOLD,
    CritiqueReport,
    DimensionScore,
)
from aether_os.core.quality.dimension_scorer import (
    score_api,
    score_architecture,
    score_correctness,
    score_database,
    score_observability,
    score_performance,
    score_security,
    score_testing,
)
from aether_os.core.quality.frontend_tools import FrontendToolReport, apply_tools
from aether_os.core.quality.dimension_scorer_frontend import (
    score_frontend_a11y,
    score_frontend_correctness,
    score_typescript_types,
)

logger = logging.getLogger(__name__)

# Re-export for callers that do `from core.quality.dimension_critic import PASSING_THRESHOLD`
__all__ = [
    "critique_artifact",
    "critique_directory",
    "CritiqueReport",
    "DimensionScore",
    "PASSING_THRESHOLD",
    "CRITICAL_THRESHOLD",
]

# Ordered list of Python scorers — order affects log output only (scores are weighted by name)
_PYTHON_SCORERS = [
    score_correctness,
    score_security,
    score_performance,
    score_architecture,
    score_database,
    score_api,
    score_observability,
    score_testing,
]

# Frontend scorers for .ts/.tsx/.js/.jsx files
_FRONTEND_SCORERS = [
    score_typescript_types,
    score_frontend_a11y,
    score_frontend_correctness,
]

_FRONTEND_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")

# ---------------------------------------------------------------------------
# Artifact type detection
# ---------------------------------------------------------------------------

_ARTIFACT_TYPE_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'class \w+\(Base\)'), "backend_model"),
    (re.compile(r'APIRouter\(\)|@router\.(get|post|put|patch|delete)'), "backend_router"),
    (re.compile(r'app\s*=\s*FastAPI'), "backend_main"),
    (re.compile(r'def seed|seed_data|create_seed', re.IGNORECASE), "seed"),
    (re.compile(r'Base\.metadata|create_all|engine'), "schema"),
    (re.compile(r'import React|from react|useState|useEffect'), "frontend_component"),
]


def _detect_artifact_type(file_path: str, content: str) -> str:
    """Auto-detect artifact type from filename then content patterns."""
    name = Path(file_path).name.lower()
    if name in ("seed.py", "seed_data.py"):
        return "seed"
    if name in ("models.py", "model.py"):
        return "backend_model"
    if "router" in name or "routes" in name:
        return "backend_router"
    if name in ("main.py", "app.py"):
        return "backend_main"
    if name in ("database.py", "db.py", "schema.py"):
        return "schema"
    if name.endswith((".tsx", ".jsx")):
        return "frontend_component"
    for pattern, artifact_type in _ARTIFACT_TYPE_HINTS:
        if pattern.search(content):
            return artifact_type
    return "unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def critique_artifact(file_path: str, artifact_type: str = "", tools: Optional[FrontendToolReport] = None) -> CritiqueReport:
    """Read *file_path*, run all 8 dimension scorers, return a CritiqueReport.

    Fail-open: if the file cannot be read, returns a report with overall_score=0.0
    and passed=False so the pipeline can still gate on it.
    """
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning("[dimension_critic] Cannot read %s: %s", file_path, e)
        return CritiqueReport(
            artifact_path=file_path,
            artifact_type=artifact_type or "unknown",
            overall_score=0.0,
            critical_failures=["File unreadable"],
            passed=False,
        )

    if not artifact_type:
        artifact_type = _detect_artifact_type(file_path, content)

    is_frontend = file_path.endswith(_FRONTEND_EXTENSIONS)
    scorers = _FRONTEND_SCORERS if is_frontend else _PYTHON_SCORERS

    dimension_scores: list[DimensionScore] = []
    for scorer in scorers:
        try:
            ds = scorer(content, file_path) if is_frontend else scorer(content)
        except Exception as e:
            logger.warning(
                "[dimension_critic] scorer %s crashed on %s: %s",
                scorer.__name__, file_path, e,
            )
            ds = DimensionScore(
                dimension=scorer.__name__.replace("score_", ""),
                score=0.5,
                findings=[f"Scorer crashed (fail-open): {e}"],
                passed=True,
            )
        dimension_scores.append(ds)

    if is_frontend and tools is not None:
        tsc_msgs, eslint_msgs = tools.for_file(file_path)
        apply_tools(dimension_scores, tsc_msgs, eslint_msgs, tools.axe_violations)

    # Weighted overall score
    weights = FRONTEND_DIMENSION_WEIGHTS if is_frontend else DIMENSION_WEIGHTS
    overall = sum(
        weights.get(ds.dimension, 0.0) * ds.score
        for ds in dimension_scores
    )

    # Critical failures: any single dimension below CRITICAL_THRESHOLD
    critical_failures = [
        ds.dimension for ds in dimension_scores
        if ds.score < CRITICAL_THRESHOLD
    ]

    passed = overall >= PASSING_THRESHOLD and not critical_failures

    report = CritiqueReport(
        artifact_path=file_path,
        artifact_type=artifact_type,
        dimension_scores=dimension_scores,
        overall_score=round(overall, 4),
        critical_failures=critical_failures,
        passed=passed,
    )

    if not passed or critical_failures:
        logger.warning(
            "[dimension_critic] %s FAILED critique (overall=%.2f, critical=%s)",
            Path(file_path).name,
            overall,
            critical_failures,
        )

    return report


def critique_directory(output_dir: str, tools: Optional[FrontendToolReport] = None) -> list[CritiqueReport]:
    """Walk *output_dir*, auto-detect artifact types, critique each .py file.

    Returns one CritiqueReport per file. Non-Python files are skipped.
    __pycache__, .venv, and node_modules directories are excluded.
    """
    reports: list[CritiqueReport] = []
    base = Path(output_dir)

    if not base.exists():
        logger.warning("[dimension_critic] critique_directory: path does not exist: %s", output_dir)
        return reports

    _exclude_dirs = {"__pycache__", ".venv", "node_modules"}

    def _should_include(p: Path) -> bool:
        return not any(part in _exclude_dirs for part in p.parts)

    py_files = [p for p in base.rglob("*.py") if _should_include(p)]
    fe_files = [
        p for ext in _FRONTEND_EXTENSIONS
        for p in base.rglob(f"*{ext}")
        if _should_include(p)
    ]
    all_files = sorted(set(py_files + fe_files))

    logger.info(
        "[dimension_critic] Critiquing %d files (%d py, %d frontend) in %s",
        len(all_files), len(py_files), len(fe_files), output_dir,
    )

    for source_file in all_files:
        try:
            report = critique_artifact(str(source_file), tools=tools)
            reports.append(report)
        except Exception as e:
            logger.warning("[dimension_critic] Failed to critique %s: %s", source_file, e)

    passed_count = sum(1 for r in reports if r.passed)
    logger.info(
        "[dimension_critic] Critique complete: %d/%d artifacts passed (threshold=%.0f%%)",
        passed_count,
        len(reports),
        PASSING_THRESHOLD * 100,
    )

    return reports
