"""Pattern library injection helpers for p04a backend codegen.

Detects active patterns from build metadata and writes the corresponding
pattern files (multi_tenant.py, agent.py) into the generated app's src/ dir.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def detect_active_patterns(data: Dict[str, Any], raw_input: str) -> List[str]:
    """Return a list of pattern names that should be activated for this build."""
    active: List[str] = []
    raw_lower = str(raw_input).lower()
    build_types: List[str] = data.get("build_types") or []

    if (
        any(x in raw_lower for x in ["multi-tenant", "multi tenant", "saas", "organization", "org_id"])
        or "multi_tenant" in build_types
    ):
        active.append("multi_tenant")

    if (
        any(x in raw_lower for x in ["ai agent", "agentic", "tool use", "chat"])
        or "agentic_ai" in build_types
    ):
        active.append("agentic_ai")

    if (
        any(x in raw_lower for x in ["websocket", "real-time", "realtime", "live update", "collaboration", "live chat", "broadcast"])
        or "websocket" in build_types
        or "realtime" in build_types
    ):
        active.append("websocket")

    if (
        any(x in raw_lower for x in ["stripe", "billing", "subscription", "payment processing", "checkout"])
        or "stripe" in build_types
        or "billing" in build_types
    ):
        active.append("stripe")

    if (
        any(x in raw_lower for x in ["marketplace", "escrow", "bidding", "auction", "buy and sell", "p2p", "peer-to-peer", "listings"])
        or "marketplace" in build_types
    ):
        active.append("marketplace")

    return active


def inject_patterns(
    active_patterns: List[str],
    src_dir: Path,
    output_dir: Path,
) -> None:
    """Write pattern files to src_dir and append their requirements to requirements.txt.

    Failures are non-fatal — logged at WARNING level and skipped.
    """
    req_path = output_dir / "requirements.txt"

    def _append_requirements(new_reqs: List[str]) -> None:
        if not req_path.exists():
            return
        existing = req_path.read_text()
        for req in new_reqs:
            pkg_name = req.split(">=")[0].split("==")[0].split("[")[0]
            if pkg_name not in existing:
                req_path.write_text(existing.rstrip() + f"\n{req}\n")
                existing = req_path.read_text()

    for pattern_name in active_patterns:
        logger.info("[p04a] activating pattern: %s", pattern_name)
        try:
            if pattern_name == "multi_tenant":
                # Deferred import: patterns import SQLAlchemy which may not be available at
                # module load time (test environments without DB deps installed).
                from aether_os.phases.patterns.multi_tenant import (  # noqa: PLC0415
                    MULTI_TENANT_CODE,
                    MULTI_TENANT_REQUIREMENTS,
                )
                (src_dir / "multi_tenant.py").write_text(MULTI_TENANT_CODE)
                _append_requirements(MULTI_TENANT_REQUIREMENTS)

            elif pattern_name == "agentic_ai":
                from aether_os.phases.patterns.agentic_ai import (  # noqa: PLC0415
                    AGENTIC_AI_CODE,
                    AGENTIC_AI_REQUIREMENTS,
                )
                (src_dir / "agent.py").write_text(AGENTIC_AI_CODE)
                _append_requirements(AGENTIC_AI_REQUIREMENTS)

            elif pattern_name == "websocket":
                from aether_os.phases.patterns.websocket import (  # noqa: PLC0415
                    WEBSOCKET_CODE,
                    WEBSOCKET_REQUIREMENTS,
                )
                (src_dir / "websocket_router.py").write_text(WEBSOCKET_CODE)
                _append_requirements(WEBSOCKET_REQUIREMENTS)

            elif pattern_name == "stripe":
                from aether_os.phases.patterns.stripe import (  # noqa: PLC0415
                    STRIPE_CODE,
                    STRIPE_REQUIREMENTS,
                )
                (src_dir / "billing_router.py").write_text(STRIPE_CODE)
                _append_requirements(STRIPE_REQUIREMENTS)

            elif pattern_name == "marketplace":
                from aether_os.phases.patterns.marketplace import (  # noqa: PLC0415
                    MARKETPLACE_CODE,
                    MARKETPLACE_REQUIREMENTS,
                )
                (src_dir / "marketplace_router.py").write_text(MARKETPLACE_CODE)
                _append_requirements(MARKETPLACE_REQUIREMENTS)

            else:
                logger.warning("[p04a] unknown pattern '%s' — skipped", pattern_name)

        except Exception as exc:
            logger.warning("[p04a] pattern %s injection failed (non-fatal): %s", pattern_name, exc)
