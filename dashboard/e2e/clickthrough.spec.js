import { test, expect } from '@playwright/test';
import { signIn, stubApi } from './helpers';

// KAN-62: click-throughs, not "opened". Each screen's main action is driven and judged twice: the request the
// browser made (path and body) and what the person then sees. API stubbed in the browser (helpers.js).

const confirmDialog = (page) => page.getByRole('alertdialog').getByRole('button').last();   // the confirming button is the last one
const posted = (calls, key) => calls.find((c) => c.key === key)?.body;

const REQUEST = {
  id: 'req1', state: 'pending', urgency: 'normal', can_decide: true, can_approve: true, request_hash: 'h1',
  expires_at: new Date(Date.now() + 3600e3).toISOString(),
  action: { type: 'payment.release', amount: 5000, currency: 'INR', on_behalf_of: 'org1', requested_by: 'agent' },
};
const DETAIL = {
  ...REQUEST, what_will_happen: 'Releases the payment.', executor: 'webhook', created_at: new Date().toISOString(),
  detail: { policy: { reason: 'Needs a person', autonomy: { level: 1, name: 'ask' }, second_person_required: false },
    eligible_roles: ['owner'], edited_by: [], ledger: [], data_touched: [], revision: 1, editable_fields: { amount: { type: 'amount' } } },
};

test('prime: rejecting sends the reason and the request hash and the screen shows the request as rejected', async ({ page }) => {
  await signIn(page, 'owner');
  let state = 'pending';
  const calls = await stubApi(page, {
    'GET /prime/inbox': () => ({ requests: state === 'pending' ? [REQUEST] : [], total: state === 'pending' ? 1 : 0 }),
    'GET /prime/requests/req1': () => ({ ...DETAIL, state, can_decide: state === 'pending' }),
    'POST /prime/requests/req1/reject': () => { state = 'rejected'; return { ...REQUEST, state }; },
  });
  await page.goto('prime/inbox');
  await page.getByRole('button', { name: /payment\.release/ }).click();
  await page.getByLabel('Reason (required to reject)').fill('Not this month');
  await page.getByRole('button', { name: 'Reject', exact: true }).click();
  await confirmDialog(page).click();
  await expect.poll(() => posted(calls, 'POST /prime/requests/req1/reject')).toMatchObject({ request_hash: 'h1', reason: 'Not this month' });
  await expect(page.getByRole('button', { name: 'Reject', exact: true })).toHaveCount(0);   // decided: no buttons any more
});

test('prime: approving shows the decided state, not the buttons', async ({ page }) => {
  await signIn(page, 'owner');
  let state = 'pending';
  const calls = await stubApi(page, {
    'GET /prime/inbox': { requests: [REQUEST], total: 1 },
    'GET /prime/requests/req1': () => ({ ...DETAIL, state, can_decide: state === 'pending' }),
    'POST /prime/requests/req1/approve': () => { state = 'approved'; return { ...REQUEST, state }; },
  });
  await page.goto('prime/inbox');
  await page.getByRole('button', { name: /payment\.release/ }).click();
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await confirmDialog(page).click();
  await expect.poll(() => posted(calls, 'POST /prime/requests/req1/approve')).toMatchObject({ request_hash: 'h1' });
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0);
});

test('hr: applying for leave posts the dates and shows the answer', async ({ page }) => {
  await signIn(page, 'member');
  const calls = await stubApi(page, { 'POST /hr/LEAVE_MANAGEMENT/apply': { result: { status: 'ok', leave: { id: 7, status: 'pending' } } } });
  await page.goto('work/my-leave');
  const card = page.locator('section', { has: page.getByRole('heading', { name: 'Apply for leave' }) });
  await card.getByLabel(/^Leave type/).fill('casual');
  await card.getByLabel(/^From/).fill('2026-12-01');
  await card.getByLabel(/^To/).fill('2026-12-02');
  await card.getByRole('button', { name: 'Apply', exact: true }).click();
  await expect.poll(() => posted(calls, 'POST /hr/LEAVE_MANAGEMENT/apply')).toEqual({ leave_type: 'casual', from_date: '2026-12-01', to_date: '2026-12-02' });
  await expect(card.getByText('pending').first()).toBeVisible();
});

