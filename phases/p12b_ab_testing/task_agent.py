from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Implements p12b_ab_testing: A/B Testing Framework
    """
    ab_dir = output_dir / "ab_testing"
    migrations_dir = output_dir / "migrations"
    test_dir = output_dir / "tests"
    ab_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    (ab_dir / "__init__.py").write_text("")

    # A/B testing engine (standalone, JSON-file-backed persistence)
    (ab_dir / "ab_testing.py").write_text(
        '''import hashlib
import json
import os
from pathlib import Path

_EXPERIMENTS_FILE = Path(os.getenv("AB_EXPERIMENTS_PATH", "ab_experiments.json"))
_EXPERIMENTS: dict = {}


def _load() -> None:
    global _EXPERIMENTS
    if _EXPERIMENTS_FILE.exists():
        try:
            _EXPERIMENTS = json.loads(_EXPERIMENTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            _EXPERIMENTS = {}


def _save() -> None:
    try:
        _EXPERIMENTS_FILE.write_text(json.dumps(_EXPERIMENTS, indent=2), encoding="utf-8")
    except Exception:
        pass


_load()


def register(name: str, variants: list, weights: list = None):
    """Register an experiment with variant names and optional weights (must sum to 1)."""
    _EXPERIMENTS[name] = {"variants": variants, "weights": weights or [1 / len(variants)] * len(variants)}
    _save()

def get_variant(experiment: str, user_id) -> str:
    """Deterministically assign a user to a variant based on hash."""
    _load()
    if experiment not in _EXPERIMENTS:
        return "control"
    exp = _EXPERIMENTS[experiment]
    variants = exp["variants"]
    weights = exp["weights"]
    # Deterministic bucket from hash
    h = int(hashlib.md5(f"{experiment}:{user_id}".encode()).hexdigest(), 16)
    bucket = (h % 1000) / 1000.0
    cumulative = 0.0
    for variant, weight in zip(variants, weights):
        cumulative += weight
        if bucket < cumulative:
            return variant
    return variants[-1]
'''
    )

    # A/B router (standalone — consumer must include it manually)
    (ab_dir / "ab_router.py").write_text(
        '''from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from .ab_testing import register, get_variant, _EXPERIMENTS

router = APIRouter(prefix="/experiments", tags=["A/B Testing"])

class ExperimentCreate(BaseModel):
    name: str
    variants: List[str]
    weights: Optional[List[float]] = None

@router.post("/")
def create_experiment(exp: ExperimentCreate):
    register(exp.name, exp.variants, exp.weights)
    return {"name": exp.name, "variants": exp.variants}

@router.get("/")
def list_experiments():
    return {"experiments": list(_EXPERIMENTS.keys())}

@router.get("/{name}/variant/{user_id}")
def get_user_variant(name: str, user_id: str):
    variant = get_variant(name, user_id)
    return {"experiment": name, "user_id": user_id, "variant": variant}
'''
    )

    (ab_dir / "ab_results_calculator.py").write_text(
        '''import math

def chi_square_significance(control_conversions: int, control_total: int,
                             variant_conversions: int, variant_total: int) -> float:
    """Return approximate two-sided p-value using a Z-test for proportions.

    NOTE: This is a simplified approximation suitable for A/B testing dashboards.
    For rigorous statistical analysis, use scipy.stats.chi2_contingency.
    Returns 1.0 when sample sizes are insufficient for reliable inference.
    """
    if control_total < 30 or variant_total < 30:
        return 1.0  # insufficient data
    p_control = control_conversions / control_total
    p_variant = variant_conversions / variant_total
    p_pooled = (control_conversions + variant_conversions) / (control_total + variant_total)
    if p_pooled in (0.0, 1.0):
        return 1.0
    se = math.sqrt(p_pooled * (1 - p_pooled) * (1 / control_total + 1 / variant_total))
    if se == 0:
        return 1.0
    z = abs(p_variant - p_control) / se
    # Two-tailed p-value approximation via complementary error function
    # Approximation: p ≈ erfc(z / sqrt(2))
    p_value = math.erfc(z / math.sqrt(2))
    return round(min(1.0, max(0.0, p_value)), 4)
'''
    )

    (ab_dir / "experiment_hypothesis.json").write_text(
        '{"experiments": [{"name": "button_color", "hypothesis": "A green CTA button increases sign-up conversion by 10%.", "variants": ["control", "green_cta"]}]}\n'
    )

    # Migration with real SQL
    (migrations_dir / "add_ab_testing.sql").write_text(
        "CREATE TABLE IF NOT EXISTS experiments (\n"
        "  id SERIAL PRIMARY KEY,\n"
        "  name VARCHAR(100) UNIQUE NOT NULL,\n"
        "  variants JSONB NOT NULL,\n"
        "  weights JSONB,\n"
        "  active BOOLEAN DEFAULT TRUE,\n"
        "  created_at TIMESTAMPTZ DEFAULT NOW()\n"
        ");\n\n"
        "CREATE TABLE IF NOT EXISTS experiment_events (\n"
        "  id SERIAL PRIMARY KEY,\n"
        "  experiment_id INTEGER REFERENCES experiments(id),\n"
        "  user_id VARCHAR(100) NOT NULL,\n"
        "  variant VARCHAR(100) NOT NULL,\n"
        "  event_type VARCHAR(100) NOT NULL,\n"
        "  created_at TIMESTAMPTZ DEFAULT NOW()\n"
        ");\n"
    )

    (ab_dir / "INTEGRATION.md").write_text(
        "# A/B Testing Integration\n\n"
        "To add A/B testing to your FastAPI app:\n\n"
        "```python\n"
        "from ab_testing.ab_router import router as ab_router\n"
        "app.include_router(ab_router)\n"
        "```\n\n"
        "Register experiments at startup:\n\n"
        "```python\n"
        "from ab_testing.ab_testing import register\n"
        "register('button_color', ['control', 'green_cta'], [0.5, 0.5])\n"
        "```\n\n"
        "Get user variant:\n\n"
        "```python\n"
        "from ab_testing.ab_testing import get_variant\n"
        "variant = get_variant('button_color', user_id=current_user.id)\n"
        "```\n"
    )

    (test_dir / "test_ab_testing.py").write_text(
        "import sys, os\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))\n"
        "from ab_testing.ab_testing import register, get_variant\n\n"
        "def test_deterministic_assignment():\n"
        "    register('test_exp', ['a', 'b'])\n"
        "    v1 = get_variant('test_exp', 'user123')\n"
        "    v2 = get_variant('test_exp', 'user123')\n"
        "    assert v1 == v2  # same user always gets same variant\n"
        "    assert v1 in ('a', 'b')\n\n"
        "def test_unknown_experiment():\n"
        "    assert get_variant('no_such_exp', 'user1') == 'control'\n"
    )

    return TaskResult(
        output_path=str(ab_dir),
        confidence=0.9,
        metadata={"files_written": 6},
        issues=[],
        success=True
    )
