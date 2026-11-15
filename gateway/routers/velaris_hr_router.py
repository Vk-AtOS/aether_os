"""HR proxy: POST /hr/{agent}/{method} -> Velaris POST /agents/{agent}/{method}, for the agent+method pairs the
HR screens use and NO others (not a generic passthrough; erasure, bulk export and signer/candidate-facing
methods are deliberately absent). Velaris still applies its own allow-list and roles, and answers 202 for acts
that wait for approval; that is passed through unchanged. Every call is ledgered (names of parameters only).
"""
from __future__ import annotations

import json
from typing import Any, Dict, FrozenSet

from fastapi import APIRouter, Depends, HTTPException, Request

from aether_os.gateway.dependencies import get_current_user
from aether_os.gateway.velaris_proxy import MAX_JSON, call, identity, read_body, reply

router = APIRouter(prefix="/hr", tags=["velaris-hr"])

_S = frozenset
HR_ALLOW: Dict[str, FrozenSet[str]] = {
    "ATS_CORE": _S({"list_requisitions", "get_requisition", "create_requisition", "approve_requisition",
                    "open_requisition", "close_requisition", "pipeline", "get_application", "move_stage",
                    "decision_log", "aggregate_counts", "duplicate_review", "resolve_duplicate"}),
    "RESUME_EVIDENCE": _S({"get_evidence", "match_requisition", "unknown_skills", "alias_proposals",
                           "propose_alias", "review_alias", "parse_resume", "list_skills"}),
    "JOB_POSTINGS": _S({"prepare_careers_posting", "get_posting", "approve_posting", "mark_posting_live",
                        "take_down_posting", "prepare_pack", "approve_pack", "mark_pack_posted",
                        "mark_pack_taken_down", "list_packs", "takedown_due"}),
    "SCREENING_FORMS": _S({"create_form", "publish_form", "unpublish_form", "list_forms", "get_form",
                           "pending_submissions", "get_submission", "accept_submission", "discard_submission"}),
    "INTERVIEW_SCHEDULER": _S({"set_availability", "list_interviewers", "propose_slots", "book_interview",
                               "reschedule_interview", "cancel_interview", "complete_interview", "list_bookings",
                               "list_drafts", "approve_draft", "render_invitation"}),
    "INTERVIEW_KIT": _S({"list_questions", "get_kit", "create_kit", "assign_panel", "submit_scorecard",
                         "scorecards", "agreement_report"}),
    "OFFER_LETTERS": _S({"list_offers", "get_offer", "render_offer", "create_offer", "submit_for_approval",
                         "approve", "reject", "send_offer", "record_response", "withdraw_offer"}),
    "ESIGN": _S({"list_requests", "get_request", "verify", "create_request", "send_request", "void_request"}),
    "ONBOARDING_FLOW": _S({"list_templates", "list_cases", "case_status", "start_onboarding", "complete_task",
                           "waive_task", "cancel_case", "get_identifiers"}),
    "EMPLOYEE_RECORDS": _S({"list_employees", "get_employee", "employee_history", "start_exit",
                            "complete_exit_task", "exit_status", "finalise_exit", "propose_conversion",
                            "approve_conversion", "reject_conversion"}),
    "POLICY_ACKS": _S({"list_policies", "get_policy", "compliance_report", "publish_policy", "retire_policy",
                       "pending_for_employee"}),
}


@router.get("/allowlist")
async def allowlist(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """The pairs this proxy will forward (lets the UI say 'not available' instead of guessing)."""
    await identity(user, acting=False)
    return {"agents": {a: sorted(m) for a, m in sorted(HR_ALLOW.items())}}


@router.post("/{agent}/{method}")
async def hr_call(agent: str, method: str, request: Request,
                  user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    """Read methods: 200 {result}. Act methods: 202 {run}, waiting for approval (Prime inbox)."""
    if method not in HR_ALLOW.get(agent, _S()):
        raise HTTPException(status_code=404, detail="This agent method is not available here")
    who = await identity(user, acting=True)
    raw = await read_body(request, MAX_JSON)
    if raw:
        try:
            args = json.loads(raw)
        except ValueError:
            raise HTTPException(status_code=400, detail="The body is not JSON") from None
        if not isinstance(args, dict):
            raise HTTPException(status_code=400, detail="The body must be a JSON object")
    else:
        args, raw = {}, b"{}"
    resp = await call(who, "hr.call", "POST", f"/agents/{agent}/{method}", body=raw,
                      detail={"agent": agent, "method": method, "params": sorted(args)[:20]})
    return reply(resp)
