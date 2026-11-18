"""P07c Accessibility Testing — axe-core checks against the generated frontend."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.domain_knowledge.loader import load_pack
from aether_os.core.run_app import safe_fs
from aether_os.core.sandbox import phase_exec
from aether_os.core.sandbox.browser_job import run_browser_job
from aether_os.core.sandbox.runner import SandboxUnavailable, sandbox_dirs
from aether_os.phases.base import TaskResult

logger = logging.getLogger(__name__)

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


_BASE_AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]


def axe_tags_for(domain: str) -> list:
    """WCAG 2.1 AA always; the Section 508 ruleset too when the domain's compliance rules name it
    (govtech, edtech): that is how the domain pack's "inject Section 508 into p07c" instruction is carried out."""
    pack = load_pack(domain or "")
    names = " ".join(f"{r.standard} {r.rule}" for r in (pack.compliance if pack else []))
    return _BASE_AXE_TAGS + (["section508"] if "508" in names else [])


_AXE_PORT = 4173   # on the browser sandbox's own loopback


def dist_dir_for(data: Dict[str, Any]) -> Optional[Path]:
    """The built frontend (dist/ with an index.html) the browser sandbox can serve, or None."""
    for raw in (data.get("frontend_dist_dir"), (Path(data["frontend_output_path"]) / "dist")
                if data.get("frontend_output_path") else None):
        if raw:
            d = Path(raw)
            root = phase_exec.project_root(d)
            if safe_fs.is_real_dir(root, d.relative_to(root)) and safe_fs.stat_or_none(root, (d / "index.html").relative_to(root)):
                return d
    return None


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}

    # Defer: the scan needs a built frontend to open. (A URL cannot stand in: the browser sandbox has no
    # network by design, so "localhost" there is only what the sandbox itself serves.)
    dist = dist_dir_for(data)
    if dist is None:
        result = {
            "success": True,
            "skipped": True,
            "reason": "deferred: needs a built frontend (dist/) — nothing to open in the browser sandbox",
        }
        (output_dir / "a11y_results.json").write_text(json.dumps(result, indent=2))
        return TaskResult(
            output_path=str(output_dir / "a11y_results.json"),
            confidence=1.0,
            metadata={"phase": "p07c_accessibility_testing", "skipped": True, "data": result},
        )

    tags = axe_tags_for(data.get("domain", ""))
    results: Dict = {
        "target": f"dist served inside the browser sandbox ({dist})",
        "wcag_level": "WCAG 2.1 AA" + (" + Section 508" if "section508" in tags else ""),
        "axe_tags": tags,
        "checklist": _WCAG_CHECKLIST,
        "violations": 0,
        "passes": 0,
    }

    # ── axe-core in the browser sandbox (Chromium never runs on the platform host) ──────────────
    root = phase_exec.project_root(dist)
    out_json = Path(sandbox_dirs(root)["TMPDIR"]) / "axe_result.json"
    job = {"action": "axe", "tags": tags, "out": str(out_json),
           "serve": {"dir": str(dist), "port": _AXE_PORT}, "url": f"http://127.0.0.1:{_AXE_PORT}/"}
    try:
        axe_data = await run_browser_job(job, project=dist, timeout=60)
        if not axe_data.get("ok") or not isinstance(axe_data.get("violations"), int):
            raise RuntimeError(axe_data.get("error") or "axe returned no violation count")
        results.update({k: axe_data[k] for k in ("violations", "passes", "incomplete", "items") if k in axe_data})
        results["ran_axe"] = True
        logger.info("[p07c] axe done: %d violations, %d passes", axe_data.get("violations", 0), axe_data.get("passes", 0))
    except SandboxUnavailable as exc:
        logger.error("[p07c] axe not run, the browser sandbox is unavailable: %s", exc)
        results["skipped"] = True
        results["reason"] = f"browser sandbox unavailable: {exc}"
    except Exception as exc:
        logger.info("[p07c] axe skipped (%s) — using static checklist", exc)
        results["skipped"] = True
        results["reason"] = "axe did not run in the browser sandbox (see log)"

    # ── ARIA attribute audit on generated HTML ────────────────────────────────
    frontend_dir = Path(data.get("frontend_src_dir", "")) if data.get("frontend_src_dir") else None
    aria_issues = []
    if frontend_dir and frontend_dir.exists():
        root_fe = phase_exec.project_root(frontend_dir)
        for rel in safe_fs.walk_files(root_fe, frontend_dir.relative_to(root_fe), skip_dirs=("node_modules", "dist")):
            if rel.suffix not in (".tsx", ".jsx"):
                continue
            content = safe_fs.read_text_or_none(root_fe, rel)
            if content and "<img" in content and "alt=" not in content:
                aria_issues.append(f"{rel.name}: <img> missing alt attribute")
        results["aria_issues"] = aria_issues[:10]

    # "No violations" is only a result when axe actually ran: a scan that did not run is not a pass.
    results["passed"] = bool(results.get("ran_axe")) and results["violations"] == 0
    (output_dir / "a11y_results.json").write_text(json.dumps(results, indent=2))

    return TaskResult(
        output_path=str(output_dir / "a11y_results.json"),
        confidence=0.70,
        metadata=results,
        success=True,
        issues=aria_issues[:5],
    )
