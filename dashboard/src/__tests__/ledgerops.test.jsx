// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent, cleanup, render } from '@testing-library/react';
import { ok, fail } from './helpers';

const primeApi = vi.hoisted(() => ({
  anchorNow: vi.fn(), anchorVerify: vi.fn(), anchorCheckFile: vi.fn(), backfill: vi.fn(), retryErasures: vi.fn(),
}));
vi.mock('../components/prime/primeApi', () => ({ primeApi, errText: (e, f) => e?.response?.data?.detail || f }));
const confirmAction = vi.hoisted(() => vi.fn(() => Promise.resolve(true)));
vi.mock('../components/confirmAction', () => ({ confirmAction }));

import LedgerOps from '../components/prime/LedgerOps';

beforeEach(() => { cleanup(); vi.clearAllMocks(); confirmAction.mockResolvedValue(true); });

describe('LedgerOps', () => {
  it('renders nothing for a plain member', () => {
    const { container } = render(<LedgerOps isAdmin={false} isSuperadmin={false} />);
    expect(container.firstChild).toBeNull();
  });

  it('admin: anchor now confirms and shows the JSON result; superadmin-only buttons are absent', async () => {
    primeApi.anchorNow.mockReturnValue(ok({ checkpoint: { chain_seq: 7 } }));
    render(<LedgerOps isAdmin isSuperadmin={false} />);
    expect(screen.queryByText('Retry erasures')).toBeNull();
    fireEvent.click(screen.getByText('Anchor now'));
    await waitFor(() => expect(primeApi.anchorNow).toHaveBeenCalled());
    expect((await screen.findByRole('status')).textContent).toMatch(/"chain_seq": 7/);
  });

  it('a refusal is shown and declining a confirmation calls nothing', async () => {
    primeApi.retryErasures.mockReturnValue(fail(403, 'Superadmin only'));
    render(<LedgerOps isAdmin isSuperadmin />);
    confirmAction.mockResolvedValueOnce(false);
    fireEvent.click(screen.getByText('Retry erasures'));
    await waitFor(() => expect(confirmAction).toHaveBeenCalled());
    expect(primeApi.retryErasures).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Retry erasures'));
    expect((await screen.findByText(/Superadmin only/))).toBeTruthy();
  });

  it('a kept anchor file is verified against its newest checkpoint; garbage is rejected locally', async () => {
    primeApi.anchorVerify.mockReturnValue(ok({ ok: true }));
    render(<LedgerOps isAdmin isSuperadmin={false} />);
    const input = screen.getByLabelText('Anchor export file');
    const file = (txt) => new File([txt], 'a.json', { type: 'application/json' });
    fireEvent.change(input, { target: { files: [file(JSON.stringify({ checkpoints: [{ chain_seq: 1 }, { chain_seq: 9 }] }))] } });
    await waitFor(() => expect(primeApi.anchorVerify).toHaveBeenCalledWith({ full: true, checkpoint: { chain_seq: 9 } }));
    fireEvent.change(input, { target: { files: [file('not json')] } });
    expect(await screen.findByText(/not an anchor export/)).toBeTruthy();
  });
});
