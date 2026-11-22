"""
P01 Gate Engine — Intent Verification + Entity Approval Gate
Extracted from task_agent.py to keep that file under 350 lines.

Functions:
  run_intent_verification()  — ambiguity detection + second LLM pass
  run_entity_approval_gate() — low-confidence gate (pauses pipeline, awaits human)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def record_architectural_decisions(
    *,
    phase_input: Any,
    contract: Dict[str, Any],
    domain: str,
    _b2b_domain: bool,
    _has_customer_persona: bool,
    _b2b_in_raw: bool,
    _effective_domain: str,
    tenant_isolation: str,
) -> None:
    """Record multi_tenancy, tenant_isolation, domain, and audit_log decisions.

    These decision records travel through accumulated_context so every
    downstream LLM phase receives consistent justification for key choices.
    """
    from aether_os.core.context_helpers import record_decision

    _multi_tenancy_val = contract["commercial_defaults"]["multi_tenancy"]
    _mt_reason_parts = []
    if _b2b_domain:
        _mt_reason_parts.append(f"domain '{_effective_domain}' is B2B/SaaS")
    if _has_customer_persona:
        _mt_reason_parts.append("spec has a customer-type persona")
    if _b2b_in_raw:
        _mt_reason_parts.append("B2B keywords found in raw input")
    _mt_reason = "; ".join(_mt_reason_parts) if _mt_reason_parts else "no B2B signals detected"

    record_decision(
        phase_input.input_data,
        key="multi_tenancy",
        value=str(_multi_tenancy_val),
        reason=_mt_reason,
        phase="p01",
    )
    record_decision(
        phase_input.input_data,
        key="tenant_isolation",
        value=tenant_isolation,
        reason=(
            f"derived from multi_tenancy={_multi_tenancy_val}; "
            "org_id_filter is the safe default for multi-tenant apps, "
            "'none' for single-tenant"
        ),
        phase="p01",
    )
    _domain_decision = contract.get("domain") or domain
    record_decision(
        phase_input.input_data,
        key="domain",
        value=_domain_decision,
        reason="LLM-classified from intake text; affects entity defaults and security requirements",
        phase="p01",
    )
    _data_sens = contract["scalability"].get("data_sensitivity", "internal")
    if _data_sens == "regulated" or contract["scalability"].get("handles_money"):
        record_decision(
            phase_input.input_data,
            key="audit_log",
            value="True",
            reason=(
                f"data_sensitivity={_data_sens} or handles_money=True — "
                "regulated/financial data requires immutable audit trail"
            ),
            phase="p01",
        )


async def run_intent_verification(
    *,
    data: Dict[str, Any],
    requirements_doc: Dict[str, Any],
    phase_input: Any,
) -> None:
    """Check intent ambiguity and run a second LLM verification pass.

    Flags intent_ambiguity on phase_input.input_data and records decision
    context.  All results are written directly onto phase_input.input_data
    so downstream phases see them through accumulated_context.
    """
    from aether_os.core.context_helpers import record_decision

    _raw_input: str = data.get("raw_input", "")
    _word_count = len(_raw_input.split())
    _entity_count_iv = len(requirements_doc.get("entities", []))

    if _word_count < 30 or _entity_count_iv == 0:
        logger.warning(
            "p01 intent_verification: prompt is %s — "
            "short input (%d words) or no entities (%d). "
            "Flagging ambiguity in accumulated_context.",
            "ambiguous" if _word_count < 30 else "entity-empty",
            _word_count, _entity_count_iv,
        )
        record_decision(
            phase_input.input_data,
            "intent_ambiguity_flag",
            {
                "word_count": _word_count,
                "entity_count": _entity_count_iv,
                "flag": "ambiguous" if _word_count < 30 else "no_entities_found",
                "recommendation": "Consider providing more detail about the app's core features",
            },
            reason="p01 detected low-detail prompt — downstream phases should use conservative defaults",
            phase="p01_intake_requirements",
        )
        phase_input.input_data["intent_ambiguity"] = True
    else:
        phase_input.input_data["intent_ambiguity"] = False

    # Second LLM pass: verify the top 3 entities make sense together
    try:
        _entity_names = [e.get("name", "") for e in requirements_doc.get("entities", [])[:3]]
        if _entity_names:
            from aether_os.core.llm.client import get_llm_client as _get_llm
            _llm_iv = _get_llm()
            _verify_prompt = (
                f"Given the user's app description: '{_raw_input[:300]}'\n"
                f"I interpreted the core entities as: {', '.join(_entity_names)}.\n"
                f"In one sentence, does this interpretation make sense? "
                f"Reply with 'YES: <reason>' or 'NO: <correct interpretation>'."
            )
            _verify_text = await _llm_iv.call(
                _verify_prompt, task_type="verify",   # light tier: a one-sentence semantic check, no tool can answer it
                org_id=data.get("org_id") or None, plan=data.get("plan"),
                run_id=getattr(phase_input, "run_id", None), phase="p01_intake_requirements",
            )
            phase_input.input_data["intent_verification"] = _verify_text[:200]
            if str(_verify_text).upper().startswith("NO"):
                logger.warning(
                    "p01 intent_verification: LLM flagged misinterpretation: %s",
                    _verify_text[:100],
                )
                record_decision(
                    phase_input.input_data, "intent_mismatch",
                    {"verification_response": _verify_text[:200]},
                    reason="Second-pass LLM disagrees with first-pass interpretation",
                    phase="p01_intake_requirements",
                )
    except Exception as _iv_exc:
        logger.warning("p01 intent_verification failed (non-fatal): %s", _iv_exc)


async def run_entity_approval_gate(
    *,
    data: Dict[str, Any],
    confidence: float,
    confidence_reason: str,
    entities_extracted: List[Dict[str, Any]],
    requirements_doc: Dict[str, Any],
    summary: Dict[str, Any],
) -> tuple[float, str, List[Dict[str, Any]]]:
    """Run the entity approval gate when confidence is low or intent is ambiguous.

    Returns (updated_confidence, updated_confidence_reason, updated_entities).
    If the gate is skipped (autonomous mode or high confidence), the original
    values are returned unchanged.

    Raises PipelineBlockedError when the user explicitly rejects the extraction.
    """
    _is_autonomous = (
        data.get("autonomous_mode") is True
        or data.get("decision_mode") == "autonomous"
    )
    _needs_gate = (not _is_autonomous) and (confidence < 0.65 or data.get("intent_ambiguity"))

    if not _needs_gate:
        return confidence, confidence_reason, entities_extracted

    try:
        from aether_os.core.pipeline_state import publish_event
        from aether_os.core.decisions.decision_engine import Decision, get_decision_engine
        from aether_os.orchestrator.events import ACTIVE_RUN_ID
        run_id = ACTIVE_RUN_ID.get()
        if not run_id:
            return confidence, confidence_reason, entities_extracted

        logger.info("p01: low confidence (%.2f) — requesting entity approval gate", confidence)
        _entity_preview = ", ".join(
            e.get("name", e.get("table", "?")) for e in entities_extracted[:6]
        ) or "(none detected)"
        engine = get_decision_engine()
        decision = Decision(
            run_id=run_id,
            org_id=data.get("org_id", ""),
            decision_type="entity_approval",
            title="Entity Approval Gate: Low-Confidence Extraction",
            what=(
                f"Confidence: {confidence:.0%} — {confidence_reason}.\n"
                f"Detected entities: {_entity_preview}.\n"
                "Confirm these are correct, or provide a comma-separated list of corrections."
            ),
            why="Pipeline detected ambiguity in the app description and needs human confirmation before generating code.",
            phase="p01_intake_requirements",
        )
        await engine.request_approval(decision)
        await publish_event(run_id, {
            "type": "PhaseApprovalRequired",
            "phase": "p01_intake_requirements",
            "gate": "entity_approval",
            "decision_id": decision.id,
            "data": {
                "confidence": confidence,
                "confidence_reason": confidence_reason,
                "entities": [e.get("name", "") for e in entities_extracted],
            },
            "allow_overrides": True,
        })
        resolved = await engine.await_decision(decision.id)
        if resolved.status == "approved" and resolved.human_choice:
            _corrected = [n.strip() for n in resolved.human_choice.split(",") if n.strip()]
            if _corrected:
                entities_extracted = [
                    {"name": n, "table": n.lower().replace(" ", "_")}
                    for n in _corrected
                ]
                requirements_doc["entities"] = entities_extracted
                data["entities"] = entities_extracted  # later phases read input_data["entities"]
                summary["entities"] = entities_extracted
                confidence = 0.80
                confidence_reason = f"Human-corrected entities: {', '.join(_corrected)}"
                logger.info("p01: entity gate approved — user provided %d entities", len(_corrected))
        elif resolved.status in ("denied", "timeout", "rejected"):
            # The engine produces pending|approved|denied|timeout; a denial or an
            # unanswered gate must stop the run, not fall through as approved.
            from aether_os.core.errors import PipelineBlockedError
            raise PipelineBlockedError(
                f"Entity extraction not approved ({resolved.status}) — pipeline halted at p01"
            )
    except (ImportError, AttributeError) as _gate_exc:
        logger.warning("p01: entity approval gate unavailable (non-fatal): %s", _gate_exc)

    return confidence, confidence_reason, entities_extracted
