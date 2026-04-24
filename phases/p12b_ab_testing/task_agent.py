"""P12b Task Agent — GrowthBook A/B experiments."""
from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Any, Dict, List
from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client
logger = logging.getLogger(__name__)

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    project_dir = Path(data.get("project_dir", str(output_dir)))
    requirements_doc = data.get("requirements_doc", "")
    llm = get_llm_client()

    # docker-compose.growthbook.yml
    gb_compose = """version: '3.8'
services:
  growthbook:
    image: growthbook/growthbook:latest
    environment:
      - MONGODB_URI=mongodb://growthbook-mongo/growthbook
      - APP_ORIGIN=http://localhost:3100
      - API_HOST=http://localhost:3100
    ports: ["3100:3000", "3101:3100"]
    depends_on: [growthbook-mongo]
  growthbook-mongo:
    image: mongo:7
    volumes:
      - growthbook_mongo:/data/db
volumes:
  growthbook_mongo:
"""
    (project_dir / "docker-compose.growthbook.yml").write_text(gb_compose)

    # Generate experiment definitions
    def calc_sample_size(baseline_rate=0.1, mde=0.05, power=0.8, alpha=0.05) -> int:
        import math
        z_alpha = 1.96  # two-tailed, alpha=0.05
        z_beta = 0.84   # power=0.8
        p1 = baseline_rate
        p2 = baseline_rate * (1 + mde)
        n = ((z_alpha * (2*p1*(1-p1))**0.5 + z_beta * (p1*(1-p1)+p2*(1-p2))**0.5) / (p2-p1))**2
        return math.ceil(n)

    experiments_json = await llm.call_json(
        f"Define 2 A/B experiments for this product:\n{requirements_doc[:1000]}\n\n"
        f"Return JSON list of 2 experiments: [{{name, hypothesis, control_variant, "
        f"treatment_variant, success_metric, tracking_event, expected_lift_pct}}]",
        task_type="requirements",
    )
    if isinstance(experiments_json, list):
        experiments = experiments_json
    else:
        experiments = experiments_json.get("experiments", [
            {"name": "onboarding_flow_v2", "hypothesis": "Simplified onboarding increases completion",
             "control_variant": "current", "treatment_variant": "simplified",
             "success_metric": "onboarding_completed", "tracking_event": "user_completed_onboarding",
             "expected_lift_pct": 5},
            {"name": "cta_button_colour", "hypothesis": "Green CTA increases conversions",
             "control_variant": "blue", "treatment_variant": "green",
             "success_metric": "cta_clicked", "tracking_event": "cta_button_clicked",
             "expected_lift_pct": 10},
        ])

    sample_size = calc_sample_size()
    for exp in experiments:
        exp["sample_size_per_variant"] = sample_size
        exp["significance_level"] = 0.05
        exp["statistical_power"] = 0.80

    exp_config = output_dir / "experiments_config.json"
    exp_config.write_text(json.dumps({"experiments": experiments}, indent=2))

    # GrowthBook SDK integration
    gb_code = """
import os
from growthbook import GrowthBook

def get_gb_instance(user_id: str, attributes: dict = None) -> GrowthBook:
    features = {}  # In production, fetch from GrowthBook API
    gb = GrowthBook(
        api_host=os.getenv("GROWTHBOOK_API_HOST", "http://localhost:3100"),
        client_key=os.getenv("GROWTHBOOK_KEY", ""),
        attributes={"id": user_id, **(attributes or {})},
        features=features,
    )
    return gb

def get_experiment_variant(user_id: str, experiment_id: str,
                           control: str = "control", treatment: str = "treatment") -> str:
    gb = get_gb_instance(user_id)
    result = gb.run({"key": experiment_id, "variations": [control, treatment]})
    return result.value if result.inExperiment else control
"""
    gb_file = project_dir / "src" / "ab_testing.py"
    gb_file.parent.mkdir(parents=True, exist_ok=True)
    gb_file.write_text(gb_code)

    # Update .env.example
    env_ex = project_dir / ".env.example"
    if env_ex.exists():
        content = env_ex.read_text()
        if "GROWTHBOOK" not in content:
            env_ex.write_text(content + "\n# GrowthBook\nGROWTHBOOK_KEY=\nGROWTHBOOK_API_HOST=http://localhost:3100\n")

    issues = []
    if len(experiments) < 2:
        issues.append(f"Only {len(experiments)} experiments (need 2)")
    if not gb_file.exists():
        issues.append("ab_testing.py not written")

    return TaskResult(
        output_path=str(gb_file),
        confidence=0.9 if not issues else 0.5,
        metadata={"experiments": [e["name"] for e in experiments], "sample_size": sample_size},
        issues=issues,
        success=len(experiments) >= 2,
    )
