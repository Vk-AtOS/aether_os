// Velaris gap screens as DATA, rendered by ActionScreen.jsx. role: 'member' (any role that may act; Velaris still
// limits a member to their own records) or 'admin' (owner/admin; the gateway refuses anyone else).
// Field names are the argument names of the Velaris methods, checked against the real Velaris allow-list by
// tests/test_velaris_contract.py (no catch-all "other fields" box). Org/actor keys are refused by the gateway.
// fixed: {scope: '@org'} is replaced by the signed-in organisation id before sending (library/memory scopes).
const H = (a, m) => ({ hr: [a, m] });
const A = (a, m) => ({ agent: [a, m] });
const P = (method, path) => ({ method, path });
const text = (name, label, extra = {}) => ({ name, label, type: 'text', ...extra });
const num = (name, label, extra = {}) => ({ name, label, type: 'number', ...extra });
const json = (name, label, extra = {}) => ({ name, label, type: 'json', ...extra });
const list = (name, label, extra = {}) => ({ name, label, type: 'list', ...extra });
const nums = (name, label, extra = {}) => ({ name, label, type: 'numlist', help: 'Numbers separated by commas', ...extra });
const YM = [num('year', 'Year', { required: true }), num('month', 'Month (1-12)', { required: true })];
const load = (title, call, extra = {}) => ({ kind: 'load', title, call, ...extra });
const form = (title, call, fields, submit, extra = {}) => ({ kind: 'form', title, call, fields, submit, ...extra });
const LEGAL_REVIEW = 'Wording on this screen is pending legal review (KAN-80). Export and erase are for organisation owners and admins only, need the typed word, and are written to the ledger by id.';
const DISCLAIMER = 'Payroll figures are calculations, not payments, and are not approved by an accountant yet (KAN-79). Do not act on them until that is done.';

