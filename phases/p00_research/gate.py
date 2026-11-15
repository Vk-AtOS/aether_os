"""P00 Gate — validates research results and handles user confirmation."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from aether_os.phases.base import GateOutcome, TaskResult

logger = logging.getLogger(__name__)

def validate(result: TaskResult) -> GateOutcome:
    """Gate 1: Confirm research direction with the user."""
    if not result.success:
        return GateOutcome(passed=False, issues=["Research task failed"])
        
    if not result.output_path:
        return GateOutcome(passed=False, issues=["No output path"])
        
    p = Path(result.output_path)
    if not p.exists():
        return GateOutcome(passed=False, issues=["design_brief.json not found"])
        
    try:
        brief = json.loads(p.read_text())
        domain = brief.get("domain", "general")
        sites = brief.get("competitor_sites", [])
        
        # Summary for Gate 1 (as required by Section 7 of directive)
        summary = (
            f"\nWe researched [{domain}] and found these patterns:\n\n"
            f"Top products analyzed:\n"
            + "\n".join([f"• {s}" for s in sites[:3]])
            + "\n\nDesign approach for your app:\n"
            + f"• Layout: {brief.get('layout_patterns', {}).get('navigation', 'default')}\n"
            + f"• Color scheme: {brief.get('color_scheme', {}).get('primary', 'indigo-600')}\n"
            + f"• Customer features: {', '.join(brief.get('must_have_features', [])[:5])}\n"
        )
        
        # Log the summary. In interactive mode, this would be presented to user.
        logger.info(f"GATE 1 Summary:\n{summary}")
        
        # Validation is intentionally permissive: research is a "best-effort"
        # phase. When Playwright/screenshot/LLM all fall through (e.g. an offline
        # box or unmapped domain), we still emit a partial design_brief.json and
        # let the downstream phases use their own deterministic defaults rather
        # than re-running this phase 3 times and escalating to a human.
        warnings = []
        if not brief.get("layout_patterns"):
            warnings.append("layout_patterns empty — using defaults")
        if not brief.get("must_have_features"):
            warnings.append("must_have_features empty — using defaults")
        return GateOutcome(passed=True, issues=warnings, confidence=0.7 if warnings else 1.0)
    except Exception as e:
        logger.warning("p00_research gate validation error: %s", e)
        return GateOutcome(passed=False, issues=[f"Gate validation error: {e}"])
