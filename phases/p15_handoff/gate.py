"""P15 Gate — validates technical delivery package is complete (docs, runbook, Postman)."""
from __future__ import annotations
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

_REQUIRED_DOCS = {"readme", "architecture", "api", "runbook"}


def validate(result: TaskResult) -> GateOutcome:
    issues: list[str] = []

    if not result.output_path or not Path(result.output_path).exists():
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=["Handoff package not produced — delivery documentation is missing"],
        )

    output_path = Path(result.output_path)
    all_files = list(output_path.rglob("*")) if output_path.is_dir() else [output_path]
    file_names_lower = {f.name.lower() for f in all_files if f.is_file()}
    rel_paths_lower = {f.relative_to(output_path).as_posix().lower() for f in all_files if f.is_file()} \
        if output_path.is_dir() else set()

    missing_docs = []
    for doc in _REQUIRED_DOCS:
        if not any(doc in name for name in file_names_lower):
            missing_docs.append(doc.upper())
    if missing_docs:
        issues.append(f"Missing handoff documents: {', '.join(missing_docs)}")

    # Check for Postman collection
    # the collection is written as postman/collection.json: the folder, not the file name, says "postman"
    has_postman = any("postman" in p for p in rel_paths_lower | file_names_lower)
    if not has_postman:
        issues.append("Postman collection not found in handoff package")

    # Verify docs have meaningful content (not empty)
    for f in all_files:
        if f.is_file() and f.suffix in (".md", ".json") and f.stat().st_size < 100:
            issues.append(f"Handoff file appears empty: {f.name}")

    passed = len(missing_docs) == 0
    confidence = 0.95 if not issues else max(0.3, 0.95 - len(issues) * 0.2)
    return GateOutcome(passed=passed, confidence=confidence, issues=issues)