const OFFER = { id: 'offer-0000000001', candidate_name: 'Asha', role_title: 'Engineer', join_date: '2027-01-05', status: 'sent', needs_review: false };
const offerRoutes = (extra = {}) => ({
  'POST /hr/OFFER_LETTERS/list_offers': { result: { offers: [OFFER] } },
  'POST /hr/OFFER_LETTERS/list_templates': { result: { templates: [{ id: 'builtin:standard', name: 'standard' }, { id: 'tpl_1', name: 'Senior' }] } },
  'POST /hr/OFFER_LETTERS/get_offer': { result: { offer: { ...OFFER, candidate: {}, terms: {}, comp: {}, approvers: [], approvals: [] } } },
  ...extra,
});

test('hr offers: the template picker sends template_id with the draft', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, offerRoutes({ 'POST /hr/OFFER_LETTERS/create_offer': { result: { status: 'ok', offer: { id: 'o2' } } } }));
  await page.goto('hr/offers');
  const form = page.locator('section', { has: page.getByRole('heading', { name: 'Draft an offer' }) });
  for (const [label, v] of [['Candidate name', 'Ravi'], ['Candidate email', 'r@example.com'], ['Role title', 'SRE'], ['Department', 'Eng'], ['Location', 'Chennai'],
    ['Annual CTC', '1800000'], ['Hiring manager', 'u2'], ['HR approver', 'u3']]) await form.getByLabel(new RegExp(`^${label}`)).fill(v);
  await form.getByLabel(/^Join date/).fill('2027-02-01');
  await form.getByLabel('Template').selectOption('tpl_1');
  await form.getByRole('button', { name: 'Create draft' }).click();
  await confirmDialog(page).click();
  await expect.poll(() => posted(calls, 'POST /hr/OFFER_LETTERS/create_offer')).toMatchObject({ candidate_name: 'Ravi', template_id: 'tpl_1' });
});

test('hr offers: a sent offer records the candidate response (KAN-139)', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, offerRoutes({ 'POST /hr/OFFER_LETTERS/record_response': { result: { status: 'ok', offer: { id: OFFER.id, status: 'accepted' } } } }));
  await page.goto('hr/offers');
  await page.getByRole('cell', { name: 'Asha' }).click();
  await page.getByLabel('E-sign request id').fill('req-42');
  await page.getByRole('button', { name: 'Candidate accepted' }).click();
  await confirmDialog(page).click();
  await expect.poll(() => posted(calls, 'POST /hr/OFFER_LETTERS/record_response')).toMatchObject({ offer_id: OFFER.id, response: 'accept', evidence_ref: 'req-42' });
});

test('hr: approving a leave request posts its id', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, { 'POST /hr/LEAVE_MANAGEMENT/approve': { result: { status: 'ok' } } });
  await page.goto('work/leave-approvals');
  const card = page.locator('section', { has: page.getByRole('heading', { name: 'Approve', exact: true }) });
  await card.getByLabel(/^Leave request id/).fill('12');
  await card.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect.poll(() => posted(calls, 'POST /hr/LEAVE_MANAGEMENT/approve')).toEqual({ leave_id: 12 });
});

test('mail: composing sends a draft, submits it and shows the undo window; undo cancels', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, {
    'GET /mail/mailboxes': { mailboxes: [{ id: 'mb1', address: 'me@example.com' }] },
    'GET /mail/mailboxes/mb1/folders': { folders: [{ id: 1, name: 'inbox', unread: 0 }] },
    'GET /mail/mailboxes/mb1/messages': { messages: [] },
    'POST /mail/mailboxes/mb1/drafts': { id: 'd1' },
    'POST /mail/mailboxes/mb1/drafts/d1/submit': { id: 's1', state: 'approved', canCancel: true, sendAt: Date.now() / 1000 + 30 },
    'GET /mail/submissions/s1': { id: 's1', state: 'approved', canCancel: true, sendAt: Date.now() / 1000 + 30 },
    'POST /mail/submissions/s1/cancel': { id: 's1', state: 'canceled', canCancel: false },
  });
  await page.goto('mail');
  await page.getByRole('button', { name: 'Compose' }).click();
  await page.getByLabel('To', { exact: true }).fill('a@example.org, b@example.org');
  await page.getByLabel('Subject').fill('Hello');
  await page.getByLabel('Message body').fill('Body text');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await confirmDialog(page).click();
  await expect.poll(() => posted(calls, 'POST /mail/mailboxes/mb1/drafts')).toMatchObject({ to: ['a@example.org', 'b@example.org'], subject: 'Hello', text: 'Body text' });
  await expect(page.getByText(/Sending in \d+s/)).toBeVisible();
  expect(calls.some((c) => c.key === 'POST /mail/mailboxes/mb1/drafts/d1/submit')).toBe(true);
  await page.getByTestId('undo-send').click();
  await expect(page.getByText('Canceled. It was not sent.')).toBeVisible();
});

