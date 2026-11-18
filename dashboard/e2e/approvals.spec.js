import { test, expect } from '@playwright/test';
import { signIn, stubApi, jwt } from './helpers';

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

// The server's side of edit-before-approve, as prime/approvals.py behaves: an edit makes a new revision with a new
// hash and records the editor; someone who edited a request can no longer decide it ("you cannot decide a request
// you edited", 403), anyone else who may decide sees the new revision. `view(uid)` is what that user is served.
const editableRequest = () => {
  const s = { amount: 5000, hash: 'h1', revision: 1, edited_by: [], state: 'pending' };
  const view = (uid) => {
    const editor = s.edited_by.includes(uid);
    const open = s.state === 'pending';
    return {
      ...DETAIL, state: s.state, request_hash: s.hash, action: { ...REQUEST.action, amount: s.amount },
      can_decide: open && !editor, can_approve: open && !editor,
      blocked_reason: open && editor ? 'you cannot decide a request you edited' : null,
      detail: { ...DETAIL.detail, revision: s.revision, edited_by: s.edited_by },
    };
  };
  const routes = (uid) => ({
    'GET /prime/inbox': () => ({ requests: [view(uid)], total: 1 }), 'GET /prime/inbox/count': { count: 1 },
    'GET /prime/requests/req1': () => view(uid),
    'POST /prime/requests/req1/edit': (req) => {
      const b = req.postDataJSON();
      if (b.request_hash !== s.hash) return { status: 409, body: { detail: 'The request changed; reload it.' } };
      Object.assign(s, { amount: Number(b.amount), hash: `h${s.revision + 1}`, revision: s.revision + 1, edited_by: [...s.edited_by, uid] });
      return view(uid);
    },
    'POST /prime/requests/req1/approve': (req) => {
      if (s.edited_by.includes(uid)) return { status: 403, body: { detail: 'you cannot decide a request you edited' } };
      if (req.postDataJSON().request_hash !== s.hash) return { status: 409, body: { detail: 'The request changed; reload it.' } };
      s.state = 'approved';
      return view(uid);
    },
  });
  return { s, routes };
};

const decideButtons = (page) => page.getByRole('button', { name: /^(Approve|Reject|Edit)$/ });

