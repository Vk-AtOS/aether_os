import { test, expect } from '@playwright/test';
import { ROUTES, signIn, stubApi } from './helpers';

// Every screen the app routes to, opened as an owner with an empty-but-valid API: none may crash into the
// error boundary or throw an uncaught exception. (Content correctness is covered by the component tests.)
for (const route of ROUTES) {
  test(`opens ${route}`, async ({ page }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await signIn(page, 'owner');
    await stubApi(page);
    await page.goto(route === '/' ? '' : route.slice(1));
    await expect(page.locator('body')).not.toContainText(/Something went wrong|Application error/i);
    await expect(page.locator('#root')).not.toBeEmpty();
    expect(errors).toEqual([]);
  });
}

test('a signed-out visitor is sent to the login page', async ({ page }) => {
  await stubApi(page);
  await page.goto('projects');
  await expect(page).toHaveURL(/\/login$/);
});

test('an unknown address shows the not-found page', async ({ page }) => {
  await signIn(page);
  await stubApi(page);
  await page.goto('definitely/not/a/page');
  await expect(page.getByText('Page Not Found')).toBeVisible();
});

test('a member cannot open admin screens (redirected home)', async ({ page }) => {
  await signIn(page, 'member');
  await stubApi(page);
  for (const path of ['admin/billing', 'settings/api-keys', 'operator']) {
    await page.goto(path);
    await expect(page).not.toHaveURL(new RegExp(`${path}$`));
  }
});