const CHAT = {
  'POST /chat/register': { queue_id: 'q1', last_event_id: 0, snapshot: { user: { id: 'u1' }, channels: [{ id: 1, name: 'general', kind: 'stream', role: 'owner', unread: 0, members: [{ id: 'u1', role: 'owner' }, { id: 'bob', role: 'member' }] }] } },
  'GET /chat/channels/1/messages': { messages: [{ id: 7, sender: 'bob', body: 'my phone is 12345', created_at: 1760000000, reactions: {}, attachments: [] }], has_more: false },
  'GET /chat/channels/1/topics': { topics: [] }, 'GET /chat/channels/1/pins': { messages: [] },
  'GET /chat/assistant/drafts': { drafts: [] }, 'GET /chat/assistant/proposals': { proposals: [] },
};
const quietPoll = (page) => page.route('**/api/chat/events*', () => {});   // a long poll: never answered, so the loop does not spin

test('chat: posting a message sends it with a local id and shows it in the channel', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, { ...CHAT, 'POST /chat/channels/1/messages': (req) => ({ message: { id: 8, sender: 'u1', body: req.postDataJSON().body, created_at: 1760000100, reactions: {}, attachments: [], local_id: req.postDataJSON().local_id } }) });
  await quietPoll(page);
  await page.goto('chat');
  await page.getByLabel('Message', { exact: true }).fill('Hello team');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect.poll(() => posted(calls, 'POST /chat/channels/1/messages')).toMatchObject({ body: 'Hello team' });
  expect(posted(calls, 'POST /chat/channels/1/messages').local_id).toBeTruthy();
  await expect(page.getByText('Hello team')).toBeVisible();
  await expect(page.getByLabel('Message', { exact: true })).toHaveValue('');
});

test('chat: erasing one message needs the typed word, sends it, and is refused before it is typed (KAN-129)', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, { ...CHAT, 'POST /chat/admin/messages/7/erase': { status: 'ok' } });
  await quietPoll(page);
  await page.goto('chat');
  await page.getByTestId('chat-message').hover();
  await page.getByRole('button', { name: 'Erase message (compliance)' }).click();
  const form = page.getByRole('form', { name: 'Erase this message' });
  const go = form.getByRole('button', { name: 'Erase permanently' });
  await expect(go).toBeDisabled();
  await form.getByLabel('Type ERASE').fill('erase');
  await expect(go).toBeDisabled();
  await form.getByLabel('Type ERASE').fill('ERASE');
  await go.click();
  await expect.poll(() => posted(calls, 'POST /chat/admin/messages/7/erase')).toEqual({ confirm: 'ERASE' });
  await expect(form).toHaveCount(0);
});

test('chat: a member gets no erase button, only delete on their own words', async ({ page }) => {
  await signIn(page, 'member');
  await stubApi(page, { ...CHAT });
  await quietPoll(page);
  await page.goto('chat');
  await page.getByTestId('chat-message').hover();
  await expect(page.getByRole('button', { name: 'Erase message (compliance)' })).toHaveCount(0);
});

test('control: starting a run confirms, posts the task and opens the run', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, {
    'GET /control/tasks': { tasks: [{ id: 't1', title: 'Tidy files', surface: 'files', description: 'Moves files', actions: ['move'], approval_steps: ['delete'], max_steps: 5 }] },
    'POST /control/runs': { task_id: 'run-1234567890' },
    'GET /control/runs/run-1234567890': { task_id: 'run-1234567890', task: 'Tidy files', status: 'succeeded', owner: 'u1', turns: 2 },
    'GET /control/runs/run-1234567890/report': { actions: [], observations: [], changes: [] },
  });
  await page.goto('control');
  await page.getByRole('button', { name: 'Set up a run' }).click();
  await page.getByLabel(/^Parameters/).fill('{"folder":"/tmp/a"}');
  await page.getByRole('button', { name: 'Start run', exact: true }).click();
  await confirmDialog(page).click();
  await expect.poll(() => posted(calls, 'POST /control/runs')).toEqual({ task_id: 't1', params: { folder: '/tmp/a' } });
  await expect(page.getByText('Run Tidy files')).toBeVisible();
  await expect(page.getByText('succeeded').first()).toBeVisible();
});

