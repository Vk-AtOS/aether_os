// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, cleanup, waitFor } from '@testing-library/react';
import { renderAt } from './helpers';

import Legal from '../pages/Legal';

beforeEach(() => {
  cleanup();
  globalThis.fetch = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ title: 'Terms', content: 'Body', version: '1' }), text: () => Promise.resolve('Body') }));
});

describe('Legal', () => {
  it('an unknown ?doc falls back to the terms instead of loading forever', async () => {
    renderAt(<Legal />, '/legal?doc=bogus');
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(globalThis.fetch.mock.calls[0][0]).toBe('/api/legal/tos');
    expect(await screen.findAllByText('Terms of Service')).toBeTruthy();
  });
  it('a known ?doc is honoured', async () => {
    renderAt(<Legal />, '/legal?doc=privacy');
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(globalThis.fetch.mock.calls[0][0]).toBe('/api/legal/privacy');
  });
});
