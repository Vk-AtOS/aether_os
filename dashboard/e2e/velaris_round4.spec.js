import { test, expect } from '@playwright/test';
import { signIn, stubApi } from './helpers';

// Round 4 dashboard remainders (KAN-121, 140..151, 165) against a stubbed API.

test('a Jira issue is shown as a structured view', async ({ page }) => {
  await signIn(page, 'owner');
  await stubApi(page, { 'POST /velaris/agents/JIRA/get_issue': { result: { key: 'KAN-1', fields: { summary: 'Fix login', status: { name: 'In Progress' }, assignee: { displayName: 'Asha' }, description: 'Plain <b>text</b>' } } } });
  await page.goto('work/jira');
  await page.getByLabel(/^Issue key/).first().fill('KAN-1');
  await page.getByRole('button', { name: 'Open', exact: true }).click();
  await expect(page.getByText('KAN-1 Fix login')).toBeVisible();
  await expect(page.getByText('In Progress').first()).toBeVisible();
  await expect(page.getByText('Asha').first()).toBeVisible();
  await expect(page.locator('pre', { hasText: 'Plain <b>text</b>' })).toBeVisible();   // text, not HTML
});

test('library sources are links, and a javascript: address is not', async ({ page }) => {
  await signIn(page, 'owner');
  await stubApi(page, { 'POST /velaris/agents/DOCUMENT_LIBRARY/ask': { result: { answer: 'Yes', sources: [{ title: 'Policy', url: 'https://docs.example.com/p' }, { title: 'Bad', url: 'javascript:alert(1)' }] } } });
  await page.goto('work/library');
  await page.getByLabel(/^Question/).first().fill('x');
  await page.getByRole('button', { name: 'Ask', exact: true }).click();
  const link = page.getByRole('link', { name: 'Policy' });
  await expect(link).toHaveAttribute('href', 'https://docs.example.com/p');
  await expect(page.getByRole('link', { name: 'Bad' })).toHaveCount(0);
  await expect(page.getByText('Bad')).toBeVisible();
});

test('the former three knowledge screens are separate sidebar entries', async ({ page }) => {
  await signIn(page, 'owner');
  await stubApi(page);
  await page.goto('work/library');
  for (const n of ['Jira', 'Confluence', 'Document library', 'Research and web search', 'Model council', 'Long-term memory']) {
    await expect(page.getByRole('link', { name: n, exact: true })).toBeVisible();
  }
});

test('calibration is drawn as bars per competency', async ({ page }) => {
  await signIn(page, 'owner');
  await stubApi(page, { 'POST /hr/INTERVIEW_KIT/calibration_report': { result: { competencies: [{ competency: 'Communication', krippendorff_alpha_ordinal: 0.8, rated_items: 5 }, { competency: 'Design', krippendorff_alpha_ordinal: 0.2, rated_items: 4 }] } } });
  await page.goto('work/kits-admin');
  await expect(page.getByRole('img', { name: 'Chart' })).toBeVisible();
  await expect(page.getByText('0.80').first()).toBeVisible();
  await expect(page.getByText('0.20').first()).toBeVisible();
});

test('follow-up drafts are listed with the no-show form', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, { 'POST /hr/INTERVIEW_SCHEDULER/list_drafts': { result: { drafts: [{ id: 'd1', kind: 'no_show_followup', status: 'draft' }] } } });
  await page.goto('work/hiring-admin');
  await expect(page.getByRole('cell', { name: 'no_show_followup' })).toBeVisible();
  expect(calls.find((c) => c.key === 'POST /hr/INTERVIEW_SCHEDULER/list_drafts').body).toEqual({ status: 'draft' });
});

test('policies: the overdue button asks Velaris only when pressed', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, { 'POST /hr/POLICY_ACKS/reminders_due': { result: { due: [{ employee: 'E1', policy_key: 'coc' }] } } });
  await page.goto('hr/policies');
  expect(calls.some((c) => c.key === 'POST /hr/POLICY_ACKS/reminders_due')).toBe(false);
  await page.getByRole('button', { name: 'Show overdue acknowledgements' }).click();
  await expect(page.getByText('coc')).toBeVisible();
});

test('e-sign: the document hash is shown next to the verify verdict', async ({ page }) => {
  await signIn(page, 'owner');
  await stubApi(page, {
    'POST /hr/ESIGN/list_requests': { result: { requests: [{ id: 'req-0000000001', title: 'NDA', status: 'sealed', signers: [], expires_at: '' }] } },
    'POST /hr/ESIGN/get_request': { result: { request: { id: 'req-0000000001', status: 'sealed', document_sha256: 'abc123def456' } } },
    'POST /hr/ESIGN/verify': { result: { valid: true, checks: [] } },
  });
  await page.goto('hr/esign');
  await page.getByText('NDA').click();
  await page.getByRole('button', { name: 'Verify integrity' }).click();
  await expect(page.getByTestId('doc-hash')).toHaveText('abc123def456');
  await expect(page.getByText('Every check passed')).toBeVisible();
});

test('onboarding shows the current step as a wizard card', async ({ page }) => {
  await signIn(page, 'owner');
  await stubApi(page, { 'GET /onboarding': { dismissed: false, complete: false, steps: [
    { id: 'llm_key', title: 'Add an LLM API key', done: true, required: true, link: '/settings' },
    { id: 'first_run', title: 'Run your first pipeline', done: false, required: true, link: '/new' }] } });
  await page.goto('');
  const card = page.getByTestId('wizard-current');
  await expect(card).toContainText('Step 2 of 2');
  await card.getByRole('button', { name: 'Start this step' }).click();
  await expect(page).toHaveURL(/\/new$/);
});
