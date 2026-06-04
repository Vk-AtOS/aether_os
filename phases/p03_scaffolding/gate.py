"""P03 Gate — validate project scaffold completeness and production standards."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    if not result.output_path:
        return GateOutcome(passed=False, issues=["Task did not produce output path"])

    project_dir = Path(result.output_path)
    issues = []
    warnings = []

    if not project_dir.exists() or not project_dir.is_dir():
        return GateOutcome(passed=False, issues=["Project directory does not exist"])

    # REQUIREMENT: entry point
    entry_points = ["main.py", "index.js", "app.py", "src/main.py"]
    if not any((project_dir / e).exists() for e in entry_points):
        issues.append("No entry point found (main.py, index.js, app.py, src/main.py)")

    # REQUIREMENT: dependency file
    deps = ["requirements.txt", "package.json", "pyproject.toml"]
    if not any((project_dir / d).exists() for d in deps):
        issues.append("No dependency file found (requirements.txt, package.json)")

    # REQUIREMENT: minimum file count
    files = [f for f in project_dir.rglob("*") if f.is_file()]
    if len(files) < 3:
        issues.append(f"Project too sparse: only {len(files)} files created")

    # WARNING: production standards (non-blocking)
    if not (project_dir / "docker-compose.yml").exists():
        warnings.append("No docker-compose.yml — add for production deployment")
    if not any((project_dir / f).exists() for f in (".env.dev", ".env.example")):
        warnings.append("No .env.dev or .env.example — add environment template")
    if not (project_dir / ".gitignore").exists():
        warnings.append("No .gitignore — secrets may be accidentally committed")

    passed = len(issues) == 0
    return GateOutcome(
        passed=passed,
        issues=issues + warnings,
        confidence=0.9 if passed else 0.3,
    )
