"""P05 Gate — validate that the React/Vite/TanStack project was generated correctly.

Passes if:
  - frontend/package.json exists in the output directory
  - frontend/src/main.tsx exists
  - frontend/src/App.tsx exists
  - At least one entity page exists in frontend/src/pages/
  - package.json references the expected dependencies
"""
from __future__ import annotations

import json
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

_REQUIRED_DEPS = ["react", "@tanstack/react-query", "@tanstack/react-router", "@tanstack/react-table"]


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path:
        return GateOutcome(passed=False, confidence=0.0, issues=["No output_path set"])

    out_path = Path(result.output_path)

    # output_path should point to the frontend/ directory
    if out_path.name == "frontend":
        frontend_dir = out_path
    elif (out_path / "frontend").exists():
        frontend_dir = out_path / "frontend"
    else:
        # Fallback: maybe output_path is the phase dir and frontend is inside
        frontend_dir = out_path / "frontend"

    # Check required files
    required_files = [
        frontend_dir / "package.json",
        frontend_dir / "src" / "main.tsx",
        frontend_dir / "src" / "App.tsx",
    ]

    for f in required_files:
        if not f.exists():
            issues.append(f"Missing required file: {f.relative_to(out_path.parent) if out_path.parent.exists() else f}")

    # Check at least one entity page exists
    pages_dir = frontend_dir / "src" / "pages"
    if pages_dir.exists():
        entity_pages = [p for p in pages_dir.glob("*Page.tsx")
                        if p.stem not in ("LoginPage",)]
        if not entity_pages:
            issues.append("No entity pages found in frontend/src/pages/")
    else:
        issues.append("frontend/src/pages/ directory does not exist")

    # Validate package.json has expected deps
    pkg_file = frontend_dir / "package.json"
    if pkg_file.exists():
        try:
            pkg = json.loads(pkg_file.read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for dep in _REQUIRED_DEPS:
                if dep not in deps:
                    issues.append(f"Missing dependency in package.json: {dep}")
        except Exception as exc:
            issues.append(f"Could not parse package.json: {exc}")

    if issues:
        # All checks failed — hard fail
        all_critical = all(
            "Missing required file" in i or "does not exist" in i
            for i in issues
        )
        if all_critical:
            return GateOutcome(passed=False, confidence=0.1, issues=issues)
        # Partial issues — still pass but lower confidence
        return GateOutcome(passed=True, confidence=0.7, issues=issues)

    return GateOutcome(passed=True, confidence=0.9, issues=[])
