"""P03 Gate — validate project scaffold completeness."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

def validate(result: TaskResult) -> GateOutcome:
    if not result.output_path:
        return GateOutcome(passed=False, issues=["Task did not produce output path"])
    
    project_dir = Path(result.output_path)
    issues = []
    
    # REQUIREMENT: project directory exists
    if not project_dir.exists() or not project_dir.is_dir():
        return GateOutcome(passed=False, issues=["Project directory does not exist"])
        
    # REQUIREMENT: main.py OR index.js OR app.py exists
    entry_points = ["main.py", "index.js", "app.py", "src/main.py"]
    has_entry = any((project_dir / e).exists() for e in entry_points)
    if not has_entry:
        issues.append("No entry point found (main.py, index.js, app.py)")
        
    # REQUIREMENT: requirements.txt OR package.json exists
    deps = ["requirements.txt", "package.json", "pyproject.toml"]
    has_deps = any((project_dir / d).exists() for d in deps)
    if not has_deps:
        issues.append("No dependency file found (requirements.txt, package.json)")
        
    # REQUIREMENT: At least 3 files exist total
    files = [f for f in project_dir.rglob("*") if f.is_file()]
    if len(files) < 3:
        issues.append(f"Project too sparse: only {len(files)} files created")
        
    passed = len(issues) == 0
    return GateOutcome(
        passed=passed,
        issues=issues,
        confidence=0.9 if passed else 0.3
    )
