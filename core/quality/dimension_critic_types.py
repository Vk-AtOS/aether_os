"""
Shared data classes and constants for the AetherOS per-dimension artifact critic.

Imported by both dimension_critic.py (public API) and dimension_scorer.py (scorers).
Kept in a separate file to avoid circular imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PASSING_THRESHOLD = 0.65   # dimension score below this triggers a warning
CRITICAL_THRESHOLD = 0.40  # dimension score below this is a critical failure

# Dimension weights (must sum to 1.0)
DIMENSION_WEIGHTS: dict[str, float] = {
    "correctness":   0.25,
    "security":      0.20,
    "performance":   0.10,
    "architecture":  0.10,
    "database":      0.10,
    "api":           0.10,
    "observability": 0.10,
    "testing":       0.05,
}


# Frontend files are scored on their own three dimensions. They had no weights at all, so the
# weighted overall of every .ts/.tsx file was 0.0 and every frontend file "failed" the critique.
FRONTEND_DIMENSION_WEIGHTS: dict[str, float] = {
    "typescript_types":     0.40,
    "frontend_a11y":        0.30,
    "frontend_correctness": 0.30,
}


@dataclass
class DimensionScore:
    dimension: str
    score: float              # 0.0–1.0
    findings: list[str] = field(default_factory=list)
    passed: bool = True


@dataclass
class CritiqueReport:
    artifact_path: str
    artifact_type: str        # "backend_model", "backend_router", "seed", "schema", etc.
    dimension_scores: list[DimensionScore] = field(default_factory=list)
    overall_score: float = 0.0
    critical_failures: list[str] = field(default_factory=list)
    passed: bool = True
