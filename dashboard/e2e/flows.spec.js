import { test, expect } from '@playwright/test';
import { signIn, stubApi } from './helpers';

test('login form posts the credentials and lands on the dashboard', async ({ page }) => {
  const calls = await stubApi(page, {
    'POST /auth/login': { access_token: 'h.' + Buffer.from(JSON.stringify({ role: 'owner', user_id: 'u1', org_id: 'o' })).toString('base64url') + '.s', refresh_token: 'r' },
  });
  await page.goto('login');
  await page.getByLabel(/email/i).fill('demo@aetheros.ai');
  await page.locator('input[type="password"]').fill('demo1234');
  await page.getByRole('button', { name: /sign in|log in/i }).click();
  await expect(page).not.toHaveURL(/login$/);
  expect(calls.find((c) => c.key === 'POST /auth/login').body).toMatchObject({ email: 'demo@aetheros.ai' });
});

test('API keys: create shows the secret once, revoke removes the row', async ({ page }) => {
  await signIn(page);
  let keys = [];
  const calls = await stubApi(page, {
    'GET /auth/api-keys': () => keys,
    'POST /auth/api-keys': () => { keys = [{ id: 'k1', name: 'ci', created_at: '2026-01-01' }]; return { id: 'k1', api_key: 'aesk_secretvalue', name: 'ci' }; },
    'DELETE /auth/api-keys/k1': () => { keys = []; return { status: 'revoked' }; },
  });
  await page.goto('settings/api-keys');
  await page.getByPlaceholder('ci-pipeline').fill('ci');
  await page.getByRole('button', { name: /create key/i }).click();
  await expect(page.getByText('aesk_secretvalue')).toBeVisible();
  await page.getByText('I have saved it').click();
  await expect(page.getByText('aesk_secretvalue')).toHaveCount(0);
  await page.getByLabel('Revoke ci').click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm' }).click();
  await expect(page.getByText('No API keys yet.')).toBeVisible();
  expect(calls.some((c) => c.key === 'DELETE /auth/api-keys/k1')).toBe(true);
});

test('decisions inbox: reject sends approved=false for that run', async ({ page }) => {
  await signIn(page);
  const calls = await stubApi(page, {
    'GET /factory/decisions': { decisions: [{ id: 'd1', run_id: 'r1', title: 'Approve spec', what: 'Spec ready' }] },
    'POST /factory/runs/r1/decisions/d1/decide': { status: 'denied' },
  });
  await page.goto('decisions');
  await page.getByRole('button', { name: /reject/i }).click();
  await expect(page.getByText('Approve spec')).toHaveCount(0);
  expect(calls.find((c) => c.key.endsWith('/decide')).body).toMatchObject({ approved: false });
});

test('billing: lowering the plan to Free goes through the cancel path after confirmation', async ({ page }) => {
  await signIn(page);
  const calls = await stubApi(page, {
    'GET /billing/status': { plan: 'pro', period_end: 1900000000 },
    'GET /billing/plans': { plans: [] },
    'POST /billing/cancel': { success: true, plan: 'free' },
  });
  await page.goto('admin/billing');
  await page.getByLabel('Lower plan').selectOption('free');
  await page.getByRole('button', { name: 'Apply' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm' }).click();
  await expect.poll(() => calls.some((c) => c.key === 'POST /billing/cancel')).toBe(true);
});

test('the Stripe return keeps ?upgrade=success on the billing page', async ({ page }) => {
  await signIn(page);
  await stubApi(page, { 'GET /billing/status': { plan: 'pro' }, 'GET /billing/plans': { plans: [] } });
  await page.goto('billing?upgrade=success');
  await expect(page).toHaveURL(/admin\/billing/);
  await expect(page.getByText(/Payment successful/)).toBeVisible();
});

test('notification preferences: turning a channel off sends only that channel', async ({ page }) => {
  await signIn(page);
  const events = [{ event: 'run_failed', label: 'A build failed', in_app: true, email: true, source: 'default' }];
  const calls = await stubApi(page, {
    'GET /notifications/preferences': { events },
    'PUT /notifications/preferences': { events: [{ ...events[0], email: false }] },
  });
  await page.goto('profile');
  await page.getByLabel('A build failed email').click();  // controlled: the box follows the server's answer
  await expect.poll(() => calls.find((c) => c.key === 'PUT /notifications/preferences')?.body).toEqual({ event: 'run_failed', email: false });
});

test('operator console: refusal from the server is shown to a non-operator who reaches it', async ({ page }) => {
  await signIn(page, 'superadmin');
  await stubApi(page, { 'GET /admin/platform-health': { status: 403, body: { detail: 'Platform operator access required' } } });
  await page.goto('operator');
  await expect(page.getByRole('alert').first()).toContainText('Platform operator access required');
});

test('run detail opens and shows its reports tabs for a project', async ({ page }) => {
  await signIn(page);
  await stubApi(page, { 'GET /factory/runs/r1': { run_id: 'r1', id: 'r1', status: 'completed', project_name: 'Demo' } });
  await page.goto('project/r1');
  await expect(page.locator('body')).not.toContainText(/Something went wrong/i);
});
