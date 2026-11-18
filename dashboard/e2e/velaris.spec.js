import { test, expect } from '@playwright/test';
import { SCREENS } from '../src/components/velaris/screens.js';
import { signIn, stubApi } from './helpers';

// The Velaris screens (KAN-129..151) against a stubbed API: every screen opens, the role floor hides admin screens,
// a form posts the argument names Velaris takes, and the not-linked / waiting-for-approval answers are shown.

for (const s of SCREENS) {
  test(`opens /work/${s.id}`, async ({ page }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await signIn(page, 'owner');
    await stubApi(page);
    await page.goto(`work/${s.id}`);
    await expect(page.getByRole('heading', { name: s.title, level: 1 })).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/Something went wrong|Application error/i);
    expect(errors).toEqual([]);
  });
}

test('a member sees member screens and is told admin screens need the admin role', async ({ page }) => {
  await signIn(page, 'member');
  await stubApi(page);
  await page.goto('work/payroll');
  await expect(page.getByText(/needs the owner or admin role/i)).toBeVisible();
  await page.goto('work/my-leave');
  await expect(page.getByRole('button', { name: 'Show balance' })).toBeVisible();
});

test('a viewer may look but not act', async ({ page }) => {
  await signIn(page, 'viewer');
  await stubApi(page);
  await page.goto('work/my-leave');
  await expect(page.getByText(/may look at Velaris but not act/i)).toBeVisible();
});

test('my leave posts year (an argument Velaris takes) and shows the answer', async ({ page }) => {
  await signIn(page, 'member');
  const calls = await stubApi(page, { 'POST /hr/LEAVE_MANAGEMENT/get_balance': { result: { casual: 7 } } });
  await page.goto('work/my-leave');
  await page.getByLabel(/^Year/).first().fill('2026');
  await page.getByRole('button', { name: 'Show balance' }).click();
  await expect(page.getByText('casual')).toBeVisible();
  const call = calls.find((c) => c.key === 'POST /hr/LEAVE_MANAGEMENT/get_balance');
  expect(call.body).toEqual({ year: 2026 });          // no employee_id: the gateway fills the caller's linked record
});

test('a sign-in that is not linked to an employee record is told so', async ({ page }) => {
  await signIn(page, 'member');
  await stubApi(page, { 'POST /hr/LEAVE_MANAGEMENT/get_balance': { status: 409, body: { detail: 'Your sign-in is not linked to an employee record yet.' } } });
  await page.goto('work/my-leave');
  await page.getByLabel(/^Year/).first().fill('2026');
  await page.getByRole('button', { name: 'Show balance' }).click();
  await expect(page.getByText(/not linked to an employee record/i)).toBeVisible();
});

test('an act that waits for approval says so instead of showing a result', async ({ page }) => {
  await signIn(page, 'owner');
  await stubApi(page, { 'POST /hr/LEAVE_MANAGEMENT/approve': { status: 202, body: { run: { id: 'run1' } } } });
  await page.goto('work/leave-approvals');
  await page.getByLabel(/^Leave request id/).first().fill('12');
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.getByText(/approval/i).first()).toBeVisible();
});

test('erasure stays disabled until the word is typed', async ({ page }) => {
  await signIn(page, 'owner');
  await stubApi(page);
  await page.goto('work/privacy');
  const erase = page.getByRole('button', { name: 'Request erasure' });
  await expect(erase).toBeDisabled();
  await page.getByLabel('Type ERASE').first().fill('ERASE');
  await expect(erase).toBeEnabled();
});

test('a document is chosen with a file picker, not pasted as base64', async ({ page }) => {
  await signIn(page, 'member');
  await stubApi(page);
  await page.goto('work/my-onboarding');
  await expect(page.locator('input[type=file]')).toHaveCount(1);
  await expect(page.getByText(/base64/i)).toHaveCount(0);
});
