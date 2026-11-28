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
from aether_os.phases.p00_research.stack_selector import classify_build, inject_into_brief
from aether_os.phases.p00_research.prompts import DESIGN_BRIEF_LLM_FALLBACK_PROMPT
from aether_os.phases.p00_research.business_model_generator import generate_business_model
from aether_os.core.domain_knowledge.loader import load_pack
from aether_os.core.llm import client as _llm_client
from aether_os.orchestrator.autonomy import halt_unless_approved, record_autonomous_decision, resolve_run_autonomy

try:
    from playwright.async_api import async_playwright
except ImportError:  # optional dependency; the screenshot fallback is skipped without it
    async_playwright = None

logger = logging.getLogger(__name__)
_PLAYWRIGHT_UNAVAILABLE = False

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

    # 2. Fallback: Playwright (if installed and a browser is present in this image)
    global _PLAYWRIGHT_UNAVAILABLE
    if _PLAYWRIGHT_UNAVAILABLE:
        return None
    try:
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
        if "Executable doesn't exist" in str(e):
            # The API image ships no browser (it lives in the browser sandbox image): stop trying for this process
            # instead of failing every URL of every run (KAN-219).
            _PLAYWRIGHT_UNAVAILABLE = True
            logger.info("p00: no Playwright browser in this image; screenshot fallback disabled")
        else:
            logger.warning(f"p00: Playwright fallback error: {e}")

    return None

async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    # `data` is referenced later (Gate 1 autonomous_mode check) but was never
    # bound — add a single alias at the top of the function so all downstream
    # branches resolve consistently. Bug surfaced after silencing the broad
    # exception that swallowed it.
    data = getattr(phase_input, "input_data", {}) or {}

    # Multimodal intake detection (G7)
    try:
        from aether_os.phases.p00_research.multimodal_intake import detect_and_parse_input
        raw_spec, intake_type = await detect_and_parse_input(data)
        if intake_type != "text":
            logger.info("p00: multimodal intake detected (%s), converted to text spec", intake_type)
            data = {**data, "raw_input": raw_spec}
    except Exception as exc:
        logger.warning("p00: multimodal intake failed (non-blocking): %s", exc)
        raw_spec = data.get("raw_input", "") or data.get("project_description", "")

    domain = getattr(phase_input, "domain", "general")
    # Propagate from input_data if supervisor didn't set it directly
    if domain == "general":
        domain = data.get("domain", "general")

    # Classify the build type before screenshot analysis so all downstream
    # phases know what language/architecture to target.
    raw_spec = data.get("raw_input", "") or data.get("project_description", "")
    build_profile = await classify_build(raw_spec, domain)

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
        logger.info("p00: No vision analysis results, falling back to LLM-guided design")
        analysis_prompt = DESIGN_BRIEF_LLM_FALLBACK_PROMPT.format(
            domain=domain,
            competitor_sites=", ".join(sites),
        )
        try:
            llm = _llm_client.get_llm_client()
            analysis = await llm.call_json(analysis_prompt, task_type="analysis")
            design_brief["layout_patterns"] = analysis.get("layout_patterns", {"navigation": "sticky top nav"})
            design_brief["must_have_features"] = analysis.get("must_have_features", ["search", "user profile"])
            design_brief["color_scheme"] = analysis.get("color_scheme", {"primary": "indigo-600"})
        except Exception as e:
            logger.warning(f"p00: LLM synthesis fallback failed: {e}")
            design_brief["layout_patterns"] = {"navigation": "sticky"}

    # 4. Inject build_profile and domain knowledge pack, then save artifacts
    inject_into_brief(design_brief, build_profile)
    domain_pack = load_pack(domain)
    if domain_pack:
        design_brief["domain_knowledge"] = domain_pack.to_dict()
        logger.info("p00: domain_knowledge injected for domain=%s (%d entities, %d rules)",
                    domain, len(domain_pack.entities), len(domain_pack.compliance))
    out_json = output_dir / "design_brief.json"
    out_json.write_text(json.dumps(design_brief, indent=2))

    # GATE 1: Design Brief Approval
    try:
        from aether_os.core.pipeline_state import publish_event
        from aether_os.core.decisions.decision_engine import Decision, get_decision_engine
        from aether_os.orchestrator.events import ACTIVE_RUN_ID
        from aether_os.core.errors import PipelineBlockedError
        run_id = ACTIVE_RUN_ID.get()
        # One resolver for every gate: request mode > org setting > env (KAN-248).
        autonomy = await resolve_run_autonomy(run_id, data)
        autonomous_mode = autonomy.autonomous
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
            else:
                # An unanswered gate must not fall through as approved.
                halt_unless_approved(resolved, "Gate 1 (Design Brief)")
        elif run_id:
            await record_autonomous_decision(
                run_id=run_id, org_id=data.get("org_id"), decision_type="phase_approval",
                title="Gate 1: Design Brief", phase="p00_research",
                what=f"Design brief for {domain} auto-approved.", source=autonomy.source)
    except PipelineBlockedError:
        raise
    except Exception as e:
        logger.warning(f"p00: Gate 1 approval skipped due to error: {e}")
    
    # Generate business model alongside design brief (Gap 6 — gracefully degraded)
    business_model = None
    try:
        stack_name = getattr(build_profile, "build_type", "web_app") if build_profile else "web_app"
        business_model = await generate_business_model(
            requirement=raw_spec or data.get("project_description", ""),
            domain=domain,
            stack_name=stack_name,
            output_dir=output_dir,
        )
    except Exception as exc:
        logger.warning("p00: business model step failed (non-blocking): %s", exc)

    return TaskResult(
        output_path=str(out_json),
        confidence=0.9,
        # build_profile is the full profile dict (as in design_brief.json), not its name: the s01
        # supervisor merges this metadata into the shared context, and every reader
        # (p00c, p02, p04, p05, s04, s09...) calls build_profile.get(...).
        metadata={"domain": domain, "build_profile": design_brief["build_profile"], "business_model": business_model},
        success=True,
    )
