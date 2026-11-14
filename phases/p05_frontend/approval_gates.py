"""P05 approval gates (Gate 3 admin requirements, Gate 2 portal preview), split from domain_assembler.py for size."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from aether_os.core.decisions.decision_engine import Decision, get_decision_engine
from aether_os.core.domain_ir import AetherType  # noqa: F401
from aether_os.core.pipeline_state import publish_event
from aether_os.orchestrator.events import ACTIVE_RUN_ID
from aether_os.phases.p05_frontend.preview import vlm_rubric_critique

logger = logging.getLogger(__name__)


async def run_gate3_approval(
    *,
    domain_ir: Any,
    data: Dict[str, Any],
    is_autonomous: bool,
    derive_admin_features_fn: Any,
) -> List[str]:
    """Run Gate 3 — Admin Requirements Approval Gate.

    Returns the (possibly human-corrected) list of admin_features.
    In autonomous mode, returns the features without waiting.
    """

    customer_flows = [wf.trigger for wf in domain_ir.workflows] if domain_ir else []
    admin_features = derive_admin_features_fn(customer_flows)
    try:



        run_id = ACTIVE_RUN_ID.get()

        if run_id and not is_autonomous:
            logger.info("p05: Waiting for Gate 3 (Admin Requirements) approval...")
            engine = get_decision_engine()
            decision = Decision(
                run_id=run_id, org_id=data.get("org_id", ""),
                decision_type="admin_spec_approval", title="Gate 3: Admin Portal Requirements",
                what=f"Admin panel features: {', '.join(admin_features)}",
                why="Confirm admin features before generation.", phase="p05_frontend",
            )
            await engine.request_approval(decision)
            await publish_event(run_id, {
                "type": "PhaseApprovalRequired", "phase": "p05_frontend", "gate": "gate_3",
                "decision_id": decision.id,
                "data": {"admin_features": admin_features},
                "allow_overrides": True,
            })
            resolved = await engine.await_decision(decision.id)
            if resolved.status == "approved" and resolved.human_choice:
                try:
                    if resolved.human_choice.strip().startswith("["):
                        admin_features = json.loads(resolved.human_choice)
                    else:
                        admin_features = [f.strip() for f in resolved.human_choice.split(",") if f.strip()]
                except Exception as _parse_exc:
                    logger.warning("p05: Gate 3 choice parse failed: %s", _parse_exc)
        else:
            logger.info("p05: Autonomous mode — bypassing Gate 3 approval.")
    except Exception as exc:
        logger.warning("p05: Gate 3 skipped: %s", exc)
    return admin_features


async def run_gate2_preview(
    *,
    run_id: Optional[str],
    frontend_dir: Path,
    output_dir: Path,
    domain: str,
    project_name: str,
    data: Dict[str, Any],
    is_autonomous: bool,
    take_screenshot_fn: Any,
    apply_revisions_fn: Any,
) -> bool:
    """Run Gate 2 — Customer Portal Preview Approval Gate.

    Takes a screenshot, publishes a PhaseApprovalRequired event, and applies
    any human-provided revision instructions.  Skipped in autonomous mode.

    Returns True when revisions were applied to *frontend_dir* (the caller must rebuild).
    """
    revised = False
    screenshot_path = ""
    preview_path = output_dir / "customer_portal_preview.png"
    _shot_ok = await take_screenshot_fn(frontend_dir, preview_path)
    if _shot_ok:
        screenshot_path = str(preview_path)

    # Autonomous 2-round critique: run apply_revisions with a generic
    # "improve visual polish" instruction, re-screenshot, then run again.
    # Human-review path (non-autonomous) still runs at most one round below.
    if is_autonomous and _shot_ok:

        _critique = await vlm_rubric_critique(preview_path, domain, project_name)
        for _round in (1, 2):
            try:
                await apply_revisions_fn(_critique, frontend_dir, domain, project_name)
                revised = True
                # Re-screenshot before the next round so a second pass sees the delta.
                if _round == 1:
                    await take_screenshot_fn(frontend_dir, preview_path)
                    _critique = await vlm_rubric_critique(preview_path, domain, project_name)
            except Exception as _auto_exc:
                logger.warning("p05: autonomous critique round %d failed: %s", _round, _auto_exc)
                break

    try:
        if run_id and not is_autonomous:
    
    
            engine = get_decision_engine()
            decision = Decision(
                run_id=run_id, org_id=data.get("org_id", ""),
                decision_type="portal_preview_approval", title="Gate 2: Customer Portal Preview",
                what=f"Preview available at {screenshot_path}" if screenshot_path else "Preview unavailable.",
                why="Human confirmation of visual design.", phase="p05_frontend",
            )
            await engine.request_approval(decision)
            await publish_event(run_id, {
                "type": "PhaseApprovalRequired", "phase": "p05_frontend", "gate": "gate_2",
                "decision_id": decision.id,
                "screenshot_url": (
                    f"/api/artifacts/{run_id}/p05_frontend/customer_portal_preview.png"
                    if screenshot_path else None
                ),
            })
            resolved = await engine.await_decision(decision.id)
            if resolved.status == "approved" and resolved.human_choice:
                await apply_revisions_fn(
                    resolved.human_choice.strip(), frontend_dir, domain, project_name
                )
                revised = True
        elif run_id:
            logger.info("p05: Autonomous mode — bypassing Gate 2 approval.")
    except Exception as _gate2_exc:
        logger.warning("p05: Gate 2 skipped: %s", _gate2_exc)
    return revised
