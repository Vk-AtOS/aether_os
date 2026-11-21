import { test, expect } from '@playwright/test';
import { signIn, stubApi } from './helpers';

// KAN-18: the platform provider keys (OpenAI-compatible endpoint, Bedrock...) and their health, against a stubbed API.

const STATUS = { providers: [
  { id: 'openrouter', label: 'OpenRouter / OpenAI-compatible endpoint', has_org_key: false, platform_key: false,
    endpoint_host: 'integrate.api.nvidia.com', uses_platform_credentials: false, health: { state: 'healthy', score: 1, breaker_open: false } },
  { id: 'bedrock', label: 'AWS Bedrock', has_org_key: false, platform_key: false, endpoint_host: '',
    uses_platform_credentials: true, health: { state: 'down', score: null, breaker_open: true } },
] };

test('an admin adds an endpoint key: it is sent once, cleared from the page, and health shows the breaker', async ({ page }) => {
  await signIn(page, 'owner');
  const KEY = 'nvapi-0123456789abcdef';
  const calls = await stubApi(page, {
    'GET /settings/provider-status': STATUS,
    'GET /model-providers': { providers: [], kinds: ['openai_compatible'], presets: [] }, 'GET /model-providers/usage': { days: [] },
    'GET /settings/api-keys': { anthropic: null, google: null, openrouter: null, org_keys: {} },
    'POST /settings/api-keys': { success: true },
    'POST /settings/test-provider': { success: true, message: 'Connected' },
  });
  await page.goto('settings');
  const panel = page.getByRole('region', { name: 'Provider health' });
  await expect(panel.getByText('endpoint integrate.api.nvidia.com')).toBeVisible();
  await expect(panel.getByText(/Circuit breaker open/)).toBeVisible();
  const input = page.getByPlaceholder('sk-or-…');
  await input.fill(KEY);
  await page.getByRole('button', { name: 'ADD', exact: true }).nth(2).click();
  await expect(page.getByText('✓ SAVED')).toBeVisible();
  await expect(input).toHaveValue('');
  expect(await page.content()).not.toContain(KEY);
  expect(calls.filter((c) => JSON.stringify(c.body || '').includes(KEY))).toHaveLength(1);
  await page.getByRole('button', { name: 'TEST', exact: true }).nth(2).click();
  await expect(page.getByText('✓ OK')).toBeVisible();
});

test('a member does not see provider health and the API is never asked', async ({ page }) => {
  await signIn(page, 'member');
  const calls = await stubApi(page, { 'GET /settings/provider-status': STATUS });
  await page.goto('settings');
  await expect(page.getByRole('region', { name: 'Provider health' })).toHaveCount(0);
  expect(calls.filter((c) => c.key === 'GET /settings/provider-status')).toHaveLength(0);
});
