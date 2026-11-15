// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent, cleanup, render } from '@testing-library/react';
import { ok, fail } from './helpers';

const api = vi.hoisted(() => ({ cancelSubscription: vi.fn(), downgradePlan: vi.fn() }));
vi.mock('../api', () => ({ api, default: api }));
const confirmAction = vi.hoisted(() => vi.fn(() => Promise.resolve(true)));
vi.mock('../components/confirmAction', () => ({ confirmAction }));

import PlanReduction from '../components/billing/PlanReduction';

beforeEach(() => { cleanup(); vi.clearAllMocks(); confirmAction.mockResolvedValue(true); });

describe('PlanReduction', () => {
  it('offers only lower plans and nothing on the lowest', () => {
    const { container, rerender } = render(<PlanReduction currentPlan="pro" onDone={vi.fn()} onError={vi.fn()} />);
    const opts = [...container.querySelectorAll('option')].map((o) => o.value);
    expect(opts).toEqual(['', 'free', 'starter']);
    rerender(<PlanReduction currentPlan="free" onDone={vi.fn()} onError={vi.fn()} />);
    expect(container.querySelector('select')).toBeNull();
  });

  it('downgrade confirms, calls /billing/downgrade and reports', async () => {
    api.downgradePlan.mockReturnValue(ok({ success: true }));
    const onDone = vi.fn();
    render(<PlanReduction currentPlan="enterprise" periodEnd={1900000000} onDone={onDone} onError={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Lower plan'), { target: { value: 'pro' } });
    fireEvent.click(screen.getByText('Apply'));
    await waitFor(() => expect(api.downgradePlan).toHaveBeenCalledWith('pro'));
    expect(confirmAction.mock.calls[0][0]).toMatch(/still ends on/);
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('Plan changed to Pro.'));
  });

  it('free is the cancel path; declining the confirmation changes nothing; server errors are shown', async () => {
    confirmAction.mockResolvedValueOnce(false);
    const onError = vi.fn();
    render(<PlanReduction currentPlan="pro" onDone={vi.fn()} onError={onError} />);
    fireEvent.change(screen.getByLabelText('Lower plan'), { target: { value: 'free' } });
    fireEvent.click(screen.getByText('Apply'));
    await waitFor(() => expect(confirmAction).toHaveBeenCalled());
    expect(api.cancelSubscription).not.toHaveBeenCalled();
    api.cancelSubscription.mockReturnValue(fail(502, 'Could not change the subscription with the payment provider; nothing was changed. Try again.'));
    fireEvent.click(screen.getByText('Apply'));
    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringMatching(/nothing was changed/)));
  });
});
