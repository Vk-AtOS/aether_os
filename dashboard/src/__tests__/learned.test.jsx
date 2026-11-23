// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, cleanup, fireEvent, within } from '@testing-library/react';
import { renderAt, ok, settle } from './helpers';

const api = vi.hoisted(() => ({ client: { get: vi.fn(), post: vi.fn() }, getToken: vi.fn() }));
vi.mock('../api', () => ({ api, default: api }));
vi.mock('../components/confirmAction', () => ({ confirmAction: vi.fn(() => Promise.resolve(true)) }));

import Learned from '../components/prime/Learned';

const jwt = (role) => `h.${btoa(JSON.stringify({ sub: 'u', role }))}.s`;
const item = (over) => ({ kind: 'correction', id: 'c1', source: 'prime_corrections', org_id: 'o', scope: 'payables · invoice.approve',
  text: 'edited: wrong amount', at: null, used: 4, helped: 1, settled: 4, help_rate: 0.25, retired: false, ...over });
const ITEMS = { retire_after: 3, kinds: { correction: [item()], golden: [], fix: [item({ kind: 'fix', id: 'sig1', text: '1 stored patch(es)', retired: true, retired_by: 'prime', help_rate: 0 })] } };
const week = (w, fp, cr) => ({ week: w, kinds: {}, builds: 1, first_pass: 0, corrections: 0, decided: 0, first_pass_rate: fp, correction_rate: cr });
const METRICS = { weeks: [week('2026-11-09', 0.5, null), week('2026-11-16', null, 0.2), week('2026-11-23', 0.75, 0.1)],
  totals: { correction: { help_rate: 0.25 }, golden: { help_rate: null }, fix: { help_rate: 0 } } };

const respond = (items = ITEMS) => api.client.get.mockImplementation((url) => ok(url.endsWith('/metrics') ? METRICS : items));

beforeEach(() => { cleanup(); vi.clearAllMocks(); });

describe('Learned (What Prime has learned)', () => {
  it('lists each kind with usage and help rate, and the weekly trend', async () => {
    api.getToken.mockReturnValue(jwt('member'));
    respond();
    renderAt(<Learned />);
    await settle();
    expect(screen.getByText('What Prime has learned')).toBeTruthy();
    const corr = screen.getByRole('region', { name: 'Approver corrections' });
    expect(within(corr).getByText('edited: wrong amount')).toBeTruthy();
    expect(within(corr).getByLabelText('Used 4 times, helped 25%')).toBeTruthy();
    expect(within(screen.getByRole('region', { name: 'Golden builds' })).getByText('Nothing learned yet.')).toBeTruthy();
    expect(within(screen.getByRole('region', { name: 'Build fixes' })).getByText('Retired by Prime')).toBeTruthy();
    expect(screen.getByTestId('latest-first_pass_rate').textContent).toBe('75%');
    expect(screen.getByTestId('latest-correction_rate').textContent).toBe('10%');
    expect(screen.queryByRole('button', { name: /Retire|Restore/ })).toBeNull();   // not an admin: no actions
  });

  it('an admin retires a lesson and restores a retired one, each with one call', async () => {
    api.getToken.mockReturnValue(jwt('admin'));
    respond();
    api.client.post.mockReturnValue(ok({}));
    renderAt(<Learned />);
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Retire edited: wrong amount' }));
    await settle();
    expect(api.client.post).toHaveBeenCalledWith('/prime/learning/items/correction/c1/retire');
    fireEvent.click(screen.getByRole('button', { name: 'Restore 1 stored patch(es)' }));
    await settle();
    expect(api.client.post).toHaveBeenCalledWith('/prime/learning/items/fix/sig1/restore');
    expect(api.client.post).toHaveBeenCalledTimes(2);
  });

  it('shows the server refusal instead of pretending it worked', async () => {
    api.getToken.mockReturnValue(jwt('admin'));
    respond();
    const p = Promise.reject({ response: { status: 403, data: { detail: 'Only an organisation owner or admin can do this' } } });
    p.catch(() => {});
    api.client.post.mockReturnValue(p);
    renderAt(<Learned />);
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Retire edited: wrong amount' }));
    await settle();
    expect(screen.getByRole('alert').textContent).toContain('Only an organisation owner or admin can do this');
  });
});
