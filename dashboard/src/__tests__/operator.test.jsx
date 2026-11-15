// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, cleanup, render } from '@testing-library/react';
import { ok, fail } from './helpers';

const op = vi.hoisted(() => ({
  featureFlags: vi.fn(), platformHealth: vi.fn(), errorSummary: vi.fn(), workloop: vi.fn(),
  qualityMetrics: vi.fn(), runCosts: vi.fn(), phaseLatency: vi.fn(),
}));
vi.mock('../api', () => ({ api: { operator: op }, default: { operator: op } }));

import OperatorConsole from '../pages/OperatorConsole';

beforeEach(() => {
  cleanup();
  Object.values(op).forEach((f) => f.mockReturnValue(ok({})));
});

describe('OperatorConsole', () => {
  it('shows flags and error categories as tables', async () => {
    op.featureFlags.mockReturnValue(ok({ flags: { new_router: true } }));
    op.errorSummary.mockReturnValue(ok({ by_category: { relative_import: { count: 3 } } }));
    render(<OperatorConsole />);
    expect(await screen.findByText('new_router')).toBeTruthy();
    expect(await screen.findByText('relative_import')).toBeTruthy();
  });

  it('a 403 from a section is shown, not swallowed', async () => {
    op.platformHealth.mockReturnValue(fail(403, 'Platform operator access required'));
    render(<OperatorConsole />);
    expect((await screen.findByRole('alert')).textContent).toMatch(/Platform operator access required/);
  });
});
