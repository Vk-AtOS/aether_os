import { test, expect } from '@playwright/test';
import { signIn, stubApi } from './helpers';

// KAN-18 (model providers), KAN-21 (approval detail), KAN-23 (edit before approve) against a stubbed API.

const PROVIDERS = { providers: [], kinds: ['openai_compatible'], presets: [] };
const USAGE = { days: [] };
// A stored provider as the API lists it: never the key, only has_key and the last four characters.
const GW = { id: 'gw', kind: 'openai_compatible', base_url: 'https://llm.example.com/v1', enabled: true, free_pool: false,
  has_key: true, key_last4: '6789', sensitivity_allowed: ['public'] };

// No input on the page holds `secret`, and it is nowhere in the markup.
const expectSecretGone = async (page, secret) => {
  expect(await page.content()).not.toContain(secret);
  expect(await page.locator('input, textarea').evaluateAll((els, v) => els.filter((e) => e.value.includes(v)).length, secret)).toBe(0);
};

test('an admin adds a model provider: the key is sent once and never shown again', async ({ page }) => {
  await signIn(page, 'owner');
  const KEY = 'sk-test-0123456789';
  let providers = [];
  const calls = await stubApi(page, {
    'GET /model-providers': () => ({ ...PROVIDERS, providers }), 'GET /model-providers/usage': USAGE,
    // What Velaris answers: the provider without its key, only that one exists and its last four characters.
    'POST /model-providers': (req) => { providers = [{ ...GW, key_last4: req.postDataJSON().api_key.slice(-4) }]; return { id: 'gw' }; },
  });
  await page.goto('settings');
  const form = page.getByRole('form', { name: 'Add provider' });
  await expect(form).toBeVisible();
  await form.getByLabel('Name').fill('gw');
  await form.getByLabel('Base URL').fill('https://llm.example.com/v1');
  await expect(form.getByLabel('API key')).toHaveAttribute('type', 'password');
  await form.getByLabel('API key').fill(KEY);
  await form.getByRole('button', { name: 'Add' }).click();
  await expect(page.getByText('••••6789')).toBeVisible();            // saved: only the last four are shown
  await expect(form.getByLabel('API key')).toHaveValue('');
  await expectSecretGone(page, KEY);
  const posts = calls.filter((c) => c.key === 'POST /model-providers');
  expect(posts).toHaveLength(1);
  expect(posts[0].body).toMatchObject({ id: 'gw', base_url: 'https://llm.example.com/v1', api_key: KEY });
  expect(calls.filter((c) => JSON.stringify(c.body || '').includes(KEY))).toHaveLength(1);
  await page.reload();                                               // and a fresh load has nothing to show either
  await expect(page.getByText('••••6789')).toBeVisible();
  await expectSecretGone(page, KEY);
});

test('a saved provider: test connection, rotate the key, disable, enable, delete', async ({ page }) => {
  await signIn(page, 'owner');
  let providers = [{ ...GW }];
  let test = { ok: true, models: 3, latency_s: 0.2 };
  const patch = (p) => { providers = providers.map((x) => ({ ...x, ...p })); return providers[0]; };
  const calls = await stubApi(page, {
    'GET /model-providers': () => ({ ...PROVIDERS, providers }), 'GET /model-providers/usage': USAGE,
    'POST /model-providers/gw/test': () => test,
    'POST /model-providers/gw/rotate': (req) => patch({ key_last4: req.postDataJSON().api_key.slice(-4) }),
    'PUT /model-providers/gw': (req) => patch(req.postDataJSON()),
    'DELETE /model-providers/gw': () => { providers = []; return { deleted: true }; },
  });
  const sent = (key) => calls.filter((c) => c.key === key).map((c) => c.body);
  await page.goto('settings');
  const row = page.getByRole('listitem').filter({ hasText: 'https://llm.example.com/v1' });
  await expect(row.getByText('••••6789')).toBeVisible();

  // Test connection: the result, and for a failure a fixed sentence, never the provider's own text.
  await row.getByRole('button', { name: 'Test connection' }).click();
  await expect(row.getByRole('status')).toHaveText('Working (3 models, 0.2s)');
  test = { ok: false, error: 'key_rejected', detail: 'upstream said: bad key sk-old-6789' };
  await row.getByRole('button', { name: 'Test connection' }).click();
  await expect(row.getByRole('status')).toHaveText('The provider rejected the key.');
  await expect(page.getByText('upstream said')).toHaveCount(0);

  // Rotate: nothing to send without a new key; the new key goes out once and is not shown afterwards.
  const NEW = 'sk-rotated-key-4321';
  await expect(row.getByRole('button', { name: 'Rotate' })).toBeDisabled();
  await expect(row.getByLabel('New key for gw')).toHaveAttribute('type', 'password');
  await row.getByLabel('New key for gw').fill(NEW);
  await row.getByRole('button', { name: 'Rotate' }).click();
  await expect(row.getByText('••••4321')).toBeVisible();
  await expect(row.getByLabel('New key for gw')).toHaveValue('');
  await expectSecretGone(page, NEW);
  expect(sent('POST /model-providers/gw/rotate')).toEqual([{ api_key: NEW }]);

  // Disable, then enable again: the row follows what the server stored.
  await row.getByRole('button', { name: 'Disable' }).click();
  await expect(row.getByText('disabled', { exact: true })).toBeVisible();
  await row.getByRole('button', { name: 'Enable' }).click();
  await expect(row.getByText('disabled', { exact: true })).toHaveCount(0);
  await expect(row.getByRole('button', { name: 'Disable' })).toBeVisible();
  expect(sent('PUT /model-providers/gw')).toEqual([{ enabled: false }, { enabled: true }]);

  // Delete asks first; cancelling deletes nothing.
  await row.getByRole('button', { name: 'Delete' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel' }).click();
  await expect(row).toBeVisible();
  expect(sent('DELETE /model-providers/gw')).toHaveLength(0);
  await row.getByRole('button', { name: 'Delete' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm' }).click();
  await expect(page.getByText('No providers added yet.')).toBeVisible();
  await expect(row).toHaveCount(0);
  expect(sent('DELETE /model-providers/gw')).toHaveLength(1);
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
