"""P11e Gate — validates enterprise deployment artifacts (Helm, Terraform, scripts)."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

_EXPECTED_ARTIFACTS = {
    "helm": ["Chart.yaml", "values.yaml"],
    "terraform": [".tf"],
    "scripts": [".sh"],
}


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=True,
            confidence=0.4,
            issues=["Enterprise deployment artifacts not produced — Helm/Terraform/scripts missing"],
        )

    output_path = Path(result.output_path)
    all_files = list(output_path.rglob("*")) if output_path.is_dir() else [output_path]
    suffixes = {f.suffix.lower() for f in all_files if f.is_file()}
    names = {f.name for f in all_files if f.is_file()}

    has_helm = "Chart.yaml" in names
    has_terraform = ".tf" in suffixes
    has_scripts = ".sh" in suffixes

    if not has_helm:
        issues.append("Helm Chart.yaml not found — Kubernetes deployment chart missing")
    if not has_terraform:
        issues.append("No Terraform .tf files found — infrastructure-as-code missing")
    if not has_scripts:
        issues.append("No shell scripts found — operational runbooks missing")

    confidence = 0.9 if not issues else max(0.4, 0.9 - len(issues) * 0.15)
    return GateOutcome(passed=True, confidence=confidence, issues=issues)
