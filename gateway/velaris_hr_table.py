"""The HR proxy as DATA: every (agent, method) the dashboard may reach, with its rules, built into the same `Route`
rows the chat / mail / control proxies use (gateway/velaris_proxy.py), so role check, identity-override refusal,
body cap, page-size clamp, timeout, answer cap and ledger are one implementation, not one per feature.

A pair that is not in this table does not exist (404). Rules per row:
  admin    owner/admin only, checked in the gateway (self-service rows leave it off; Velaris still applies its
           own read/act rules, e.g. own record only).
  confirm  typed confirmation word the body must carry (erasure, export of one person's data). Such rows are
           admin-only, always ledgered, and are NOT reachable through the generic /velaris/agents route (KAN-199).
  export   the answer is served as a download with safe headers, never rendered.
Ledger entries hold the agent, method and parameter NAMES only; never values, tokens or documents.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

from aether_os.gateway.velaris_proxy import MAX_FILE, Route

SLOW_S = 70.0       # Velaris gives a call up to 60 s
FAST_S = 30.0

# agent -> methods. Order and grouping follow the dashboard screens.
_OPEN = {   # reachable by any role that may act (Velaris enforces own-record rules and its own roles)
    "ATS_CORE": "list_requisitions get_requisition create_requisition approve_requisition open_requisition "
                "close_requisition pipeline get_application move_stage decision_log aggregate_counts "
                "duplicate_review resolve_duplicate",
    "RESUME_EVIDENCE": "get_evidence match_requisition unknown_skills alias_proposals propose_alias review_alias "
                       "parse_resume list_skills",
    "JOB_POSTINGS": "prepare_careers_posting get_posting approve_posting mark_posting_live take_down_posting "
                    "prepare_pack approve_pack mark_pack_posted mark_pack_taken_down list_packs takedown_due",
    "SCREENING_FORMS": "create_form publish_form unpublish_form list_forms get_form pending_submissions "
                       "get_submission accept_submission discard_submission",
    "INTERVIEW_SCHEDULER": "set_availability list_interviewers propose_slots book_interview reschedule_interview "
                           "cancel_interview complete_interview list_bookings list_drafts approve_draft "
                           "render_invitation",
    "INTERVIEW_KIT": "list_questions get_kit create_kit assign_panel submit_scorecard scorecards agreement_report "
                     "list_work_samples review_work_sample work_sample_reviews",
    "OFFER_LETTERS": "list_offers get_offer render_offer create_offer submit_for_approval approve reject send_offer "
                     "record_response withdraw_offer",
    "ESIGN": "list_requests get_request verify create_request send_request void_request",
    "ONBOARDING_FLOW": "list_templates list_cases case_status start_onboarding complete_task waive_task "
                       "cancel_case get_identifiers get_form get_document check_aadhaar submit_identifier "
                       "submit_form collect_document",
    "EMPLOYEE_RECORDS": "list_employees get_employee employee_history start_exit complete_exit_task exit_status "
                        "finalise_exit propose_conversion approve_conversion reject_conversion",
    "POLICY_ACKS": "list_policies get_policy compliance_report publish_policy retire_policy pending_for_employee "
                   "acknowledge",
    # KAN-137 / KAN-138: self-service (own balance, own payslip). Velaris refuses another person's record.
    "LEAVE_MANAGEMENT": "get_balance employee_history apply",
    "PAYROLL_ENGINE": "get_payslip get_statutory_deductions get_ytd_summary",
    "ZOHO_PAYROLL": "get_payslip get_statutory_deductions get_ytd_summary",
    # KAN-148: the interviewer-facing methods. Candidate-facing consent and audio upload (KAN-74) stay out.
    "INTERVIEW_RECORD": "create_session list_sessions issue_participant_token replay_pad evidence_view "
                        "close_session mark_event",
}
_ADMIN = {  # owner/admin only
    "LEAVE_MANAGEMENT": "pending_approvals approve reject",
    "ZOHO_PEOPLE": "get_employees get_leave_summary get_attendance get_attendance_summary",
    "PAYROLL_ENGINE": "compute compute_bulk org_statutory_summary",
    "ZOHO_PAYROLL": "get_cost_to_company",
    "OFFER_LETTERS": "list_templates add_template compensation_preview revise_offer expire_due",
    "ESIGN": "send_reminders process_due seal_request",
    "ONBOARDING_FLOW": "reminders_due",
    "EMPLOYEE_RECORDS": "retention_status retention_table workforce_aggregate change_record",
    "POLICY_ACKS": "reminders_due",
    "ATS_CORE": "add_candidate add_application candidate_summary candidate_contact withdraw_consent "
                "retention_due record_offer_outcome",
    "JOB_POSTINGS": "get_company_profile set_company_profile resolve_tracking send_indexing_notification",
    "SCREENING_FORMS": "issue_candidate_token process_withdrawal withdrawal_requests sweep_submissions "
                       "public_routes",
    "RESUME_EVIDENCE": "bias_audit",
    "INTERVIEW_SCHEDULER": "issue_schedule_token reminders mark_reminder_sent mark_no_show",
    "INTERVIEW_KIT": "add_question define_rubric create_work_sample calibration_report",
}
# (agent, method) -> typed word. Personal-data export and erasure: admin + ledger + typed confirmation (KAN-199).
_CONFIRM: Dict[Tuple[str, str], str] = {
    ("EMPLOYEE_RECORDS", "export_subject"): "EXPORT",
    ("EMPLOYEE_RECORDS", "erase_subject"): "ERASE",
    ("ATS_CORE", "export_candidate"): "EXPORT",
    ("ATS_CORE", "erase_candidates"): "ERASE",
}
_EXPORT = frozenset({("EMPLOYEE_RECORDS", "export_subject"), ("ATS_CORE", "export_candidate"),
                     ("ESIGN", "get_sealed_document")})
_SLOW = frozenset({("PAYROLL_ENGINE", "compute_bulk"), ("RESUME_EVIDENCE", "parse_resume"),
                   ("RESUME_EVIDENCE", "bias_audit"), ("ESIGN", "process_due"), ("ESIGN", "seal_request"),
                   ("SCREENING_FORMS", "sweep_submissions"), ("OFFER_LETTERS", "expire_due"),
                   ("ATS_CORE", "erase_candidates"), ("EMPLOYEE_RECORDS", "erase_subject"),
                   ("EMPLOYEE_RECORDS", "export_subject"), ("ATS_CORE", "export_candidate")})
_BIG_BODY = frozenset({("ONBOARDING_FLOW", "collect_document")})   # a joiner's document travels inside the JSON


def _rows() -> Tuple[Route, ...]:
    pairs = [(a, m, False) for a, ms in _OPEN.items() for m in ms.split()]
    pairs += [(a, m, True) for a, ms in _ADMIN.items() for m in ms.split()]
    pairs += [(a, m, True) for (a, m) in _CONFIRM]
    pairs.append(("ESIGN", "get_sealed_document", True))
    rows = []
    for agent, method, admin in pairs:
        key = (agent, method)
        rows.append(Route(
            "POST", f"/{agent}/{method}", "hr.call",
            kind="export" if key in _EXPORT else "json",
            ledger=True, admin=admin, confirm=_CONFIRM.get(key),
            timeout=SLOW_S if key in _SLOW else FAST_S,
            max_body=MAX_FILE if key in _BIG_BODY else 64 * 1024,
            empty_body=b"{}", extra=(("agent", agent), ("method", method))))
    return tuple(rows)


HR_ROUTES: Tuple[Route, ...] = _rows()
HR_ALLOW: Dict[str, FrozenSet[str]] = {}
for _r in HR_ROUTES:
    _a, _m = _r.path.strip("/").split("/")
    HR_ALLOW[_a] = HR_ALLOW.get(_a, frozenset()) | {_m}
# Rows the generic /velaris/agents route and flow tools must NOT reach: they need the admin check or the typed
# confirmation that only these rows carry. (A viewer-visible, member-level row may still be reached generically.)
HR_DEDICATED: FrozenSet[Tuple[str, str]] = frozenset(
    tuple(r.path.strip("/").split("/")) for r in HR_ROUTES if r.admin or r.confirm)   # type: ignore[arg-type]