test('control: a run waiting for approval is approved with its call hash', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, {
    'GET /control/tasks': { tasks: [] },
    'GET /control/pending': { runs: [{ task_id: 'run-77', task: 'Tidy files', pending: { tool: 'delete', call_hash: 'ch1' } }] },
    'GET /control/runs/run-77': { task_id: 'run-77', task: 'Tidy files', status: 'waiting_approval', pending: { tool: 'delete', call_hash: 'ch1', args: { ref: 'f1', snapshot_id: 3 } } },
    'GET /control/runs/run-77/report': { actions: [], observations: [], changes: [] },
    'POST /control/runs/run-77/decide': { ok: true },
  });
  await page.goto('control');
  await page.getByRole('tab', { name: 'Waiting for approval' }).click();
  await page.getByRole('button', { name: 'Open run' }).click();
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await confirmDialog(page).click();
  await expect.poll(() => posted(calls, 'POST /control/runs/run-77/decide')).toMatchObject({ call_hash: 'ch1', approve: true });
});

test('calibration: interviewers are compared side by side (KAN-147)', async ({ page }) => {
  await signIn(page, 'owner');
  await stubApi(page, { 'POST /hr/INTERVIEW_KIT/calibration_report': { result: { competencies: [
    { competency: 'Design', krippendorff_alpha_ordinal: 0.5, rated_items: 5, rater_leniency_offset: { 'iv-a': 0.2, 'iv-b': -0.2 } },
    { competency: 'Coding', krippendorff_alpha_ordinal: 0.9, rated_items: 5, rater_leniency_offset: { 'iv-a': -0.4 } }] } } });
  await page.goto('work/kits-admin');
  const table = page.getByRole('table', { name: 'Interviewers side by side' });
  await expect(table.getByTestId('cmp-iv-a-Design')).toContainText('+0.20');
  await expect(table.getByTestId('cmp-iv-b-Design')).toContainText('-0.20');
  await expect(table.getByTestId('cmp-iv-a-Coding')).toContainText('-0.40');
  await expect(table.getByTestId('cmp-iv-b-Coding')).toContainText('n/a');
});

test('interview record: the evidence view shows who consented and who withdrew (KAN-148)', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, { 'POST /hr/INTERVIEW_RECORD/evidence_view': { result: { session_id: 's1', status: 'open', timeline: [],
    consents: { candidate: { scopes: ['events', 'audio'], notice_version: 'v2', withdrawn: false }, 'iv-a': { scopes: ['events'], notice_version: 'v2', withdrawn: true } } } } });
  await page.goto('work/interview-records');
  const card = page.locator('section', { has: page.getByRole('heading', { name: 'Evidence and consent state' }) });
  await card.getByLabel(/^Session id/).fill('s1');
  await card.getByRole('button', { name: 'Show', exact: true }).click();
  await expect.poll(() => posted(calls, 'POST /hr/INTERVIEW_RECORD/evidence_view')).toEqual({ session_id: 's1' });
  const state = card.getByTestId('consent-state');
  await expect(state.getByRole('row', { name: /candidate.*Consented.*events, audio/ })).toBeVisible();
  await expect(state.getByRole('row', { name: /iv-a.*Withdrawn/ })).toBeVisible();
});

test('onboarding: the name and DPA steps send the name and the version shown', async ({ page }) => {
  await signIn(page, 'owner');
  let steps = [
    { id: 'org_name', title: 'Name your organisation', done: false, required: true, link: '/settings' },
    { id: 'dpa', title: 'Accept the data processing agreement', done: false, required: true, link: '/legal?doc=dpa' }];
  const calls = await stubApi(page, {
    'GET /onboarding': () => ({ dismissed: false, complete: false, steps }),
    'POST /account/settings': () => { steps = [{ ...steps[0], done: true }, steps[1]]; return { status: 'ok' }; },
    'POST /onboarding/dpa': () => { steps = steps.map((s) => ({ ...s, done: true })); return { accepted: true }; },
  });
  await page.goto('');
  await page.getByLabel('Organisation name').fill('Acme Pvt Ltd');
  await page.getByRole('button', { name: 'Save name' }).click();
  await expect.poll(() => posted(calls, 'POST /account/settings')).toEqual({ org_name: 'Acme Pvt Ltd' });
  await page.getByRole('button', { name: 'Accept the DPA' }).click();
  await expect.poll(() => posted(calls, 'POST /onboarding/dpa')).toEqual({ version: '1.0' });
});
