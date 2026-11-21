// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, cleanup } from '@testing-library/react';
import { renderAt, ok, fail, settle } from './helpers';

const api = vi.hoisted(() => ({ getProviderStatus: vi.fn() }));
vi.mock('../api', () => ({ api, default: api }));

import ProviderHealthPanel from '../components/settings/ProviderHealthPanel';
import { healthText, keyStatusText } from '../components/settings/providerHelpers';

const ROWS = [
  { id: 'openrouter', label: 'OpenRouter / OpenAI-compatible endpoint', has_org_key: true, platform_key: false,
    endpoint_host: 'integrate.api.nvidia.com', uses_platform_credentials: false, health: { state: 'degraded', score: 0.33, breaker_open: false } },
  { id: 'bedrock', label: 'AWS Bedrock', has_org_key: false, platform_key: false, endpoint_host: '',
    uses_platform_credentials: true, health: { state: 'down', score: null, breaker_open: true } },
];

beforeEach(() => { cleanup(); vi.clearAllMocks(); });

describe('ProviderHealthPanel', () => {
  it('shows key presence, endpoint host and breaker / AHM state, and no key', async () => {
    api.getProviderStatus.mockReturnValue(ok({ providers: ROWS }));
    renderAt(<ProviderHealthPanel isAdmin />);
    await settle();
    expect(screen.getByText(/endpoint integrate.api.nvidia.com/)).toBeTruthy();
    expect(screen.getByText(/Your organisation's key is on file/)).toBeTruthy();
    expect(screen.getByText(/Degraded/)).toBeTruthy();
    expect(screen.getByText(/Circuit breaker open/)).toBeTruthy();
    expect(screen.getByText('score 0.33')).toBeTruthy();
  });

  it('renders nothing and calls nothing for a non-admin', async () => {
    renderAt(<ProviderHealthPanel isAdmin={false} />);
    await settle();
    expect(api.getProviderStatus).not.toHaveBeenCalled();
    expect(screen.queryByText('Provider health')).toBeNull();
  });

  it('shows the server refusal', async () => {
    api.getProviderStatus.mockReturnValue(fail(403, 'Only org owners/admins may view provider status.'));
    renderAt(<ProviderHealthPanel isAdmin />);
    await settle();
    expect(screen.getByRole('alert').textContent).toMatch(/owners\/admins/);
  });

  it('texts', () => {
    expect(healthText({ state: 'weird' })).toBe('No calls yet');
    expect(keyStatusText({ has_org_key: false, platform_key: true })).toMatch(/platform key is used/);
  });
});
