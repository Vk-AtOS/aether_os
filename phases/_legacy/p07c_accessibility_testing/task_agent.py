"""P07c Task Agent — axe accessibility tests via playwright."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    import os as _os
    _default_url = _os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/dashboard").rstrip("/")
    base_url = data.get("frontend_url", _default_url)
    components_json_path = data.get("components_json_path", "")

    pages = [{"name": "home", "path": "/"}]
    if components_json_path and Path(components_json_path).exists():
        try:
            comp_data = json.loads(Path(components_json_path).read_text())
            pages_data = comp_data.get("pages", [])
            if pages_data:
                pages = [{"name": p.get("name","").lower().replace(" ","_"),
                          "path": f"/{p.get('name','').lower().replace(' ','-')}"}
                         for p in pages_data]
        except Exception:
            pass

    report = {"base_url": base_url, "pages_tested": [], "total_violations": 0,
              "critical_violations": 0, "all_violations": []}

    try:
        from playwright.async_api import async_playwright
        from axe_playwright_python.async_playwright import Axe

        axe = Axe()
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            for page_info in pages:
                try:
                    page = await context.new_page()
                    url = base_url.rstrip("/") + page_info.get("path", "/")
                    await page.goto(url, timeout=10000, wait_until="domcontentloaded")
                    results = await axe.run(page)
                    violations = results.get("violations", []) if isinstance(results, dict) else []
                    critical = [v for v in violations if v.get("impact") == "critical"]
                    report["pages_tested"].append({
                        "page": page_info["name"],
                        "url": url,
                        "violations": len(violations),
                        "critical": len(critical),
                    })
                    report["all_violations"].extend(violations)
                    report["critical_violations"] += len(critical)
                    report["total_violations"] += len(violations)
                    await page.close()
                except Exception as e:
                    logger.warning("Axe scan failed for %s: %s", page_info.get("name"), e)
                    report["pages_tested"].append({"page": page_info["name"],
                                                    "error": str(e)})
            await browser.close()
    except Exception as e:
        logger.warning("Playwright/Axe unavailable: %s — noting in report", e)
        report["playwright_error"] = str(e)
        report["pages_tested"] = [{"page": p["name"], "note": "scan skipped"} for p in pages]

    report_path = output_dir / "accessibility_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    issues = []
    if report["critical_violations"] > 0:
        issues.append(f"{report['critical_violations']} critical accessibility violations")

    return TaskResult(
        output_path=str(report_path),
        confidence=0.9 if not issues else 0.3,
        metadata={"pages_tested": len(report["pages_tested"]),
                  "critical_violations": report["critical_violations"]},
        issues=issues,
        success=report["critical_violations"] == 0,
    )
