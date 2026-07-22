"""P05 Frontend — screenshot/preview build logic and gate-2 revision helpers."""
from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_NPM_SHARED_CACHE = Path.home() / ".aether_os" / "npm_cache"


async def take_preview_screenshot(frontend_dir: Path, output_path: Path) -> bool:
    """Attempt to capture a real screenshot of the generated frontend."""
    # 1. Ensure Playwright browsers are installed
    try:
        subprocess.run(["python3", "-m", "playwright", "install", "chromium"], capture_output=True, timeout=120)
    except Exception as exc:
        logger.debug("p05: playwright install failed (non-fatal): %s", exc)

    dist_dir = frontend_dir / "dist"
    # 2. Try building it if not already built
    if not dist_dir.exists():
        try:
            logger.info("p05: Building frontend for screenshot...")
            subprocess.run(["npm", "install", "--cache", str(_NPM_SHARED_CACHE)], cwd=str(frontend_dir), capture_output=True, timeout=240)
            subprocess.run(["npm", "run", "build"], cwd=str(frontend_dir), capture_output=True, timeout=180)
        except Exception as build_err:
            logger.warning(f"p05: Build failed before screenshot: {build_err}")

    if not dist_dir.exists():
        logger.warning("p05: dist/ directory not found, cannot take real screenshot")
        return False

    # 3. Find a free port dynamically
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            port = s.getsockname()[1]
    except Exception as e:
        logger.warning("p05_frontend preview: could not find free port, using 8888: %s", e)
        port = 8888  # fallback

    # 4. Start a temporary local server to serve the build
    server_process = subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(dist_dir)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 800})

            try:
                await asyncio.sleep(2)
                await page.goto(f"http://localhost:{port}", wait_until="networkidle", timeout=20000)
                await asyncio.sleep(3)
                await page.screenshot(path=str(output_path), full_page=True)
                logger.info(f"p05: Successfully captured preview screenshot at {output_path}")
                return True
            except Exception as e:
                logger.warning(f"p05: Playwright navigation/capture failed: {e}")
                return False
            finally:
                await browser.close()
    except Exception as e:
        logger.warning(f"p05: Playwright engine failed: {e}")
        return False
    finally:
        server_process.terminate()


_FALLBACK_CRITIQUE = (
    "Improve visual polish: tighten spacing, ensure consistent rounded corners, "
    "add visual hierarchy with font weights, remove empty placeholder sections."
)


async def vlm_rubric_critique(
    screenshot_path: Path,
    domain: str,
    project_name: str,
    timeout: float = 60.0,
) -> str:
    """Return domain-aware UI critique from LLM, or fallback string on failure."""
    if not screenshot_path.exists() or not screenshot_path.is_file():
        return _FALLBACK_CRITIQUE
    try:
        img_bytes = screenshot_path.read_bytes()
        prompt = (
            f"You are a UI/UX critic reviewing a screenshot of a generated {domain} "
            f"application called \"{project_name}\".\n"
            "Score it on 5 dimensions (1–5 each):\n"
            "1. Visual Hierarchy — clear primary/secondary/tertiary content levels\n"
            "2. Spacing — consistent padding, margins; no crowding or excessive whitespace\n"
            "3. Contrast — text legible against backgrounds; sufficient color contrast\n"
            "4. Content Richness — actual data visible (not empty tables/placeholder stats)\n"
            f"5. Domain Distinctiveness — looks like a {domain} app, not a generic grey dashboard\n\n"
            "After scoring, write 2–3 concrete, actionable improvement instructions for the React developer.\n"
            "Focus on the lowest-scoring dimensions. Be specific: mention CSS classes, component names, or layout patterns to change.\n"
            "Return ONLY the improvement instructions (no scores, no preamble)."
        )
        from aether_os.core.llm.client import get_llm_client
        client = get_llm_client()
        result = await asyncio.wait_for(
            client.call_vision(prompt, img_bytes, task_type="ui_critique", max_tokens=300),
            timeout=timeout,
        )
        if isinstance(result, str) and result.strip():
            return result.strip()
        return _FALLBACK_CRITIQUE
    except Exception as exc:
        logger.warning("p05: vlm_rubric_critique failed, using fallback: %s", exc)
        return _FALLBACK_CRITIQUE


async def apply_gate2_revisions(
    instructions: str,
    frontend_dir: Path,
    domain: str,
    project_name: str,
) -> None:
    """Use LLM to refine the customer portal based on user feedback."""
    from aether_os.phases.p05_frontend.task_agent import _generate_file

    # Identify files to refine (focus on the most visible ones)
    src_dir = frontend_dir / "src"
    candidates = [
        src_dir / "pages" / "Dashboard.tsx",
        src_dir / "components" / "DomainWidget.jsx",
        src_dir / "components" / "Layout.tsx",
    ]

    # Also include all pages in customer portal subdirectory
    customer_dir = src_dir / "pages" / "customer"
    if customer_dir.exists():
        candidates.extend(customer_dir.glob("*.tsx"))

    files_to_edit = [f for f in candidates if f.exists()]
    if not files_to_edit:
        return

    for fpath in files_to_edit:
        try:
            current_code = fpath.read_text()
            prompt = (
                f"You are a senior React developer. Refine the following component based on user feedback.\n"
                f"Feedback: {instructions}\nProject: {project_name}\nDomain: {domain}\n\n"
                f"Current Code:\n{current_code}\n\n"
                "Rules:\n- Keep the overall structure.\n"
                "- Only change visual styling (Tailwind classes) or wording to match feedback.\n"
                "- Return ONLY the updated code. No explanation. No markdown fences."
            )
            new_code = await _generate_file(fpath.name, prompt, task_type="code_refinement", timeout=90.0)
            if new_code and ("export" in new_code or "function" in new_code):
                new_code = new_code.strip()
                if new_code.startswith("```"):
                    lines = new_code.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    new_code = "\n".join(lines)
                fpath.write_text(new_code)
                logger.info("p05: Refined %s based on user feedback", fpath.name)
        except Exception as exc:
            logger.warning("p05: Failed to refine %s: %s", fpath.name, exc)