test('edit before approve: diff table, approvals reset to a new revision, a second user approves it', async ({ page, browser }) => {
  const { routes } = editableRequest();
  await signIn(page, 'owner');                                  // user u1
  const calls = await stubApi(page, routes('u1'));
  await page.goto('prime/inbox');
  await page.getByRole('button', { name: /payment\.release/ }).click();
  await expect(page.getByText('revision 1', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  const form = page.getByRole('form', { name: 'Edit request' });
  const save = form.getByRole('button', { name: 'Save edit' });

  // Nothing changed yet: no diff and nothing to save.
  await expect(form.getByRole('table', { name: 'Changes' })).toHaveCount(0);
  await expect(save).toBeDisabled();
  await form.getByLabel('Amount (INR)').fill('4000');
  const cells = form.getByRole('table', { name: 'Changes' }).getByRole('row').nth(1).getByRole('cell');
  await expect(cells).toHaveText(['amount', '5000', '4000']);  // field, before, after
  await expect(save).toBeDisabled();                             // the reason is required
  await form.getByLabel(/Why you are changing it/).fill('Agreed with finance');
  await save.click();

  // Saved: the reset message names the new revision, and the editor can no longer decide it.
  await expect(page.getByRole('status').filter({ hasText: 'Earlier approvals were reset' }))
    .toHaveText('Edited. Earlier approvals were reset: this is revision 2, and it needs a new decision from someone other than its editors.');
  await expect(page.getByText('revision 2', { exact: true })).toBeVisible();
  await expect(form).toHaveCount(0);
  await expect(page.getByText('you cannot decide a request you edited')).toBeVisible();
  await expect(decideButtons(page)).toHaveCount(0);
  expect(calls.find((c) => c.key === 'POST /prime/requests/req1/edit').body)
    .toEqual({ request_hash: 'h1', reason: 'Agreed with finance', amount: '4000' });

  // A second person (another browser session) sees the new revision and approves that one, by its new hash.
  const ctx = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const second = await ctx.newPage();
  await second.addInitScript((t) => { localStorage.setItem('aether_token', t); },
    jwt({ sub: 'second@example.com', user_id: 'u2', org_id: 'org1', role: 'owner' }));
  const calls2 = await stubApi(second, routes('u2'));
  await second.goto('prime/inbox');
  await second.getByRole('button', { name: /payment\.release/ }).click();
  await expect(second.getByText('revision 2', { exact: true })).toBeVisible();
  await expect(second.getByText('INR 4,000').first()).toBeVisible();
  await expect(second.getByRole('status').filter({ hasText: 'Earlier approvals were reset' })).toHaveCount(0);  // only the editor is told
  await second.getByRole('button', { name: 'Approve', exact: true }).click();
  await second.getByRole('alertdialog').getByRole('button').last().click();
  await expect(second.getByText('approved', { exact: true })).toBeVisible();
  await expect(decideButtons(second)).toHaveCount(0);
  expect(calls2.find((c) => c.key === 'POST /prime/requests/req1/approve').body.request_hash).toBe('h2');
  await ctx.close();
});

// KAN-21: the buttons follow can_decide / can_approve from the API, not the role in the browser's token.
test('approval detail: someone who may not decide sees the reason and no buttons', async ({ page }) => {
  await signIn(page, 'member');
  const blocked = { can_decide: false, can_approve: false, blocked_reason: 'cannot approve: your role holds no authority for payment.release' };
  const calls = await stubApi(page, {
    'GET /prime/inbox': { requests: [{ ...REQUEST, ...blocked }], total: 1 }, 'GET /prime/inbox/count': { count: 1 },
    'GET /prime/requests/req1': { ...DETAIL, ...blocked },
  });
  await page.goto('prime/inbox');
  await page.getByRole('button', { name: /payment\.release/ }).click();
  await expect(page.getByText('Releases the payment.')).toBeVisible();       // the detail itself is shown
  await expect(page.getByText(blocked.blocked_reason, { exact: true })).toBeVisible();
  await expect(decideButtons(page)).toHaveCount(0);
  await expect(page.getByLabel('Reason (required to reject)')).toHaveCount(0);
  expect(calls.filter((c) => !c.key.startsWith('GET '))).toHaveLength(0);
});

test('approval detail: someone who may only reject gets Reject, a disabled Approve and no Edit', async ({ page }) => {
  await signIn(page, 'admin');
  const limited = { can_decide: true, can_approve: false, blocked_reason: 'cannot approve: over your payment limit' };
  await stubApi(page, {
    'GET /prime/inbox': { requests: [{ ...REQUEST, ...limited }], total: 1 }, 'GET /prime/inbox/count': { count: 1 },
    'GET /prime/requests/req1': { ...DETAIL, ...limited, detail: { ...DETAIL.detail, editable_fields: {} } },
  });
  await page.goto('prime/inbox');
  await page.getByRole('button', { name: /payment\.release/ }).click();
  await expect(page.getByText('It can only be rejected: cannot approve: over your payment limit')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(0);
  await page.getByLabel('Reason (required to reject)').fill('Too much');
  await expect(page.getByRole('button', { name: 'Reject' })).toBeEnabled();
});

test.describe('at a phone width', () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test('approval detail: readable without sideways scrolling, and a decision can be made', async ({ page }) => {
    await signIn(page, 'owner');
    const long = { ...DETAIL, request_hash: 'h1', action: { ...REQUEST.action, params: { beneficiary_reference: 'INV-2026-11-000000000000000000000000000000000000000000000042' } } };
    const calls = await stubApi(page, {
      'GET /prime/inbox': { requests: [REQUEST], total: 1 }, 'GET /prime/inbox/count': { count: 1 },
      'GET /prime/requests/req1': long,
      'POST /prime/requests/req1/reject': { ...REQUEST, state: 'rejected' },
    });
    await page.goto('prime/inbox');
    await page.getByRole('button', { name: /payment\.release/ }).click();
    await expect(page.getByText('Releases the payment.')).toBeVisible();
    const inView = async (loc) => {
      await loc.scrollIntoViewIfNeeded();
      const box = await loc.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(375);
    };
    // Everything fits the width of the screen: the page does not scroll sideways, and neither a long value nor a button is cut off.
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    await inView(page.getByText(/INV-2026-11-0+42/));
    for (const name of ['Approve', 'Reject', 'Edit']) await inView(page.getByRole('button', { name, exact: true }));
    await inView(page.getByLabel('Reason (required to reject)'));

    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await inView(page.getByRole('form', { name: 'Edit request' }).getByLabel('Amount (INR)'));
    await page.getByRole('form', { name: 'Edit request' }).getByRole('button', { name: 'Cancel' }).click();

    await page.getByLabel('Reason (required to reject)').fill('Wrong supplier');
    await page.getByRole('button', { name: 'Reject' }).click();
    const dialog = page.getByRole('alertdialog');
    await inView(dialog.getByRole('button').last());
    await dialog.getByRole('button').last().click();
    await expect.poll(() => calls.find((c) => c.key === 'POST /prime/requests/req1/reject')?.body)
      .toEqual({ request_hash: 'h1', reason: 'Wrong supplier' });
  });
});
