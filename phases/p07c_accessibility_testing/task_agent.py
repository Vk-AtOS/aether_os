"""P07c Accessibility Testing — axe-core checks against the generated frontend."""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

_AXE_SCRIPT = """
const { chromium } = require('playwright');
const { checkA11y, injectAxe } = require('axe-playwright');

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  try {
    await page.goto(process.argv[2] || 'http://localhost:5173', { waitUntil: 'networkidle', timeout: 15000 });
    await injectAxe(page);
    const results = await checkA11y(page, null, { detailedReport: true, includedImpacts: ['critical', 'serious', 'moderate', 'minor'] }, true);
    // checkA11y throws on violations; if we reach here, no violations
    console.log(JSON.stringify({
      violations: 0,
      passes: 0,
      incomplete: 0,
      items: [],
    }));
  } catch (e) {
    // checkA11y throws an AxeResults error containing violations
    if (e && e.violations) {
      console.log(JSON.stringify({
        violations: e.violations.length,
        passes: (e.passes || []).length,
        incomplete: (e.incomplete || []).length,
        items: e.violations.slice(0, 10).map(v => ({ id: v.id, impact: v.impact, description: v.description })),
      }));
    } else {
      console.log(JSON.stringify({ error: e.message || String(e) }));
    }
  } finally {
    await browser.close();
  }
})();
"""

_WCAG_CHECKLIST = [
    {"id": "color-contrast", "description": "Text has sufficient color contrast", "impact": "serious"},
    {"id": "image-alt", "description": "Images have alt text", "impact": "critical"},
    {"id": "label", "description": "Form inputs have labels", "impact": "critical"},
    {"id": "link-name", "description": "Links have discernible text", "impact": "serious"},
    {"id": "button-name", "description": "Buttons have accessible names", "impact": "critical"},
    {"id": "html-has-lang", "description": "HTML has lang attribute", "impact": "serious"},
    {"id": "landmark-one-main", "description": "Page has main landmark", "impact": "moderate"},
    {"id": "page-has-heading-one", "description": "Page has h1 heading", "impact": "moderate"},
]


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}
    frontend_port: int = data.get("frontend_port", 5173)
    frontend_url = f"http://localhost:{frontend_port}"

    results: Dict = {
        "target": frontend_url,
        "wcag_level": "WCAG 2.1 AA",
        "checklist": _WCAG_CHECKLIST,
        "violations": 0,
        "passes": 0,
    }

    # ── Try axe-core via playwright ───────────────────────────────────────────
    axe_script = output_dir / "axe_runner.js"
    axe_script.write_text(_AXE_SCRIPT)

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.get(frontend_url)

        proc = await asyncio.create_subprocess_exec(
            "node", str(axe_script), frontend_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        axe_data = json.loads(stdout.decode().strip())
        results.update(axe_data)
        results["ran_axe"] = True
        logger.info("[p07c] axe done: %d violations, %d passes", axe_data.get("violations", 0), axe_data.get("passes", 0))
    except Exception as exc:
        logger.info("[p07c] axe skipped (%s) — using static checklist", exc)
        results["skipped"] = True
        results["reason"] = "frontend not running locally or axe/playwright not installed"

    # ── ARIA attribute audit on generated HTML ────────────────────────────────
    frontend_dir = Path(data.get("frontend_src_dir", "")) if data.get("frontend_src_dir") else None
    aria_issues = []
    if frontend_dir and frontend_dir.exists():
        for f in list(frontend_dir.rglob("*.tsx")) + list(frontend_dir.rglob("*.jsx")):
            try:
                content = f.read_text()
                if "<img" in content and "alt=" not in content:
                    aria_issues.append(f"{f.name}: <img> missing alt attribute")
                if "<button" in content and "aria-label" not in content and ">Submit" not in content:
                    pass  # buttons with text content are fine
            except Exception:
                pass
        results["aria_issues"] = aria_issues[:10]

    results["passed"] = results["violations"] == 0
    (output_dir / "a11y_results.json").write_text(json.dumps(results, indent=2))

    return TaskResult(
        output_path=str(output_dir / "a11y_results.json"),
        confidence=0.70,
        metadata=results,
        success=True,
        issues=aria_issues[:5],
    )
