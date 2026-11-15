// Velaris gap screens as DATA, rendered by ActionScreen.jsx. role: 'member' (any role that may act; Velaris still
// limits a member to their own records) or 'admin' (owner/admin; the gateway refuses anyone else).
// Field names the Velaris agents take are not visible from this repo: each form also has an "Other fields (JSON)"
// box, so a method's extra arguments never need a code change. Org/actor keys are refused by the gateway.
const H = (a, m) => ({ hr: [a, m] });
const A = (a, m) => ({ agent: [a, m] });
const P = (method, path) => ({ method, path });
const text = (name, label, extra = {}) => ({ name, label, type: 'text', ...extra });
const load = (title, call, extra = {}) => ({ kind: 'load', title, call, ...extra });
const form = (title, call, fields, submit, extra = {}) => ({ kind: 'form', title, call, fields, submit, ...extra });
const DISCLAIMER = 'Payroll figures are calculations, not payments, and are not approved by an accountant yet (KAN-79). Do not act on them until that is done.';

export const SCREENS = [
  { id: 'my-leave', role: 'member', title: 'My leave', sub: 'Balance, history and applying for leave. You can only see your own record.', sections: [
    load('Balance', H('LEAVE_MANAGEMENT', 'get_balance')),
    load('History', H('LEAVE_MANAGEMENT', 'employee_history')),
    form('Apply for leave', H('LEAVE_MANAGEMENT', 'apply'), [text('leave_type', 'Leave type', { required: true }), { name: 'start_date', label: 'From', type: 'date', required: true }, { name: 'end_date', label: 'To', type: 'date', required: true }, text('reason', 'Reason')], 'Apply'),
  ] },
  { id: 'leave-approvals', role: 'admin', title: 'Leave approvals', sub: 'Pending requests. Approving or rejecting waits for approval in Prime.', sections: [
    load('Pending', H('LEAVE_MANAGEMENT', 'pending_approvals')),
    form('Approve', H('LEAVE_MANAGEMENT', 'approve'), [text('request_id', 'Request id', { required: true }), text('note', 'Note')], 'Approve'),
    form('Reject', H('LEAVE_MANAGEMENT', 'reject'), [text('request_id', 'Request id', { required: true }), text('reason', 'Reason', { required: true })], 'Reject'),
    load('Leave summary (Zoho People)', H('ZOHO_PEOPLE', 'get_leave_summary'), { note: 'Only when Zoho People is connected.' }),
    load('Attendance summary (Zoho People)', H('ZOHO_PEOPLE', 'get_attendance_summary')),
  ] },
  { id: 'my-payslips', role: 'member', title: 'My payslips', banner: DISCLAIMER, sub: 'Your own payslip and year to date. Use the browser print command to print or save as PDF.', sections: [
    form('Payslip', H('PAYROLL_ENGINE', 'get_payslip'), [text('period', 'Month (YYYY-MM)', { required: true })], 'Show payslip'),
    load('Year to date', H('PAYROLL_ENGINE', 'get_ytd_summary')),
    form('Statutory deductions', H('PAYROLL_ENGINE', 'get_statutory_deductions'), [text('period', 'Month (YYYY-MM)', { required: true })], 'Show'),
  ] },
  { id: 'payroll', role: 'admin', title: 'Payroll', banner: DISCLAIMER, sub: 'A run calculates; it does not pay anyone. Nothing from these screens is written to the ledger except parameter names.', sections: [
    form('Compute for everyone (one month)', H('PAYROLL_ENGINE', 'compute_bulk'), [text('period', 'Month (YYYY-MM)', { required: true })], 'Compute'),
    form('Compute for one employee', H('PAYROLL_ENGINE', 'compute'), [text('employee_id', 'Employee id', { required: true }), text('period', 'Month (YYYY-MM)', { required: true })], 'Compute'),
    form('Organisation statutory summary', H('PAYROLL_ENGINE', 'org_statutory_summary'), [text('period', 'Month (YYYY-MM)', { required: true })], 'Show'),
    form('Cost to company', H('ZOHO_PAYROLL', 'get_cost_to_company'), [text('employee_id', 'Employee id', { required: true })], 'Show'),
  ] },
  { id: 'my-policies', role: 'member', title: 'My policies', sub: 'Policies waiting for your acknowledgement. The version you acknowledge is recorded.', sections: [
    load('Waiting for you', H('POLICY_ACKS', 'pending_for_employee')),
    form('Read a policy', H('POLICY_ACKS', 'get_policy'), [text('policy_key', 'Policy key', { required: true })], 'Open'),
    form('Acknowledge', H('POLICY_ACKS', 'acknowledge'), [text('policy_key', 'Policy key', { required: true }), text('version', 'Version shown', { required: true })], 'I have read and acknowledge'),
  ] },
  { id: 'my-onboarding', role: 'member', title: 'My onboarding', sub: 'Your tasks, forms and documents. What you type here goes to Velaris only; it is never written to the audit ledger.', sections: [
    load('Your tasks', H('ONBOARDING_FLOW', 'case_status')),
    form('Open a form', H('ONBOARDING_FLOW', 'get_form'), [text('form_key', 'Form key', { required: true })], 'Open'),
    form('Submit a form', H('ONBOARDING_FLOW', 'submit_form'), [text('form_key', 'Form key', { required: true }), { name: 'values', label: 'Answers', type: 'json', required: true }], 'Submit'),
    form('Submit an identifier (PAN, bank...)', H('ONBOARDING_FLOW', 'submit_identifier'), [text('kind', 'Kind', { required: true }), { name: 'value', label: 'Value', type: 'password', required: true }], 'Submit', { raw: false }),
    form('Check Aadhaar', H('ONBOARDING_FLOW', 'check_aadhaar'), [{ name: 'value', label: 'Aadhaar number', type: 'password', required: true }], 'Check'),
    form('Upload a document', H('ONBOARDING_FLOW', 'collect_document'), [text('kind', 'Document kind', { required: true }), { name: 'content_base64', label: 'Document (base64)', type: 'textarea', required: true }], 'Upload', { note: 'At most about 7 MB of file.' }),
  ] },
  { id: 'privacy', role: 'admin', title: 'Employee privacy (DPDP)', sub: 'Export one person\'s data, or erase it. Both are ledgered by id only. Erase waits for a second approver in Prime and reports what is kept for law.', sections: [
    form('Export one employee\'s data', H('EMPLOYEE_RECORDS', 'export_subject'), [text('employee_id', 'Employee id', { required: true })], 'Download export', { typed: 'EXPORT', download: 'employee-export.json' }),
    form('Erase one employee\'s data', H('EMPLOYEE_RECORDS', 'erase_subject'), [text('employee_id', 'Employee id', { required: true })], 'Request erasure', { typed: 'ERASE', danger: true, warn: 'Erasure cannot be undone. Records the law requires are kept and listed in the result.' }),
    load('Retention status', H('EMPLOYEE_RECORDS', 'retention_status')),
    load('Retention table', H('EMPLOYEE_RECORDS', 'retention_table'), { note: 'Periods must match what the lawyer approved (KAN-80).' }),
    load('Workforce aggregate', H('EMPLOYEE_RECORDS', 'workforce_aggregate')),
    form('Change record (before and after)', H('EMPLOYEE_RECORDS', 'change_record'), [text('employee_id', 'Employee id', { required: true }), { name: 'changes', label: 'Changes', type: 'json', required: true }], 'Record change'),
  ] },
  { id: 'candidates', role: 'admin', title: 'Candidates and candidate privacy', sub: 'Manual entry, contact, offer outcome, and a candidate\'s data-access or erasure request. Names and emails never go to the audit ledger.', sections: [
    form('Add a candidate', H('ATS_CORE', 'add_candidate'), [text('name', 'Name', { required: true }), text('email', 'Email'), text('source', 'Source')], 'Add'),
    form('Add an application', H('ATS_CORE', 'add_application'), [text('candidate_id', 'Candidate id', { required: true }), text('requisition_id', 'Requisition id', { required: true })], 'Add'),
    form('Candidate summary', H('ATS_CORE', 'candidate_summary'), [text('candidate_id', 'Candidate id', { required: true })], 'Show'),
    form('Candidate contact (personal data)', H('ATS_CORE', 'candidate_contact'), [text('candidate_id', 'Candidate id', { required: true })], 'Show contact'),
    form('Record offer outcome', H('ATS_CORE', 'record_offer_outcome'), [text('application_id', 'Application id', { required: true }), text('outcome', 'Outcome', { required: true })], 'Record'),
    form('Withdraw consent', H('ATS_CORE', 'withdraw_consent'), [text('candidate_id', 'Candidate id', { required: true })], 'Record withdrawal'),
    form('Export one candidate\'s data', H('ATS_CORE', 'export_candidate'), [text('candidate_id', 'Candidate id', { required: true })], 'Download export', { typed: 'EXPORT', download: 'candidate-export.json' }),
    load('Due for retention erasure', H('ATS_CORE', 'retention_due')),
    form('Erase candidates', H('ATS_CORE', 'erase_candidates'), [text('candidate_id', 'Candidate id (blank = all past retention)')], 'Request erasure', { typed: 'ERASE', danger: true, warn: 'Erasure cannot be undone and waits for approval in Prime.' }),
  ] },
  { id: 'hiring-admin', role: 'admin', title: 'Hiring intake admin', sub: 'Company profile, candidate withdrawals, links for candidates, scheduling follow-ups, bias audit. Links are shown once and are not ledgered.', sections: [
    load('Company profile', H('JOB_POSTINGS', 'get_company_profile')),
    form('Set company profile', H('JOB_POSTINGS', 'set_company_profile'), [text('careers_base_url', 'Careers base URL', { required: true }), text('company_name', 'Company name')], 'Save'),
    load('Withdrawal requests', H('SCREENING_FORMS', 'withdrawal_requests')),
    form('Process a withdrawal', H('SCREENING_FORMS', 'process_withdrawal'), [text('request_id', 'Request id', { required: true })], 'Process'),
    form('Sweep expired submissions', H('SCREENING_FORMS', 'sweep_submissions'), [], 'Sweep now', { danger: true, warn: 'Expired submissions are removed.' }),
    form('Issue candidate form link', H('SCREENING_FORMS', 'issue_candidate_token'), [text('form_id', 'Form id', { required: true }), text('application_id', 'Application id')], 'Issue link', { once: true }),
    form('Issue self-schedule link', H('INTERVIEW_SCHEDULER', 'issue_schedule_token'), [text('booking_id', 'Booking or application id', { required: true })], 'Issue link', { once: true }),
    load('Interview reminders', H('INTERVIEW_SCHEDULER', 'reminders')),
    form('Mark reminder sent', H('INTERVIEW_SCHEDULER', 'mark_reminder_sent'), [text('booking_id', 'Booking id', { required: true })], 'Mark sent'),
    form('Mark no-show (drafts a follow-up)', H('INTERVIEW_SCHEDULER', 'mark_no_show'), [text('booking_id', 'Booking id', { required: true })], 'Mark no-show'),
    form('Posting tracking', H('JOB_POSTINGS', 'resolve_tracking'), [text('posting_id', 'Posting id', { required: true })], 'Resolve'),
    form('Send indexing notification', H('JOB_POSTINGS', 'send_indexing_notification'), [text('posting_id', 'Posting id', { required: true })], 'Send'),
    form('Bias audit', H('RESUME_EVIDENCE', 'bias_audit'), [text('requisition_id', 'Requisition id', { required: true })], 'Show report'),
  ] },
  { id: 'offers-admin', role: 'admin', title: 'Offer templates and revisions', sub: 'Templates, compensation preview and revision. A revised offer still needs a second person to approve.', sections: [
    load('Templates', H('OFFER_LETTERS', 'list_templates')),
    form('Add a template', H('OFFER_LETTERS', 'add_template'), [text('template_key', 'Key', { required: true }), { name: 'body', label: 'Template text', type: 'textarea', required: true }], 'Save template'),
    form('Compensation preview', H('OFFER_LETTERS', 'compensation_preview'), [{ name: 'ctc', label: 'CTC', type: 'number', required: true }], 'Preview'),
    form('Revise a rejected offer', H('OFFER_LETTERS', 'revise_offer'), [text('offer_id', 'Offer id', { required: true })], 'Revise'),
    form('Expire overdue offers', H('OFFER_LETTERS', 'expire_due'), [], 'Expire now', { danger: true, warn: 'Overdue offers become expired.' }),
  ] },
  { id: 'esign-admin', role: 'admin', title: 'E-sign admin', sub: 'Reminders (they rotate the signer link), overdue requests, seal and download. The download is saved, never opened in the browser.', sections: [
    form('Send reminders', H('ESIGN', 'send_reminders'), [text('request_id', 'Request id', { required: true })], 'Send'),
    form('Process overdue requests', H('ESIGN', 'process_due'), [], 'Process now'),
    form('Seal a signed request', H('ESIGN', 'seal_request'), [text('request_id', 'Request id', { required: true })], 'Seal'),
    form('Download sealed document', H('ESIGN', 'get_sealed_document'), [text('request_id', 'Request id', { required: true })], 'Download', { download: 'sealed-document.json', note: 'Compare its hash with the Verify result on the E-sign screen.' }),
    load('Onboarding reminders due', H('ONBOARDING_FLOW', 'reminders_due')),
    load('Policy reminders due', H('POLICY_ACKS', 'reminders_due')),
  ] },
  { id: 'kits-admin', role: 'admin', title: 'Interview kits: rubric, work samples, calibration', sub: 'Scorecards stay locked once submitted.', sections: [
    form('Add a question', H('INTERVIEW_KIT', 'add_question'), [text('text', 'Question', { required: true }), text('competency', 'Competency')], 'Add'),
    form('Define a rubric', H('INTERVIEW_KIT', 'define_rubric'), [text('kit_id', 'Kit id', { required: true }), { name: 'rubric', label: 'Rubric', type: 'json', required: true }], 'Save'),
    form('Create a work sample', H('INTERVIEW_KIT', 'create_work_sample'), [text('application_id', 'Application id', { required: true }), { name: 'brief', label: 'Brief', type: 'textarea', required: true }], 'Create'),
    form('Work samples', H('INTERVIEW_KIT', 'list_work_samples'), [text('application_id', 'Application id')], 'List'),
    form('Review a work sample', H('INTERVIEW_KIT', 'review_work_sample'), [text('sample_id', 'Sample id', { required: true }), { name: 'review', label: 'Review', type: 'json', required: true }], 'Submit review'),
    form('Reviews of a work sample', H('INTERVIEW_KIT', 'work_sample_reviews'), [text('sample_id', 'Sample id', { required: true })], 'Show'),
    form('Calibration report', H('INTERVIEW_KIT', 'calibration_report'), [text('requisition_id', 'Requisition id', { required: true })], 'Show'),
  ] },
  { id: 'interview-records', role: 'member', title: 'Interview records', sub: 'Sessions, participant link and evidence. Consent is checked before recording; evidence never shows automatic scores.', sections: [
    load('Sessions', H('INTERVIEW_RECORD', 'list_sessions')),
    form('Create a session', H('INTERVIEW_RECORD', 'create_session'), [text('booking_id', 'Booking id', { required: true })], 'Create'),
    form('Participant link', H('INTERVIEW_RECORD', 'issue_participant_token'), [text('session_id', 'Session id', { required: true })], 'Issue link', { once: true }),
    form('Mark an event', H('INTERVIEW_RECORD', 'mark_event'), [text('session_id', 'Session id', { required: true }), text('label', 'Label', { required: true })], 'Mark'),
    form('Replay the pad', H('INTERVIEW_RECORD', 'replay_pad'), [text('session_id', 'Session id', { required: true })], 'Show'),
    form('Evidence', H('INTERVIEW_RECORD', 'evidence_view'), [text('session_id', 'Session id', { required: true })], 'Show'),
    form('Close the session', H('INTERVIEW_RECORD', 'close_session'), [text('session_id', 'Session id', { required: true })], 'Close', { danger: true, warn: 'A closed session cannot be reopened.' }),
  ] },
  { id: 'my-chat-data', role: 'member', title: 'My chat data', sub: 'Download everything Velaris holds about you in chat.', sections: [
    form('Download my chat data', { ...P('get', '/chat/me/export') }, [], 'Download', { download: 'my-chat-data.json', raw: true }),
  ] },
  { id: 'chat-privacy', role: 'admin', title: 'Chat privacy (admin)', sub: 'One person\'s chat data. Messages in channels on legal hold are reported as kept, not erased. Both actions are ledgered by id.', sections: [
    { kind: 'form', title: 'Export a person\'s chat data', call: { method: 'get', path: '/chat/admin/users/{user_id}/export' }, fields: [text('user_id', 'User id', { required: true })], submit: 'Download export', download: 'chat-user-export.json', path_params: ['user_id'], raw: true },
    { kind: 'form', title: 'Erase a person\'s chat data', call: { method: 'post', path: '/chat/admin/users/{user_id}/erase' }, fields: [text('user_id', 'User id', { required: true })], submit: 'Erase', typed: 'ERASE', danger: true, warn: 'Messages in channels on legal hold are kept; the answer says which.', path_params: ['user_id'], raw: true },
    { kind: 'form', title: 'Erase one message', call: { method: 'post', path: '/chat/admin/messages/{message_id}/erase' }, fields: [text('message_id', 'Message id', { required: true })], submit: 'Erase message', danger: true, path_params: ['message_id'], raw: true },
  ] },
  { id: 'mail-admin', role: 'admin', title: 'Mail provisioning', sub: 'Mailboxes, aliases, delegates (shared mailboxes), quota and organisation mail settings. Each change is ledgered.', sections: [
    { kind: 'form', title: 'Create a mailbox', call: P('post', '/mail/mailboxes'), fields: [text('address', 'Address', { required: true }), text('owner', 'Owner (user id)')], submit: 'Create' },
    { kind: 'form', title: 'Set aliases', call: { method: 'put', path: '/mail/mailboxes/{mb}/aliases' }, fields: [text('mb', 'Mailbox id', { required: true }), { name: 'aliases', label: 'Aliases (one per line)', type: 'list', required: true }], submit: 'Save aliases', path_params: ['mb'] },
    { kind: 'form', title: 'Delegates of a mailbox', call: { method: 'get', path: '/mail/mailboxes/{mb}/delegates' }, fields: [text('mb', 'Mailbox id', { required: true })], submit: 'Show', path_params: ['mb'] },
    { kind: 'form', title: 'Add a delegate', call: { method: 'put', path: '/mail/mailboxes/{mb}/delegates' }, fields: [text('mb', 'Mailbox id', { required: true }), text('user_id', 'User id', { required: true })], submit: 'Add', path_params: ['mb'] },
    { kind: 'form', title: 'Remove a delegate', call: { method: 'delete', path: '/mail/mailboxes/{mb}/delegates' }, fields: [text('mb', 'Mailbox id', { required: true }), text('user_id', 'User id', { required: true })], submit: 'Remove', path_params: ['mb'], query: true },
    { kind: 'form', title: 'Set quota', call: { method: 'put', path: '/mail/mailboxes/{mb}/quota' }, fields: [text('mb', 'Mailbox id', { required: true }), { name: 'quota_mb', label: 'Quota (MB)', type: 'number', required: true }], submit: 'Save quota', path_params: ['mb'] },
    { kind: 'form', title: 'Organisation mail settings', call: P('put', '/mail/settings'), fields: [], submit: 'Save settings', note: 'Put the settings in the JSON box.' },
  ] },
  { id: 'mail-compliance', role: 'admin', title: 'Mail compliance', sub: 'A legal hold blocks erase and retention for held items; Velaris reports what it kept.', sections: [
    { kind: 'form', title: 'Legal hold on a mailbox', call: { method: 'put', path: '/mail/mailboxes/{mb}/legal-hold' }, fields: [text('mb', 'Mailbox id', { required: true }), { name: 'hold', label: 'Hold on', type: 'checkbox' }], submit: 'Apply', path_params: ['mb'] },
    { kind: 'form', title: 'Retention run (preview first)', call: P('post', '/mail/retention/run'), fields: [{ name: 'dry_run', label: 'Preview only', type: 'checkbox' }], submit: 'Run retention', note: 'Tick Preview only to see counts without removing anything.' },
    { kind: 'form', title: 'Erase a mailbox (DPDP)', call: { method: 'delete', path: '/mail/mailboxes/{mb}' }, fields: [text('mb', 'Mailbox id', { required: true })], submit: 'Erase mailbox', typed: 'ERASE', danger: true, warn: 'The mailbox data is removed, except items on legal hold.', path_params: ['mb'], raw: true },
    { kind: 'form', title: 'Process the outbox now', call: P('post', '/mail/outbox/process'), fields: [], submit: 'Process', note: 'Nothing schedules this automatically yet; run it from here or from a timer.' },
  ] },
  { id: 'mail-accounts', role: 'member', title: 'External mail accounts', sub: 'Connect an IMAP/SMTP account. The password is sent to Velaris once and never shown or logged.', sections: [
    { kind: 'form', title: 'Accounts of a mailbox', call: { method: 'get', path: '/mail/mailboxes/{mb}/accounts' }, fields: [text('mb', 'Mailbox id', { required: true })], submit: 'Show', path_params: ['mb'] },
    { kind: 'form', title: 'Add an account', call: { method: 'post', path: '/mail/mailboxes/{mb}/accounts' }, fields: [text('mb', 'Mailbox id', { required: true }), text('host', 'IMAP host', { required: true }), { name: 'port', label: 'Port', type: 'number' }, text('user', 'User', { required: true }), { name: 'secret', label: 'Password', type: 'password', required: true }], submit: 'Connect', path_params: ['mb'] },
    { kind: 'form', title: 'Remove an account (deletes its stored secret)', call: { method: 'delete', path: '/mail/mailboxes/{mb}/accounts/{aid}' }, fields: [text('mb', 'Mailbox id', { required: true }), text('aid', 'Account id', { required: true })], submit: 'Remove', danger: true, path_params: ['mb', 'aid'], raw: true },
    { kind: 'form', title: 'Sync now', call: { method: 'post', path: '/mail/mailboxes/{mb}/sync' }, fields: [text('mb', 'Mailbox id', { required: true })], submit: 'Sync', path_params: ['mb'], note: 'Shows counts, or a plain error such as authentication failed or host unreachable.' },
  ] },
  { id: 'atlassian', role: 'member', title: 'Jira and Confluence', sub: 'Searching and reading need no approval. Creating or moving an issue waits for approval. Page text is shown as plain text.', sections: [
    form('Search issues', A('JIRA', 'search_issues'), [text('query', 'Search (JQL or text)', { required: true })], 'Search'),
    form('Open an issue', A('JIRA', 'get_issue'), [text('issue_key', 'Issue key', { required: true })], 'Open'),
    form('Available transitions', A('JIRA', 'get_transitions'), [text('issue_key', 'Issue key', { required: true })], 'Show'),
    form('Move an issue', A('JIRA', 'transition_issue'), [text('issue_key', 'Issue key', { required: true }), text('transition', 'Transition', { required: true })], 'Request move'),
    form('Create an issue', A('JIRA', 'create_issue'), [text('project', 'Project key', { required: true }), text('summary', 'Summary', { required: true }), { name: 'description', label: 'Description', type: 'textarea' }], 'Request create'),
    load('Projects', A('JIRA', 'list_projects')),
    form('Search Confluence', A('CONFLUENCE', 'search'), [text('query', 'Search', { required: true })], 'Search'),
    form('Read a page', A('CONFLUENCE', 'get_page_markdown'), [text('page_id', 'Page id', { required: true })], 'Open'),
    load('Spaces', A('CONFLUENCE', 'list_spaces')),
    form('Ingest a space into the library', A('CONFLUENCE', 'ingest_space'), [text('space_key', 'Space key', { required: true })], 'Request ingest', { danger: true, warn: 'The whole space is copied into the document library after approval.' }),
  ] },
  { id: 'tickets', role: 'member', title: 'Tickets and SLA', sub: 'IT service tickets. Moving a ticket waits for approval.', sections: [
    load('Tickets', A('ITSM_ENGINE', 'list_tickets')),
    form('Ticket', A('ITSM_ENGINE', 'get_ticket'), [text('ticket_id', 'Ticket id', { required: true })], 'Open'),
    form('SLA status', A('ITSM_ENGINE', 'sla_status'), [text('ticket_id', 'Ticket id')], 'Show'),
    form('Move a ticket', A('ITSM_ENGINE', 'transition'), [text('ticket_id', 'Ticket id', { required: true }), text('to', 'New state', { required: true })], 'Request move'),
  ] },
  { id: 'finance', role: 'member', title: 'Finance view', sub: 'Runway, reserves and expense forecast. Rule-based estimates, not advice.', sections: [
    load('Cash flow', A('TREASURIX', 'project_cashflow')),
    load('Reserve ratio', A('TREASURIX', 'reserve_ratio')),
    load('Runway (months)', A('TREASURIX', 'runway_months')),
    load('Cost breakdown', A('FISCALIS', 'cost_breakdown')),
    load('Expense forecast', A('FISCALIS', 'forecast_expenses')),
  ] },
  { id: 'knowledge', role: 'member', title: 'Library, research and memory', sub: 'Answers show their sources. Research and web search can be slow and use quota. Remembering waits for approval.', sections: [
    form('Ask the library', A('DOCUMENT_LIBRARY', 'ask'), [text('question', 'Question', { required: true })], 'Ask'),
    form('Search the library', A('DOCUMENT_LIBRARY', 'search'), [text('query', 'Search', { required: true })], 'Search'),
    form('Research a topic (slow)', A('AUTONOMOUS_RESEARCH_ENGINE', 'research'), [text('topic', 'Topic', { required: true })], 'Research'),
    form('Web search', A('ADVANCED_SEARCH_ENGINE', 'web_search'), [text('query', 'Search', { required: true })], 'Search'),
    form('Read a web page', A('ADVANCED_SEARCH_ENGINE', 'read_page'), [text('url', 'Address', { required: true })], 'Read'),
    form('Ask the model council', A('MODEL_COUNCIL', 'deliberate'), [text('question', 'Question', { required: true })], 'Deliberate'),
    form('Recall from memory', A('LONGTERM_MEMORY', 'recall'), [text('query', 'What', { required: true })], 'Recall'),
    form('Remember', A('LONGTERM_MEMORY', 'remember'), [{ name: 'text', label: 'To remember', type: 'textarea', required: true }], 'Request remember'),
  ] },
];

export const screenById = (id) => SCREENS.find((s) => s.id === id);