export const SCREENS = [
  { id: 'my-leave', role: 'member', title: 'My leave', sub: 'Balance, history and applying for leave. You can only see your own record; an owner or admin links your sign-in to your employee record first.', sections: [
    form('Balance', H('LEAVE_MANAGEMENT', 'get_balance'), [num('year', 'Year', { required: true })], 'Show balance'),
    form('History', H('LEAVE_MANAGEMENT', 'employee_history'), [num('year', 'Year (blank = all)')], 'Show history'),
    form('Apply for leave', H('LEAVE_MANAGEMENT', 'apply'), [text('leave_type', 'Leave type', { required: true }), { name: 'from_date', label: 'From', type: 'date', required: true }, { name: 'to_date', label: 'To', type: 'date', required: true }, text('reason', 'Reason')], 'Apply'),
  ] },
  { id: 'leave-approvals', role: 'admin', title: 'Leave approvals', sub: 'Pending requests. Approving or rejecting waits for approval in Prime.', sections: [
    load('Pending', H('LEAVE_MANAGEMENT', 'pending_approvals')),
    form('Approve', H('LEAVE_MANAGEMENT', 'approve'), [num('leave_id', 'Leave request id', { required: true })], 'Approve'),
    form('Reject', H('LEAVE_MANAGEMENT', 'reject'), [num('leave_id', 'Leave request id', { required: true })], 'Reject'),
    form('Leave summary (Zoho People)', H('ZOHO_PEOPLE', 'get_leave_summary'), [text('employee_id', 'Employee id', { required: true }), num('year', 'Year')], 'Show', { note: 'Only when Zoho People is connected.' }),
    form('Employee list (Zoho People)', H('ZOHO_PEOPLE', 'get_employees'), [num('page', 'Page (blank = first)')], 'Show', { note: 'Only when Zoho People is connected. Full records can hold identity numbers; shown to owners and admins only.' }),
    form('Attendance records (Zoho People)', H('ZOHO_PEOPLE', 'get_attendance'), [text('employee_id', 'Employee id', { required: true }), text('from_date', 'From (MM-dd-yyyy)', { required: true }), text('to_date', 'To (MM-dd-yyyy)', { required: true })], 'Show', { note: 'Only when Zoho People is connected. Zoho expects dates as month-day-year.' }),
    form('Attendance summary (Zoho People)', H('ZOHO_PEOPLE', 'get_attendance_summary'), [text('employee_id', 'Employee id', { required: true }), text('from_date', 'From (MM-dd-yyyy)', { required: true }), text('to_date', 'To (MM-dd-yyyy)', { required: true })], 'Show', { note: 'Only when Zoho People is connected. Zoho expects dates as month-day-year.' }),
  ] },
  { id: 'my-payslips', role: 'member', title: 'My payslips', banner: DISCLAIMER, sub: 'Your own payslip and year to date. Use the browser print command to print or save as PDF.', sections: [
    form('Payslip', H('PAYROLL_ENGINE', 'get_payslip'), YM, 'Show payslip'),
    form('Year to date', H('PAYROLL_ENGINE', 'get_ytd_summary'), [num('financial_year', 'Financial year (the year it starts)', { required: true })], 'Show'),
    form('Statutory deductions', H('PAYROLL_ENGINE', 'get_statutory_deductions'), YM, 'Show'),
  ] },
  { id: 'payroll', role: 'admin', title: 'Payroll', banner: DISCLAIMER, sub: 'A run calculates; it does not pay anyone. Nothing from these screens is written to the ledger except parameter names.', sections: [
    form('Compute for everyone (one month)', H('PAYROLL_ENGINE', 'compute_bulk'), [json('employees', 'Employees', { required: true, placeholder: '[{"employee_id":"E1","basic":50000,"hra":20000,"special_allowance":10000,"tds":0}]' }), text('pay_period', 'Month (YYYY-MM, blank = this month)')], 'Compute'),
    form('Compute for one employee', H('PAYROLL_ENGINE', 'compute'), [text('employee_id', 'Employee id', { required: true }), num('basic', 'Basic (monthly)', { required: true }), num('hra', 'HRA (monthly)', { required: true }), num('special_allowance', 'Special allowance (monthly)', { required: true }), num('tds', 'TDS'), text('pay_period', 'Month (YYYY-MM)'), text('local_body', 'Local body (professional tax)')], 'Compute'),
    form('Organisation statutory summary', H('PAYROLL_ENGINE', 'org_statutory_summary'), [json('employees', 'Employees', { required: true }), text('pay_period', 'Month (YYYY-MM)')], 'Show'),
    form('Cost to company', H('ZOHO_PAYROLL', 'get_cost_to_company'), [text('employee_id', 'Employee id', { required: true }), ...YM], 'Show'),
  ] },
  { id: 'my-policies', role: 'member', title: 'My policies', sub: 'Policies waiting for your acknowledgement. The text hash you acknowledge is recorded, so the version is proven.', sections: [
    load('Waiting for you', H('POLICY_ACKS', 'pending_for_employee')),
    form('Read a policy', H('POLICY_ACKS', 'get_policy'), [text('policy_key', 'Policy key', { required: true }), num('version', 'Version (blank = current)')], 'Open'),
    form('Acknowledge', H('POLICY_ACKS', 'acknowledge'), [text('policy_key', 'Policy key', { required: true }), text('seen_text_sha256', 'Text hash shown when you opened the policy', { required: true })], 'I have read and acknowledge'),
  ] },
  { id: 'my-onboarding', role: 'member', title: 'My onboarding', sub: 'Your tasks, forms and documents. What you type here goes to Velaris only; it is never written to the audit ledger.', sections: [
    load('Your cases', H('ONBOARDING_FLOW', 'list_cases')),
    form('Tasks of a case', H('ONBOARDING_FLOW', 'case_status'), [text('case_id', 'Case id', { required: true })], 'Show'),
    form('Open a form', H('ONBOARDING_FLOW', 'get_form'), [text('case_id', 'Case id', { required: true }), text('form', 'Form key', { required: true })], 'Open'),
    form('Submit a form', H('ONBOARDING_FLOW', 'submit_form'), [text('case_id', 'Case id', { required: true }), text('form', 'Form key', { required: true }), json('form_fields', 'Answers', { required: true })], 'Submit'),
    form('Submit an identifier (PAN, bank...)', H('ONBOARDING_FLOW', 'submit_identifier'), [text('case_id', 'Case id', { required: true }), text('kind', 'Kind (pan, bank, aadhaar)', { required: true }), { name: 'value', label: 'Value', type: 'password', required: true }, text('ifsc', 'IFSC (bank only)'), text('purpose', 'Purpose (Aadhaar only)')], 'Submit'),
    form('Check Aadhaar', H('ONBOARDING_FLOW', 'check_aadhaar'), [text('case_id', 'Case id', { required: true }), { name: 'number', label: 'Aadhaar number', type: 'password', required: true }], 'Check'),
    form('Upload a document', H('ONBOARDING_FLOW', 'collect_document'), [text('case_id', 'Case id', { required: true }), text('doc_type', 'Document kind', { required: true }), { name: 'content_base64', label: 'Document file', type: 'file', also: 'filename', maxMb: 7, required: true }], 'Upload', { note: 'At most 7 MB. The file is read in your browser and sent once.' }),
  ] },
  { id: 'privacy', role: 'admin', title: 'Employee privacy (DPDP)', banner: LEGAL_REVIEW, sub: 'Export one person\'s data, or erase it. Both are ledgered by id only. Erase waits for a second approver in Prime and reports what is kept for law.', sections: [
    form('Export one employee\'s data', H('EMPLOYEE_RECORDS', 'export_subject'), [text('employee_id', 'Employee id', { required: true })], 'Download export', { typed: 'EXPORT', download: 'employee-export.json' }),
    form('Erase one employee\'s data', H('EMPLOYEE_RECORDS', 'erase_subject'), [text('employee_id', 'Employee id', { required: true }), text('request_ref', 'Reference of the written request', { required: true })], 'Request erasure', { typed: 'ERASE', danger: true, warn: 'Erasure cannot be undone. Records the law requires are kept and listed in the result.' }),
    form('Retention status of one person', H('EMPLOYEE_RECORDS', 'retention_status'), [text('employee_id', 'Employee id', { required: true })], 'Show'),
    load('Retention table', H('EMPLOYEE_RECORDS', 'retention_table'), { note: 'Periods must match what the lawyer approved (KAN-80); until then this table is pending legal review.' }),
    load('Workforce aggregate', H('EMPLOYEE_RECORDS', 'workforce_aggregate')),
    form('Change record (before and after)', H('EMPLOYEE_RECORDS', 'change_record'), [text('employee_id', 'Employee id', { required: true }), { name: 'field', label: 'Field', type: 'select', options: ['department', 'designation', 'manager', 'email', 'phone'], required: true }, text('new_value', 'New value', { required: true }), text('reason', 'Reason', { required: true })], 'Record change'),
  ] },
  { id: 'employee-links', role: 'admin', title: 'Employee links', sub: 'Which employee record each sign-in is. Members see their own leave, payslips and policies only after this link is set.', sections: [
    { kind: 'links' },
  ] },
  { id: 'candidates', role: 'admin', title: 'Candidates and candidate privacy', sub: 'Manual entry, contact, offer outcome, and a candidate\'s data-access or erasure request. Names and emails never go to the audit ledger.', sections: [
    form('Add a candidate', H('ATS_CORE', 'add_candidate'), [text('name', 'Name', { required: true }), text('email', 'Email'), text('phone', 'Phone'), text('source', 'Source', { required: true }), text('requisition_id', 'Requisition id'), json('consent', 'Consent record', { required: true, placeholder: '{"purpose":"hiring","notice_version":"1","retention_until":"2027-12-31","channel":"manual","talent_pool":false}' })], 'Add'),
    form('Add an application', H('ATS_CORE', 'add_application'), [text('candidate_id', 'Candidate id', { required: true }), text('requisition_id', 'Requisition id', { required: true }), text('source', 'Source', { required: true })], 'Add'),
    form('Summary of an application', H('ATS_CORE', 'candidate_summary'), [text('application_id', 'Application id', { required: true })], 'Show'),
    form('Candidate contact (personal data)', H('ATS_CORE', 'candidate_contact'), [text('candidate_id', 'Candidate id', { required: true })], 'Show contact'),
    form('Record offer outcome', H('ATS_CORE', 'record_offer_outcome'), [text('application_id', 'Application id', { required: true }), { name: 'outcome', label: 'Outcome', type: 'select', options: ['accepted', 'declined', 'expired', 'withdrawn'], required: true }, text('offer_id', 'Offer id', { required: true })], 'Record'),
    form('Withdraw consent', H('ATS_CORE', 'withdraw_consent'), [text('candidate_id', 'Candidate id', { required: true })], 'Record withdrawal'),
    form('Export one candidate\'s data', H('ATS_CORE', 'export_candidate'), [text('candidate_id', 'Candidate id', { required: true })], 'Download export', { typed: 'EXPORT', download: 'candidate-export.json' }),
    load('Due for retention erasure', H('ATS_CORE', 'retention_due')),
    form('Erase candidates', H('ATS_CORE', 'erase_candidates'), [list('candidate_ids', 'Candidate ids', { required: true }), { name: 'reason', label: 'Reason', type: 'select', options: ['retention_due', 'consent_withdrawn', 'erasure_request'], required: true }], 'Request erasure', { typed: 'ERASE', danger: true, warn: 'Erasure cannot be undone and waits for approval in Prime.' }),
  ] },
  { id: 'hiring-admin', role: 'admin', title: 'Hiring intake admin', sub: 'Company profile, candidate withdrawals, links for candidates, scheduling follow-ups, bias audit. Links are shown once and are not ledgered.', sections: [
    load('Company profile', H('JOB_POSTINGS', 'get_company_profile')),
    form('Set company profile', H('JOB_POSTINGS', 'set_company_profile'), [text('name', 'Company name', { required: true }), text('website', 'Website', { required: true }), text('careers_base_url', 'Careers base URL', { required: true }), text('contact_email', 'Contact email')], 'Save'),
    load('Withdrawal requests', H('SCREENING_FORMS', 'withdrawal_requests')),
    form('Process a withdrawal', H('SCREENING_FORMS', 'process_withdrawal'), [text('application_id', 'Application id', { required: true })], 'Process'),
    form('Sweep expired submissions', H('SCREENING_FORMS', 'sweep_submissions'), [], 'Sweep now', { danger: true, warn: 'Expired submissions are removed.' }),
    form('Issue a status or withdraw link', H('SCREENING_FORMS', 'issue_candidate_token'), [text('application_id', 'Application id', { required: true }), { name: 'purpose', label: 'Purpose', type: 'select', options: ['status', 'withdraw'] }, num('days', 'Valid days')], 'Issue link', { once: true }),
    form('Issue self-schedule link', H('INTERVIEW_SCHEDULER', 'issue_schedule_token'), [text('application_id', 'Application id', { required: true }), list('interviewer_ids', 'Interviewer ids', { required: true }), num('duration_min', 'Duration (min)', { required: true }), text('title', 'Title', { required: true }), text('location', 'Location / link'), num('days', 'Valid days')], 'Issue link', { once: true }),
    form('Interview reminders', H('INTERVIEW_SCHEDULER', 'reminders'), [num('within_hours', 'Within hours (blank = 24)')], 'Show'),
    form('Mark reminder sent', H('INTERVIEW_SCHEDULER', 'mark_reminder_sent'), [text('booking_id', 'Booking id', { required: true }), text('kind', 'Reminder (24h or 1h)', { required: true })], 'Mark sent'),
    form('Mark no-show (drafts a follow-up)', H('INTERVIEW_SCHEDULER', 'mark_no_show'), [text('booking_id', 'Booking id', { required: true }), { name: 'party', label: 'Who did not attend', type: 'select', options: ['candidate', 'interviewer'], required: true }, text('note', 'Note')], 'Mark no-show'),
    load('Follow-up drafts (no-show and invitations)', H('INTERVIEW_SCHEDULER', 'list_drafts'), { args: { status: 'draft' }, rows: 'drafts', empty: 'No drafts waiting.' }),
    form('Hand an approved invitation to mail', H('INTERVIEW_SCHEDULER', 'hand_off_to_mail'), [text('draft_id', 'Invitation draft id', { required: true })], 'Create mail draft', { note: 'Nothing is sent: a person reads and sends it from the mailbox.' }),
    form('Posting tracking code', H('JOB_POSTINGS', 'resolve_tracking'), [text('code', 'Tracking code', { required: true })], 'Resolve'),
    form('Send indexing notification', H('JOB_POSTINGS', 'send_indexing_notification'), [text('posting_id', 'Posting id', { required: true }), { name: 'kind', label: 'Kind', type: 'select', options: ['URL_UPDATED', 'URL_DELETED'] }], 'Send'),
    form('Bias audit', H('RESUME_EVIDENCE', 'bias_audit'), [json('records', 'Records (one per candidate, with a group label)', { required: true }), list('stages', 'Funnel stages in order', { required: true }), num('min_count', 'Minimum group size')], 'Show report'),
  ] },
  { id: 'offers-admin', role: 'admin', title: 'Offer templates and revisions', sub: 'Templates, compensation preview, revision and the candidate\'s response. A revised offer still needs a second person to approve.', sections: [
    load('Templates', H('OFFER_LETTERS', 'list_templates')),
    form('Add a template', H('OFFER_LETTERS', 'add_template'), [text('name', 'Name', { required: true }), { name: 'body', label: 'Template text', type: 'textarea', required: true }], 'Save template'),
    form('Compensation preview', H('OFFER_LETTERS', 'compensation_preview'), [num('annual_ctc', 'Annual CTC', { required: true }), text('join_month', 'Join month (YYYY-MM)', { required: true }), text('local_body', 'Local body (professional tax)')], 'Preview'),
    form('Revise an unsent offer', H('OFFER_LETTERS', 'revise_offer'), [text('offer_id', 'Offer id', { required: true }), text('reason', 'Reason', { required: true }), num('annual_ctc', 'New annual CTC'), { name: 'join_date', label: 'New join date', type: 'date' }, text('role_title', 'Role title')], 'Revise'),
    form('Record the candidate\'s response', H('OFFER_LETTERS', 'record_response'), [text('offer_id', 'Offer id', { required: true }), { name: 'response', label: 'Response', type: 'select', options: ['accepted', 'declined'], required: true }, text('evidence_ref', 'E-sign request id (stronger evidence)'), text('note', 'Note')], 'Record'),
    form('Expire overdue offers', H('OFFER_LETTERS', 'expire_due'), [], 'Expire now', { danger: true, warn: 'Overdue offers become expired.' }),
  ] },
  { id: 'esign-admin', role: 'admin', title: 'E-sign admin', sub: 'Reminders (they rotate the signer link), overdue requests, seal and download. The download is saved, never opened in the browser.', sections: [
    form('Send reminders to unfinished signers', H('ESIGN', 'send_reminders'), [], 'Send'),
    form('Process overdue requests', H('ESIGN', 'process_due'), [], 'Process now'),
    form('Seal a signed request', H('ESIGN', 'seal_request'), [text('request_id', 'Request id', { required: true })], 'Seal'),
    form('Download sealed document', H('ESIGN', 'get_sealed_document'), [text('request_id', 'Request id', { required: true })], 'Download', { download: 'sealed-document.json', note: 'Compare its hash with the Verify result on the E-sign screen.' }),
    form('Onboarding reminders due', H('ONBOARDING_FLOW', 'reminders_due'), [num('within_days', 'Within days (blank = 2)')], 'Show'),
    form('Policy reminders due', H('POLICY_ACKS', 'reminders_due'), [num('within_days', 'Within days (blank = 3)')], 'Show'),
  ] },
  { id: 'kits-admin', role: 'admin', title: 'Interview kits: rubric, work samples, calibration', sub: 'Scorecards stay locked once submitted.', sections: [
    form('Add a question', H('INTERVIEW_KIT', 'add_question'), [text('text', 'Question', { required: true }), text('competency', 'Competency (must exist)', { required: true }), list('follow_ups', 'Follow-up questions')], 'Add'),
    form('Define a rubric', H('INTERVIEW_KIT', 'define_rubric'), [text('competency', 'Competency', { required: true }), text('description', 'Description', { required: true }), json('anchors', 'Anchors by level', { required: true, placeholder: '{"1":"...","2":"...","3":"...","4":"...","5":"..."}' })], 'Save'),
    form('Create a work sample', H('INTERVIEW_KIT', 'create_work_sample'), [text('title', 'Title', { required: true }), { name: 'brief', label: 'Brief', type: 'textarea', required: true }, list('checklist', 'Checklist (one observable item per line)', { required: true }), num('time_limit_min', 'Time limit (min)'), { name: 'ai_tools_allowed', label: 'AI tools allowed', type: 'checkbox' }], 'Create'),
    load('Work samples', H('INTERVIEW_KIT', 'list_work_samples')),
    form('Review a work sample', H('INTERVIEW_KIT', 'review_work_sample'), [text('application_id', 'Application id', { required: true }), text('work_sample_id', 'Work sample id', { required: true }), json('checks', 'Checks (met or not, with the evidence seen)', { required: true }), { name: 'notes', label: 'Notes', type: 'textarea' }], 'Submit review'),
    form('Reviews of an application', H('INTERVIEW_KIT', 'work_sample_reviews'), [text('application_id', 'Application id', { required: true })], 'Show'),
    load('Calibration report', H('INTERVIEW_KIT', 'calibration_report'), { rows: 'competencies', chart: { label: 'competency', value: 'krippendorff_alpha_ordinal', min: 0, max: 1 }, compare: 'rater_leniency_offset', note: 'Agreement between interviewers per competency (Krippendorff alpha, 1 = full agreement). A short bar means the rubric needs rewriting.' }),
  ] },
  { id: 'interview-records', role: 'admin', title: 'Interview records', sub: 'Sessions, participant link, consent, audio and evidence. Consent is checked before recording; evidence never shows automatic scores. The candidate\'s own consent and audio upload go through their link, not here.', sections: [
    form('Sessions', H('INTERVIEW_RECORD', 'list_sessions'), [text('application_id', 'Application id (blank = all)')], 'List'),
    form('Create a session', H('INTERVIEW_RECORD', 'create_session'), [text('application_id', 'Application id', { required: true }), list('interviewer_ids', 'Interviewer ids', { required: true }), num('retention_days', 'Keep for days')], 'Create'),
    form('Participant link', H('INTERVIEW_RECORD', 'issue_participant_token'), [text('session_id', 'Session id', { required: true }), text('participant', 'Participant (candidate or an interviewer id)'), num('hours', 'Valid hours')], 'Issue link', { once: true }),
    form('Give my consent to be recorded', H('INTERVIEW_RECORD', 'give_consent'), [text('session_id', 'Session id', { required: true }), list('scopes', 'Scopes (events, audio, transcript)', { required: true }), text('notice_version', 'Notice version shown', { required: true })], 'Consent'),
    form('Withdraw my consent', H('INTERVIEW_RECORD', 'withdraw_my_consent'), [text('session_id', 'Session id', { required: true })], 'Withdraw', { danger: true, warn: 'Recording for you stops at once.' }),
    form('Register an audio track', H('INTERVIEW_RECORD', 'register_audio_track'), [text('session_id', 'Session id', { required: true }), text('participant', 'Participant', { required: true }), text('sha256', 'SHA-256 of the file', { required: true }), num('size_bytes', 'Size (bytes)', { required: true }), num('duration_s', 'Duration (seconds)', { required: true }), text('mime', 'Type (audio/wav, audio/webm ...)', { required: true })], 'Register', { note: 'For a track held in the recorder\'s own store. A candidate uploading audio uses the upload on their interview link.' }),
    form('Transcribe a track', H('INTERVIEW_RECORD', 'transcribe_track'), [text('session_id', 'Session id', { required: true }), text('participant', 'Participant', { required: true })], 'Transcribe', { note: 'Needs transcript consent. Says so when no transcriber is configured.' }),
    form('Mark an event', H('INTERVIEW_RECORD', 'mark_event'), [text('session_id', 'Session id', { required: true }), num('seq', 'Event number', { required: true }), { name: 'mark', label: 'Mark', type: 'select', options: ['relevant', 'explained'], required: true }, text('reason', 'Reason', { required: true })], 'Mark'),
    form('Replay the pad', H('INTERVIEW_RECORD', 'replay_pad'), [text('session_id', 'Session id', { required: true }), text('pad_id', 'Pad (blank = main)'), num('upto_seq', 'Up to event (blank = end)')], 'Show'),
    form('Evidence and consent state', H('INTERVIEW_RECORD', 'evidence_view'), [text('session_id', 'Session id', { required: true })], 'Show', { view: 'evidence', note: 'Shows who has consented to be recorded, and for what, above the events. A withdrawn consent is shown as withdrawn.' }),
    form('Close the session', H('INTERVIEW_RECORD', 'close_session'), [text('session_id', 'Session id', { required: true })], 'Close', { danger: true, warn: 'A closed session cannot be reopened.' }),
  ] },
  { id: 'my-chat-data', role: 'member', title: 'My chat data', sub: 'Download everything Velaris holds about you in chat.', sections: [
    form('Download my chat data', { ...P('get', '/chat/me/export') }, [], 'Download', { download: 'my-chat-data.json', raw: true }),
  ] },
  { id: 'chat-privacy', role: 'admin', title: 'Chat privacy (admin)', sub: 'One person\'s chat data. Messages in channels on legal hold are reported as kept, not erased. Both actions are ledgered by id.', sections: [
    { kind: 'form', title: 'Export a person\'s chat data', call: { method: 'get', path: '/chat/admin/users/{user_id}/export' }, fields: [text('user_id', 'User id', { required: true })], submit: 'Download export', download: 'chat-user-export.json', path_params: ['user_id'], raw: true },
    { kind: 'form', title: 'Erase a person\'s chat data', call: { method: 'post', path: '/chat/admin/users/{user_id}/erase' }, fields: [text('user_id', 'User id', { required: true })], submit: 'Erase', typed: 'ERASE', danger: true, warn: 'Messages in channels on legal hold are kept; the answer says which.', path_params: ['user_id'], raw: true },
    { kind: 'form', title: 'Erase one message', call: { method: 'post', path: '/chat/admin/messages/{message_id}/erase' }, fields: [text('message_id', 'Message id', { required: true })], submit: 'Erase message', typed: 'ERASE', danger: true, path_params: ['message_id'], raw: true },
  ] },
  { id: 'mail-admin', role: 'admin', title: 'Mail provisioning', sub: 'Mailboxes, aliases, delegates (shared mailboxes), quota and organisation mail settings. Each change is ledgered. Delegation can only be set by the mailbox owner.', sections: [
    { kind: 'form', title: 'Create a mailbox', call: P('post', '/mail/mailboxes'), fields: [text('address', 'Address', { required: true }), text('owner_id', 'Owner (user id)')], submit: 'Create', raw: true },
    { kind: 'form', title: 'Add an alias', call: { method: 'put', path: '/mail/mailboxes/{mb}/aliases' }, fields: [text('mb', 'Mailbox id', { required: true }), text('address', 'Alias address', { required: true })], submit: 'Add alias', path_params: ['mb'], raw: true },
    { kind: 'form', title: 'Delegates of a mailbox', call: { method: 'get', path: '/mail/mailboxes/{mb}/delegates' }, fields: [text('mb', 'Mailbox id', { required: true })], submit: 'Show', path_params: ['mb'], raw: true },
    { kind: 'form', title: 'Add a delegate', call: { method: 'put', path: '/mail/mailboxes/{mb}/delegates' }, fields: [text('mb', 'Mailbox id', { required: true }), text('user_id', 'User id', { required: true }), list('rights', 'Rights (read, send, manage, approve)', { required: true })], submit: 'Add', path_params: ['mb'], raw: true },
    { kind: 'form', title: 'Remove a delegate', call: { method: 'delete', path: '/mail/mailboxes/{mb}/delegates' }, fields: [text('mb', 'Mailbox id', { required: true }), text('user_id', 'User id', { required: true })], submit: 'Remove', path_params: ['mb'], query: true, raw: true },
    { kind: 'form', title: 'Set quota', call: { method: 'put', path: '/mail/mailboxes/{mb}/quota' }, fields: [text('mb', 'Mailbox id', { required: true }), num('quota_bytes', 'Quota (bytes)', { required: true })], submit: 'Save quota', path_params: ['mb'], raw: true },
    { kind: 'form', title: 'Organisation mail settings', call: P('put', '/mail/settings'), fields: [num('max_recipients', 'Most recipients without a second approver'), num('undo_window_s', 'Undo window (seconds)'), num('retention_days', 'Keep mail for days (0 = forever)'), num('trash_retention_days', 'Keep trash for days'), num('spam_retention_days', 'Keep spam for days'), { name: 'autoreply_external', label: 'Auto-reply to outside senders', type: 'checkbox' }], submit: 'Save settings', raw: true },
  ] },
  { id: 'mail-compliance', role: 'admin', title: 'Mail compliance', sub: 'A legal hold blocks erase and retention for held items; Velaris reports what it kept.', sections: [
    { kind: 'form', title: 'Legal hold on a mailbox', call: { method: 'put', path: '/mail/mailboxes/{mb}/legal-hold' }, fields: [text('mb', 'Mailbox id', { required: true }), list('message_ids', 'Message ids (blank = the whole mailbox)', { help: 'Separate with commas or new lines. Up to 1000.' }), { name: 'on', label: 'Hold on (untick to release)', type: 'checkbox' }], submit: 'Apply', path_params: ['mb'], raw: true },
    { kind: 'form', title: 'Preview retention (removes nothing)', call: P('post', '/mail/retention/run'), fields: [], fixed: { dry_run: true }, submit: 'Preview', note: 'Counts per kind (trash, spam, age) that a run would remove. Held items are not counted.', raw: true },
    { kind: 'form', title: 'Run retention now', call: P('post', '/mail/retention/run'), fields: [], submit: 'Run retention', danger: true, warn: 'Mail past its retention period is removed (except items on legal hold). Preview first. The answer lists how many were removed per kind.', raw: true },
    { kind: 'form', title: 'Erase a mailbox (DPDP)', call: { method: 'delete', path: '/mail/mailboxes/{mb}' }, fields: [text('mb', 'Mailbox id', { required: true })], submit: 'Erase mailbox', typed: 'ERASE', danger: true, warn: 'The mailbox data is removed, except items on legal hold.', path_params: ['mb'], raw: true },
    { kind: 'form', title: 'Process the outbox now', call: P('post', '/mail/outbox/process'), fields: [], submit: 'Process', note: 'Nothing sends due mail unless the Velaris outbox worker is installed (deploy/systemd/velaris-outbox.service); this runs it at once.', raw: true },
  ] },
  { id: 'mail-accounts', role: 'admin', title: 'External mail accounts', sub: 'Connect an IMAP/SMTP account. Only the vault secret NAME is stored here: put the password in the Velaris secrets vault first (name starts with mail.). Velaris allows this to a mail administrator only.', sections: [
    { kind: 'form', title: 'Accounts of a mailbox', call: { method: 'get', path: '/mail/mailboxes/{mb}/accounts' }, fields: [text('mb', 'Mailbox id', { required: true })], submit: 'Show', path_params: ['mb'], raw: true },
    { kind: 'form', title: 'Add an account', call: { method: 'post', path: '/mail/mailboxes/{mb}/accounts' }, fields: [text('mb', 'Mailbox id', { required: true }), text('imap_host', 'IMAP host', { required: true }), num('imap_port', 'IMAP port'), text('username', 'User name', { required: true }), text('secret_name', 'Vault secret name (mail.something)', { required: true }), text('smtp_host', 'SMTP host'), num('smtp_port', 'SMTP port'), { name: 'smtp_security', label: 'SMTP security', type: 'select', options: ['starttls', 'ssl'] }], submit: 'Connect', path_params: ['mb'], raw: true },
    { kind: 'form', title: 'Remove an account (deletes its stored settings)', call: { method: 'delete', path: '/mail/mailboxes/{mb}/accounts/{aid}' }, fields: [text('mb', 'Mailbox id', { required: true }), text('aid', 'Account id', { required: true })], submit: 'Remove', danger: true, path_params: ['mb', 'aid'], raw: true },
    { kind: 'form', title: 'Sync now', call: { method: 'post', path: '/mail/mailboxes/{mb}/sync' }, fields: [text('mb', 'Mailbox id', { required: true })], submit: 'Sync', path_params: ['mb'], note: 'Shows counts, or a plain error such as authentication failed or host unreachable.', raw: true },
  ] },
  { id: 'jira', role: 'member', title: 'Jira', sub: 'Searching and reading need the Atlassian reader role in Velaris and no approval. Creating or moving an issue waits for approval.', sections: [
    form('Search issues', A('JIRA', 'search_issues'), [text('jql', 'JQL query', { required: true }), num('max_results', 'Most results')], 'Search'),
    form('Open an issue', A('JIRA', 'get_issue'), [text('key', 'Issue key', { required: true })], 'Open', { view: 'issue' }),
    form('Available transitions', A('JIRA', 'get_transitions'), [text('key', 'Issue key', { required: true })], 'Show'),
    form('Move an issue', A('JIRA', 'transition_issue'), [text('key', 'Issue key', { required: true }), text('transition_id', 'Transition id (from Available transitions)', { required: true })], 'Request move'),
    form('Create an issue', A('JIRA', 'create_issue'), [text('project_key', 'Project key', { required: true }), text('summary', 'Summary', { required: true }), text('issue_type', 'Type (blank = Task)'), { name: 'description', label: 'Description', type: 'textarea' }], 'Request create'),
    load('Projects', A('JIRA', 'list_projects')),
  ] },
  { id: 'confluence', role: 'member', title: 'Confluence', sub: 'Page text is shown as plain text. Ingesting a space waits for approval.', sections: [
    form('Search Confluence', A('CONFLUENCE', 'search'), [text('cql', 'CQL query', { required: true }), num('limit', 'Most results')], 'Search'),
    form('Read a page', A('CONFLUENCE', 'get_page_markdown'), [text('page_id', 'Page id', { required: true })], 'Open'),
    load('Spaces', A('CONFLUENCE', 'list_spaces')),
    form('Ingest a space into the library', A('CONFLUENCE', 'ingest_space'), [text('space_key', 'Space key', { required: true }), num('max_pages', 'Most pages')], 'Request ingest', { fixed: { scope: '@org' }, danger: true, warn: 'The whole space is copied into the document library after approval.' }),
  ] },
  { id: 'tickets', role: 'member', title: 'Tickets and SLA', sub: 'IT service tickets. Moving a ticket waits for approval.', sections: [
    form('Tickets', A('ITSM_ENGINE', 'list_tickets'), [text('state', 'State (blank = all)')], 'List'),
    form('Ticket', A('ITSM_ENGINE', 'get_ticket'), [text('ticket_id', 'Ticket id', { required: true })], 'Open'),
    form('SLA status', A('ITSM_ENGINE', 'sla_status'), [text('ticket_id', 'Ticket id', { required: true })], 'Show'),
    form('Move a ticket', A('ITSM_ENGINE', 'transition'), [text('ticket_id', 'Ticket id', { required: true }), text('to', 'New state', { required: true }), text('note', 'Note')], 'Request move'),
  ] },
  { id: 'finance', role: 'member', title: 'Finance view', sub: 'Runway, reserves and expense forecast from numbers you enter. Rule-based estimates, not advice.', sections: [
    form('Cash flow', A('TREASURIX', 'project_cashflow'), [nums('inflows', 'Inflows per period', { required: true }), nums('outflows', 'Outflows per period', { required: true })], 'Project'),
    form('Reserve ratio', A('TREASURIX', 'reserve_ratio'), [num('liquid_assets', 'Liquid assets', { required: true }), num('short_term_liabilities', 'Short-term liabilities', { required: true })], 'Show'),
    form('Runway (months)', A('TREASURIX', 'runway_months'), [num('monthly_burn', 'Monthly burn', { required: true }), num('reserves', 'Reserves')], 'Show'),
    form('Cost breakdown', A('FISCALIS', 'cost_breakdown'), [json('costs', 'Costs by category', { required: true, placeholder: '{"rent":50000,"salaries":400000}' })], 'Total'),
    form('Expense forecast', A('FISCALIS', 'forecast_expenses'), [nums('monthly_costs', 'Monthly costs, oldest first', { required: true }), num('growth_rate', 'Growth rate (0.05 = 5%)')], 'Forecast'),
  ] },
  { id: 'library', role: 'member', title: 'Document library', sub: 'Answers show their sources as links.', sections: [
    form('Ask the library', A('DOCUMENT_LIBRARY', 'ask'), [text('question', 'Question', { required: true })], 'Ask', { fixed: { scope: '@org' } }),
    form('Search the library', A('DOCUMENT_LIBRARY', 'search'), [text('query', 'Search', { required: true }), num('k', 'Most results')], 'Search', { fixed: { scope: '@org' } }),
  ] },
  { id: 'research', role: 'member', title: 'Research and web search', sub: 'Research and web search can be slow and use quota. Sources are links.', sections: [
    form('Research a topic (slow)', A('AUTONOMOUS_RESEARCH_ENGINE', 'research'), [text('question', 'Question', { required: true })], 'Research'),
    form('Web search', A('ADVANCED_SEARCH_ENGINE', 'web_search'), [text('query', 'Search', { required: true })], 'Search'),
    form('Read a web page', A('ADVANCED_SEARCH_ENGINE', 'read_page'), [text('url', 'Address', { required: true })], 'Read'),
  ] },
  { id: 'council', role: 'member', title: 'Model council', sub: 'Several models answer and the differences are shown.', sections: [
    form('Ask the model council', A('MODEL_COUNCIL', 'deliberate'), [text('question', 'Question', { required: true }), { name: 'context', label: 'Context', type: 'textarea' }], 'Deliberate'),
  ] },
  { id: 'memory', role: 'member', title: 'Long-term memory', sub: 'Remembering waits for approval.', sections: [
    form('Recall from memory', A('LONGTERM_MEMORY', 'recall'), [text('query', 'What', { required: true })], 'Recall', { fixed: { scope: '@org' } }),
    form('Remember', A('LONGTERM_MEMORY', 'remember'), [{ name: 'text', label: 'To remember', type: 'textarea', required: true }], 'Request remember', { fixed: { scope: '@org' } }),
  ] },
];

export const screenById = (id) => SCREENS.find((s) => s.id === id);
