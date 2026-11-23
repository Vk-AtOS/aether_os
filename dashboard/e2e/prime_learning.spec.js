import { test, expect } from '@playwright/test';
import { signIn, stubApi } from './helpers';

// KAN-229: "What Prime has learned" against a stubbed API shaped like gateway/routers/prime_learning_router.py.

const item = (over) => ({ kind: 'correction', id: 'c1', source: 'prime_corrections', org_id: 'org1', scope: 'payables · invoice.approve',
  text: 'edited: wrong amount', at: null, used: 4, helped: 1, settled: 4, help_rate: 0.25, retired: false, retired_by: null, ...over });
const week = (w, fp, cr) => ({ week: w, kinds: {}, builds: 2, first_pass: 1, corrections: 1, decided: 5, first_pass_rate: fp, correction_rate: cr });
const METRICS = { weeks: [week('2026-11-09', 0.5, 0.4), week('2026-11-16', 0.6, 0.3), week('2026-11-23', 0.8, 0.2)],
  totals: { correction: { settled: 4, helped: 1, help_rate: 0.25 }, golden: { settled: 0, helped: 0, help_rate: null }, fix: { settled: 2, helped: 1, help_rate: 0.5 } } };

const learned = (retired) => ({ retire_after: 3, kinds: {
  correction: [item({ retired, retired_by: retired ? 'u1' : null })],
  golden: [item({ kind: 'golden', id: 'g1', source: 'golden_builds', scope: 'crm', text: 'CRM (rated 4.5)', used: 2, helped: 2, help_rate: 1 })],
  fix: [] } });

test('an admin sees the lessons, the trend, and retires then restores one', async ({ page }) => {
  await signIn(page, 'admin');
  let retired = false;
  const calls = await stubApi(page, {
    'GET /prime/learning/items': () => learned(retired),
    'GET /prime/learning/metrics': METRICS,
    'POST /prime/learning/items/correction/c1/retire': () => { retired = true; return { kind: 'correction', id: 'c1', retired }; },
    'POST /prime/learning/items/correction/c1/restore': () => { retired = false; return { kind: 'correction', id: 'c1', retired }; },
  });
  await page.goto('prime/learned');
  await expect(page.getByRole('heading', { name: 'What Prime has learned' })).toBeVisible();
  const corr = page.getByRole('region', { name: 'Approver corrections' });
  await expect(corr.getByText('edited: wrong amount')).toBeVisible();
  await expect(corr.getByLabel('Used 4 times, helped 25%')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Golden builds' }).getByText('CRM (rated 4.5)')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Build fixes' }).getByText('Nothing learned yet.')).toBeVisible();
  await expect(page.getByTestId('latest-first_pass_rate')).toHaveText('80%');
  await expect(page.getByTestId('latest-correction_rate')).toHaveText('20%');
  await expect(page.getByRole('img', { name: /Build first-pass rate and correction rate per week, 3 weeks/ })).toBeVisible();

  await corr.getByRole('button', { name: 'Retire edited: wrong amount' }).click();
  await page.getByRole('button', { name: 'Confirm', exact: true }).click();          // the app's confirm dialog
  await expect(corr.getByText('Retired', { exact: true })).toBeVisible();
  await corr.getByRole('button', { name: 'Restore edited: wrong amount' }).click();
  await expect(corr.getByRole('button', { name: 'Retire edited: wrong amount' })).toBeVisible();
  expect(calls.filter((c) => c.key.startsWith('POST /prime/learning/')).map((c) => c.key)).toEqual([
    'POST /prime/learning/items/correction/c1/retire', 'POST /prime/learning/items/correction/c1/restore']);
});

test('a member sees the same organisation lessons but no retire or restore buttons', async ({ page }) => {
  await signIn(page, 'member');
  await stubApi(page, { 'GET /prime/learning/items': learned(true), 'GET /prime/learning/metrics': METRICS });
  await page.goto('prime/learned');
  await expect(page.getByRole('region', { name: 'Approver corrections' }).getByText('edited: wrong amount')).toBeVisible();
  await expect(page.getByRole('button', { name: /^(Retire|Restore) / })).toHaveCount(0);
});
