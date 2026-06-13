"""
P00 Domain Research Phase - Research and Pattern Extraction.
"""
from __future__ import annotations
import json
import logging
import os
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from aether_os.phases.base import TaskResult
from aether_os.phases.p00_research.domain_sites import DOMAIN_COMPETITOR_MAP
from aether_os.phases.p00_research.vision_analyzer import analyze_screenshot

logger = logging.getLogger(__name__)

async def _capture_screenshot(url: str, output_dir: Path) -> Optional[bytes]:
    """Capture a screenshot of a URL using Screenshotone API with Playwright fallback."""
    # Ensure URL has protocol
    if not url.startswith("http"):
        url = "https://" + url
        
    # 1. Primary: Screenshotone API
    api_key = os.environ.get("SCREENSHOTONE_API_KEY")
    if api_key:
        logger.info(f"p00: Capturing {url} via Screenshotone API")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Basic parameters for a clean screenshot
                params = {
                    "access_key": api_key,
                    "url": url,
                    "viewport_width": 1440,
                    "viewport_height": 900,
                    "format": "png",
                    "block_ads": "true",
                    "block_cookie_banners": "true",
                }
                resp = await client.get("https://api.screenshotone.com/take", params=params)
                if resp.status_code == 200:
                    return resp.content
                logger.warning(f"p00: Screenshotone API failed for {url}: {resp.status_code}")
        except Exception as e:
            logger.warning(f"p00: Screenshotone error for {url}: {e}")

    # 2. Fallback: Playwright (if installed and available)
    try:
        from playwright.async_api import async_playwright
        logger.info(f"p00: Capturing {url} via Playwright fallback")
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                # Wait a bit for animations/dynamic content
                await asyncio.sleep(2)
                img = await page.screenshot(type="png", full_page=False)
                await browser.close()
                return img
            except Exception as e:
                logger.warning(f"p00: Playwright failed for {url}: {e}")
                await browser.close()
    except ImportError:
        logger.debug("p00: Playwright not installed, skipping fallback")
    except Exception as e:
        logger.warning(f"p00: Playwright fallback error: {e}")

    return None

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    import os

    # `data` is referenced later (Gate 1 autonomous_mode check) but was never
    # bound — add a single alias at the top of the function so all downstream
    # branches resolve consistently. Bug surfaced after silencing the broad
    # exception that swallowed it.
    data = getattr(phase_input, "input_data", {}) or {}

    domain = getattr(phase_input, "domain", "general")
    # Propagate from input_data if supervisor didn't set it directly
    if domain == "general":
        domain = data.get("domain", "general")
        
    sites = DOMAIN_COMPETITOR_MAP.get(domain, [])

    # Unmapped domains: skip the simulated-search fallback that used to point
    # at the non-existent `top-rated-app.io` host and produced 30+ playwright
    # errors per run. With no sites we still emit a design_brief (the gate is
    # now permissive), and downstream phases use their deterministic defaults.
    if not sites:
        logger.info("p00: No pre-mapped sites for domain=%s — skipping screenshot stage", domain)

    design_brief = {
        "domain": domain,
        "competitor_sites": sites,
        "layout_patterns": {},
        "must_have_features": [],
        "customer_flows": [],
        "admin_flows": [],
        "color_scheme": {},
        "component_inventory": []
    }
    
    # 2. Pattern Extraction (Real Screenshots + Vision Analysis)
    analysis_results = []
    
    for site in sites[:3]: # Analyze top 3 sites
        img_bytes = await _capture_screenshot(site, output_dir)
        if img_bytes:
            # Save for debugging
            img_path = output_dir / f"screenshot_{site.replace('.', '_')}.png"
            img_path.write_bytes(img_bytes)
            
            logger.info(f"p00: Analyzing screenshot of {site}")
            analysis = await analyze_screenshot(domain, img_bytes)
            if not analysis.get("error"):
                analysis_results.append(analysis)
        else:
            logger.warning(f"p00: Failed to capture {site}, skipping vision analysis")

    # 3. Synthesis (Combine results or fall back to LLM-guided design)
    if analysis_results:
        logger.info(f"p00: Synthesizing {len(analysis_results)} analysis results")
        # Simplified synthesis: take the most detailed or the first successful one
        # In a production grade system, we'd use an LLM to merge them.
        design_brief["layout_patterns"] = analysis_results[0].get("layout_patterns", {})
        design_brief["must_have_features"] = list(set(f for r in analysis_results for f in r.get("must_have_features", [])))
        design_brief["color_scheme"] = analysis_results[0].get("color_scheme", {})
        # ... etc
    else:
        # LLM-guided fallback if no screenshots could be analyzed
        logger.info(f"p00: No vision analysis results, falling back to LLM-guided design")
        analysis_prompt = f"""
        Envision the design patterns for a top-tier {domain} web application.
        Think about sites like {', '.join(sites)}.
        Extract:
        1. Navigation style (e.g. sticky top nav, sidebar)
        2. Primary color family (e.g. indigo-600, slate-900)
        3. Essential customer features
        4. Key UI components (e.g. hero search, data tables, Kanban)
        Return JSON.
        """
        try:
            from aether_os.core.llm.client import get_llm_client
            llm = get_llm_client()
            analysis = await llm.call_json(analysis_prompt, task_type="analysis")
            design_brief["layout_patterns"] = analysis.get("layout_patterns", {"navigation": "sticky top nav"})
            design_brief["must_have_features"] = analysis.get("must_have_features", ["search", "user profile"])
            design_brief["color_scheme"] = analysis.get("color_scheme", {"primary": "indigo-600"})
        except Exception as e:
            logger.warning(f"p00: LLM synthesis fallback failed: {e}")
            design_brief["layout_patterns"] = {"navigation": "sticky"}

    # 4. Save artifacts
    out_json = output_dir / "design_brief.json"
    out_json.write_text(json.dumps(design_brief, indent=2))

    # GATE 1: Design Brief Approval
    try:
        from aether_os.core.pipeline_state import publish_event
        from aether_os.core.decisions.decision_engine import Decision, get_decision_engine
        from aether_os.orchestrator.events import ACTIVE_RUN_ID
        from aether_os.core.errors import PipelineBlockedError
        run_id = ACTIVE_RUN_ID.get()
        # FIX H1: Check both data and environment for autonomous mode
        autonomous_mode = (
            data.get("autonomous_mode") == True or 
            data.get("decision_mode") == "autonomous" or
            os.environ.get("AUTONOMOUS_MODE", "").lower() == "true"
        )
        if run_id and not autonomous_mode:
            logger.info("p00: Waiting for Gate 1 (Design Brief) approval...")
            engine = get_decision_engine()
            decision = Decision(
                run_id=run_id,
                org_id=data.get("org_id", ""),
                decision_type="phase_approval",
                title="Gate 1: Design Brief",
                what=f"Research complete for {domain}. Please review the design brief and submit overrides if needed.",
                why="Human sign-off required before P01 requirements intake.",
                phase="p00_research",
            )
            await engine.request_approval(decision)
            
            await publish_event(run_id, {
                "type": "PhaseApprovalRequired",
                "phase": "p00_research",
                "decision_id": decision.id,
                "data": design_brief,
                "allow_overrides": True
            })
            
            resolved = await engine.await_decision(decision.id)
            if resolved.status == "approved":
                if resolved.human_choice:
                    try:
                        # User choice can be raw text (revision request) or JSON overrides
                        if resolved.human_choice.strip().startswith("{"):
                            overrides = json.loads(resolved.human_choice)
                            design_brief["user_overrides"] = overrides
                        else:
                            design_brief["user_instructions"] = resolved.human_choice
                        out_json.write_text(json.dumps(design_brief, indent=2))
                        logger.info("p00: Applied user input to design brief")
                    except Exception:
                        logger.warning("p00: Could not parse user input from decision")
            elif resolved.status == "denied":
                raise PipelineBlockedError("Gate 1: Design Brief was denied by user.")
    except PipelineBlockedError:
        raise
    except Exception as e:
        logger.warning(f"p00: Gate 1 approval skipped due to error: {e}")
    
    return TaskResult(
        output_path=str(out_json),
        confidence=0.9,
        metadata={"domain": domain},
        success=True,
    )
