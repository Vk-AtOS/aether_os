// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { renderAt, ok, fail } from './helpers';

const api = vi.hoisted(() => ({ listOrgApiKeys: vi.fn(), createOrgApiKey: vi.fn(), revokeOrgApiKey: vi.fn() }));
vi.mock('../api', () => ({ api, default: api }));
vi.mock('../components/confirmAction', () => ({ confirmAction: vi.fn(() => Promise.resolve(true)) }));

import ApiKeys from '../pages/ApiKeys';

beforeEach(() => { cleanup(); vi.clearAllMocks(); });

describe('ApiKeys page', () => {
  it('lists keys without any secret and revokes one after confirmation', async () => {
    api.listOrgApiKeys.mockReturnValue(ok([{ id: 'k1', name: 'ci', created_at: '2026-01-01', last_used_at: null }]));
    api.revokeOrgApiKey.mockReturnValue(ok({ status: 'revoked' }));
    renderAt(<ApiKeys />);
    expect(await screen.findByText('ci')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Revoke ci'));
    await waitFor(() => expect(api.revokeOrgApiKey).toHaveBeenCalledWith('k1'));
    await waitFor(() => expect(screen.queryByText('ci')).toBeNull());
  });

  it('shows the new secret once and dismisses it', async () => {
    api.listOrgApiKeys.mockReturnValue(ok([]));
    api.createOrgApiKey.mockReturnValue(ok({ id: 'k2', api_key: 'aesk_secret123', name: 'bot' }));
    renderAt(<ApiKeys />);
    await screen.findByText('No API keys yet.');
    fireEvent.change(screen.getByPlaceholderText('ci-pipeline'), { target: { value: 'bot' } });
    fireEvent.click(screen.getByText('Create key'));
    expect(await screen.findByText('aesk_secret123')).toBeTruthy();
    fireEvent.click(screen.getByText('I have saved it'));
    expect(screen.queryByText('aesk_secret123')).toBeNull();
  });

  it('shows the server refusal (403 for a non-admin)', async () => {
    api.listOrgApiKeys.mockReturnValue(fail(403, { error: 'role_insufficient', required_role: 'admin' }));
    renderAt(<ApiKeys />);
    expect((await screen.findByRole('alert')).textContent).toMatch(/admin role/);
  });
});
