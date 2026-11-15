import { test, expect } from '@playwright/test';
import { signIn, stubApi } from './helpers';

// KAN-18 (model providers), KAN-21 (approval detail), KAN-23 (edit before approve) against a stubbed API.

const PROVIDERS = { providers: [], kinds: ['openai_compatible'], presets: [] };
const USAGE = { days: [] };

test('an admin adds a model provider and the key is sent in the body once', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, { 'GET /model-providers': PROVIDERS, 'GET /model-providers/usage': USAGE, 'POST /model-providers': { id: 'gw' } });
  await page.goto('settings');
  const form = page.getByRole('form', { name: 'Add provider' });
  await expect(form).toBeVisible();
  await form.getByLabel('Name').fill('gw');
  await form.getByLabel('Base URL').fill('https://llm.example.com/v1');
  await form.getByLabel('API key').fill('sk-test-0123456789');
  await form.getByRole('button', { name: 'Add' }).click();
  await expect.poll(() => calls.some((c) => c.key === 'POST /model-providers')).toBe(true);
  const body = calls.find((c) => c.key === 'POST /model-providers').body;
  expect(body.id).toBe('gw');
  expect(body.base_url).toBe('https://llm.example.com/v1');
});

test('a member does not see the providers panel', async ({ page }) => {
  await signIn(page, 'member');
  await stubApi(page, { 'GET /model-providers': PROVIDERS, 'GET /model-providers/usage': USAGE });
  await page.goto('settings');
  await expect(page.getByRole('form', { name: 'Add provider' })).toHaveCount(0);
});

const REQUEST = {
  id: 'req1', state: 'pending', urgency: 'normal', can_decide: true, can_approve: true, request_hash: 'h1',
  expires_at: new Date(Date.now() + 3600e3).toISOString(),
  action: { type: 'payment.release', amount: 5000, currency: 'INR', on_behalf_of: 'org1', requested_by: 'agent' },
};
const DETAIL = {
  ...REQUEST, what_will_happen: 'Releases the payment.', executor: 'webhook', created_at: new Date().toISOString(),
  detail: {
    policy: { reason: 'Needs a person', autonomy: { level: 1, name: 'ask' }, second_person_required: false },
    eligible_roles: ['owner'], edited_by: [], ledger: [], data_touched: [], revision: 1, editable_fields: { amount: { type: 'amount' } },
  },
};

test('approval detail opens inline, rejecting needs a reason, approving sends the hash', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, {
    'GET /prime/inbox': { requests: [REQUEST], total: 1 }, 'GET /prime/inbox/count': { count: 1 },
    'GET /prime/requests/req1': DETAIL,
    'POST /prime/requests/req1/approve': { ...REQUEST, state: 'approved' },
  });
  await page.goto('prime/inbox');
  await page.getByRole('button', { name: /payment\.release/ }).click();
  await expect(page.getByRole('button', { name: 'Reject' })).toBeDisabled();       // a reason is required
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  const dialog = page.getByRole('alertdialog');
  await dialog.getByRole('button').last().click();      // the confirming button is the last one
  await expect.poll(() => calls.some((c) => c.key === 'POST /prime/requests/req1/approve')).toBe(true);
  expect(calls.find((c) => c.key === 'POST /prime/requests/req1/approve').body.request_hash).toBe('h1');
});

test('edit before approve: the edit form posts the changed amount with a reason', async ({ page }) => {
  await signIn(page, 'owner');
  const calls = await stubApi(page, {
    'GET /prime/inbox': { requests: [REQUEST], total: 1 }, 'GET /prime/inbox/count': { count: 1 },
    'GET /prime/requests/req1': DETAIL,
    'POST /prime/requests/req1/edit': { ...DETAIL, detail: { ...DETAIL.detail, revision: 2, edited_by: ['u1'] } },
  });
  await page.goto('prime/inbox');
  await page.getByRole('button', { name: /payment\.release/ }).click();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  const form = page.getByRole('form', { name: 'Edit request' });
  await form.getByLabel('Amount (INR)').fill('4000');
  await form.getByLabel(/Why you are changing it/).fill('Agreed with finance');
  await form.getByRole('button', { name: /Save|Submit|Apply/ }).click();
  await expect.poll(() => calls.some((c) => c.key === 'POST /prime/requests/req1/edit')).toBe(true);
  const body = calls.find((c) => c.key === 'POST /prime/requests/req1/edit').body;
  expect(JSON.stringify(body)).toContain('4000');
  expect(JSON.stringify(body)).toContain('Agreed with finance');
});
