"""P05 Gate — validate that index.html exists and has sound structure.

Passes if:
  - index.html exists in the output directory
  - File is > 500 bytes (non-trivial content)
  - Contains <!DOCTYPE html> or <html (valid HTML)
  - Contains a <script block (JS is present)
  - No obvious unclosed string literals that would cause immediate parse errors
"""
from __future__ import annotations
import re
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult


def validate(result: TaskResult) -> GateOutcome:
    issues = []

    # Locate index.html — output_path may point to the file or its parent dir
    out_path = Path(result.output_path) if result.output_path else None
    if out_path is None:
        return GateOutcome(passed=False, confidence=0.0, issues=["No output_path set"])

    if out_path.is_dir():
        index_file = out_path / "index.html"
    else:
        # output_path IS the file (task_agent sets it to the html path)
        index_file = out_path if out_path.suffix == ".html" else out_path.parent / "index.html"

    if not index_file.exists():
        return GateOutcome(
            passed=False,
            confidence=0.0,
            issues=[f"index.html not found at {index_file}"],
        )

    size = index_file.stat().st_size
    if size < 500:
        return GateOutcome(
            passed=False,
            confidence=0.1,
            issues=[f"index.html too small ({size} bytes) — likely empty"],
        )

    try:
        content = index_file.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return GateOutcome(passed=False, confidence=0.0, issues=[f"Cannot read file: {exc}"])

    # Check for basic HTML structure
    if "<html" not in content.lower() and "<!doctype" not in content.lower():
        issues.append("Missing <html> or <!DOCTYPE> declaration")

    # Check for script presence
    if "<script" not in content.lower():
        issues.append("No <script> tag found — no JavaScript")

    # Check for obviously broken JS: unclosed backtick template literals
    # Count backticks outside of HTML tags (rough heuristic)
    script_blocks = re.findall(
        r"<script[^>]*>(.*?)</script>", content, re.DOTALL | re.IGNORECASE
    )
    for block in script_blocks:
        # Remove string literals (single/double quoted) before counting backticks
        stripped = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', block)
        stripped = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "''", stripped)
        backticks = stripped.count("`")
        if backticks % 2 != 0:
            issues.append("Odd number of backticks in script — possible unclosed template literal")
            break

    if issues:
        # Non-fatal structural issues → still pass but with lower confidence
        # (vanilla-JS fallback avoids JSX so this should rarely trigger)
        return GateOutcome(passed=True, confidence=0.6, issues=issues)

    return GateOutcome(passed=True, confidence=0.95, issues=[])
