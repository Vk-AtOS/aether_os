"""P05 Frontend — screenshot/preview build logic and gate-2 revision helpers."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aether_os.core.run_app import safe_fs
from aether_os.core.sandbox import phase_exec
from aether_os.core.sandbox.browser_job import run_browser_job
from aether_os.core.sandbox.runner import SandboxUnavailable, sandbox_dirs
from aether_os.phases.p05_frontend.npm_runner import PREVIEW_BUILD_ENV

logger = logging.getLogger(__name__)

_NPM_SHARED_CACHE = Path.home() / ".aether_os" / "npm_cache"
_PREVIEW_PORT = 4173   # on the browser sandbox's own loopback


async def take_preview_screenshot(frontend_dir: Path, output_path: Path) -> bool:
    """Capture a real screenshot of the generated frontend.

    Chromium runs the generated JavaScript, so it never runs on the platform host (KAN-99): the build is
    served and screenshotted by the browser sandbox (core/sandbox/browser_job.py), on that container's own
    loopback, with no network. No browser sandbox (no Docker, image not built) means no screenshot, never a
    host browser.
    """
    dist_dir = frontend_dir / "dist"
    # 1. Try building it if not already built
    if not dist_dir.exists():
        try:
            logger.info("p05: Building frontend for screenshot...")
            # Generated project: install (install egress profile) and build in the sandbox only.
            await phase_exec.run(["npm", "install"], cwd=frontend_dir, timeout=240, network=True)
            await phase_exec.run(["npm", "run", "build"], cwd=frontend_dir, timeout=180, env=PREVIEW_BUILD_ENV)
        except SandboxUnavailable:
            raise
        except Exception as build_err:
            logger.warning(f"p05: Build failed before screenshot: {build_err}")

    if not dist_dir.exists():
        logger.warning("p05: dist/ directory not found, cannot take real screenshot")
        return False

    # 2. The preview build lives under a base path; the in-sandbox server serves dist/ under that name.
    base = PREVIEW_BUILD_ENV["VITE_BASE_PATH"].strip("/")
    root = phase_exec.project_root(frontend_dir)
    shot = Path(sandbox_dirs(root)["TMPDIR"]) / "preview.png"
    job = {"action": "screenshot", "out": str(shot),
           "serve": {"dir": str(dist_dir), "port": _PREVIEW_PORT, "base": base},
           "url": f"http://127.0.0.1:{_PREVIEW_PORT}/" + (base + "/" if base else "")}
    try:
        result = await run_browser_job(job, project=frontend_dir, timeout=120)
    except SandboxUnavailable as exc:
        logger.error("p05: no screenshot, the browser sandbox is unavailable: %s", exc)
        return False
    except Exception as exc:
        logger.warning("p05: browser job failed: %s", exc)
        return False
    data = safe_fs.read_bytes_or_none(root, shot) if result.get("ok") else None
    if not data:
        logger.warning("p05: Playwright navigation/capture failed: %s", result.get("error", "no image"))
        return False
    output_path.write_bytes(data)
    logger.info(f"p05: Successfully captured preview screenshot at {output_path}")
    return True


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
            client.call_vision(prompt, img_bytes, task_type="ui_critique", max_tokens=1000),
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

    # Identify files to refine — all generated pages + key components
    src_dir = frontend_dir / "src"
    candidates = (
        list((src_dir / "pages").glob("*.tsx"))
        + [src_dir / "components" / "DomainWidget.tsx", src_dir / "components" / "Layout.tsx"]
    )

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
