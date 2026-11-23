import { test, expect } from '@playwright/test';
import { signIn, stubApi } from './helpers';

// KAN-228 "Prime and your data" against a stubbed API that behaves like prime/consent.py and prime/learned.py:
// everything off by default, a source only counts with the overall switch on, off deletes what that source learned.

const SOURCES = ['git', 'jira', 'calendar', 'attendance'];
const fakeServer = () => {
  const on = { all: false, git: false, jira: false, calendar: false, attendance: false };
  const since = {};
  let items = [];
  const state = () => ({
    notice: 'Prime can learn how you work. Shown to you alone, never used in performance reviews.',
    notice_version: '2026-11-22', retention_days: 365,
    switches: ['all', ...SOURCES].map((source) => ({
      source, enabled: on[source], enabled_at: on[source] ? since[source] : null, changed_at: null,
      notice_version: '2026-11-22', purpose: `What ${source} is used for.` })),
    counts: Object.fromEntries(SOURCES.map((s) => [s, items.filter((i) => i.source === s).length])),
    newest: items.slice(0, 10),
  });
  const learn = (source, summary) => {
    if (on.all && on[source]) items = [{ id: `i${items.length}`, source, kind: 'commit', summary, learned_at: '2026-11-23T10:00:00' }, ...items];
  };
  const routes = {
    'GET /prime/data/me': () => state(),
    'PUT /prime/data/me/consent': (req) => {
      const { source, enabled, notice_version } = req.postDataJSON();
      if (notice_version !== '2026-11-22') return { status: 409, body: { detail: 'the notice has changed' } };
      const targets = source === 'all' && !enabled ? ['all', ...SOURCES] : [source];
      targets.forEach((s) => { on[s] = enabled; since[s] = '2026-11-23T09:00:00'; });
      const before = items.length;
      if (!enabled) items = source === 'all' ? [] : items.filter((i) => i.source !== source);
      return { ...state(), erased: before - items.length };
    },
    'GET /prime/data/me/export': () => ({ user_id: 'u1', org_id: 'org1', consent: state(), learned: items }),
    'DELETE /prime/data/me/learned': (req) => {
      const source = new URL(req.url()).searchParams.get('source');
      const before = items.length;
      items = source ? items.filter((i) => i.source !== source) : [];
      return { erased: before - items.length, source: source || 'all' };
    },
  };
  return { routes, learn };
};

test('a person switches learning on per source, sees what was learned, exports it, and turning off deletes it', async ({ page }) => {
  await signIn(page, 'member');
  const server = fakeServer();
  const calls = await stubApi(page, server.routes);
  await page.goto('prime/data');

  const panel = page.getByRole('region', { name: 'Prime and your data' });
  await expect(panel.getByTestId('notice')).toContainText('never used in performance reviews');
  const sw = (name) => panel.getByRole('switch', { name });
  // Default: every switch off, the sources cannot be switched on before the overall switch.
  for (const name of ['Let Prime learn from my work', 'Git', 'Jira', 'Calendar', 'Attendance (Velaris)']) {
    await expect(sw(name)).toHaveAttribute('aria-checked', 'false');
  }
  await expect(sw('Git')).toBeDisabled();
  await expect(panel.getByText('Nothing learned yet.')).toBeVisible();

  await sw('Let Prime learn from my work').click();
  await expect(sw('Let Prime learn from my work')).toHaveAttribute('aria-checked', 'true');
  await sw('Git').click();
  await expect(sw('Git')).toHaveAttribute('aria-checked', 'true');
  await expect(sw('Jira')).toHaveAttribute('aria-checked', 'false');            // each source separately
  await expect(panel.getByText(/On since/).first()).toBeVisible();
  const puts = calls.filter((c) => c.key === 'PUT /prime/data/me/consent').map((c) => c.body);
  expect(puts).toEqual([{ source: 'all', enabled: true, notice_version: '2026-11-22' },
    { source: 'git', enabled: true, notice_version: '2026-11-22' }]);

  // A collector learns two things; jira is off, so nothing from it.
  server.learn('git', 'Merged PR #12 in aether');
  server.learn('git', 'Pushed 3 commits to dashboard');
  server.learn('jira', 'KAN-1 moved to done');
  await page.reload();
  await expect(panel.getByRole('heading', { name: 'What Prime has learned (2)' })).toBeVisible();
  await expect(panel.getByRole('list', { name: 'Newest learned items' }).getByRole('listitem')).toHaveCount(2);
  await expect(panel.getByText('Merged PR #12 in aether')).toBeVisible();

  const download = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'Export as JSON' }).click();
  expect((await download).suggestedFilename()).toMatch(/^prime-my-data-.*\.json$/);
  await expect(panel.getByRole('status')).toHaveText('Exported 2 learned items.');

  // Turning git off asks first; cancelling changes nothing; confirming deletes what git learned.
  await sw('Git').click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel' }).click();
  await expect(sw('Git')).toHaveAttribute('aria-checked', 'true');
  await sw('Git').click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm' }).click();
  await expect(panel.getByRole('status')).toHaveText('Git is off. 2 learned items deleted.');
  await expect(sw('Git')).toHaveAttribute('aria-checked', 'false');
  await expect(panel.getByText('Nothing learned yet.')).toBeVisible();
});

test('erase per source and erase everything keep the switches', async ({ page }) => {
  await signIn(page, 'member');
  const server = fakeServer();
  const calls = await stubApi(page, server.routes);
  await page.goto('prime/data');
  const panel = page.getByRole('region', { name: 'Prime and your data' });
  for (const name of ['Let Prime learn from my work', 'Git', 'Calendar']) {
    await panel.getByRole('switch', { name }).click();
    await expect(panel.getByRole('switch', { name })).toHaveAttribute('aria-checked', 'true');
  }
  server.learn('git', 'commit a');
  server.learn('calendar', 'standup 10:00');
  await page.reload();
  await panel.getByRole('button', { name: 'Erase Git data' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm' }).click();
  await expect(panel.getByRole('status')).toHaveText('1 learned items deleted.');
  await expect(panel.getByRole('heading', { name: 'What Prime has learned (1)' })).toBeVisible();
  await panel.getByRole('button', { name: 'Erase everything' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm' }).click();
  await expect(panel.getByText('Nothing learned yet.')).toBeVisible();
  await expect(panel.getByRole('switch', { name: 'Git' })).toHaveAttribute('aria-checked', 'true');
  expect(calls.filter((c) => c.key === 'DELETE /prime/data/me/learned')).toHaveLength(2);
});
