"""P00 Communication Agent — post to bus and send WhatsApp ack."""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def send_ack(client_id: str, run_id: str, success: bool) -> None:
    """Send WhatsApp acknowledgement to client after intake."""
    if not success:
        return
    base_cls = _get_base()
    msg = (
        "Your requirements have been received. "
        "We will begin analysis shortly."
    )
    await base_cls._send_whatsapp(base_cls, client_id, msg)


async def publish_result(run_id: str, phase: str, status: str,
                         output_path: str, confidence: float,
                         issues: list, next_phase: Optional[str] = None,
                         client_id: Optional[str] = None,
                         artifacts: Optional[Dict] = None) -> None:
    from aether_os.phases.base import PhaseBase
    base = PhaseBase()
    whatsapp_msg = None
    if status == "passed" and client_id:
        whatsapp_msg = ("Your requirements have been received. "
                        "We will begin analysis shortly.")
    await base.communicate(
        run_id=run_id, phase=phase, status=status,
        output_path=output_path, confidence=confidence,
        issues=issues, next_phase=next_phase, artifacts=artifacts or {},
        client_id=client_id, whatsapp_msg=whatsapp_msg,
    )


def _get_base():
    from aether_os.phases.base import PhaseBase
    return PhaseBase()
