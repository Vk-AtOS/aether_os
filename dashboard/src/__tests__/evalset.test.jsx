// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, cleanup, fireEvent } from '@testing-library/react';
import { renderAt, ok, settle } from './helpers';

const api = vi.hoisted(() => ({ client: { get: vi.fn(), put: vi.fn() } }));
vi.mock('../api', () => ({ api, default: api }));
vi.mock('../components/confirmAction', () => ({ confirmAction: vi.fn(() => Promise.resolve(true)) }));

import EvalSet from '../components/prime/EvalSet';

const CASE = { id: 'c1', agent: 'payables', action_type: 'invoice.approve', input: '{}', proposed: '{}', expected: '{"amount": "300"}' };

beforeEach(() => { cleanup(); vi.clearAllMocks(); });

describe('EvalSet', () => {
  it('lists the cases and removing one calls the API once, then reloads without it', async () => {
    api.client.get.mockReturnValueOnce(ok({ cases: [CASE] })).mockReturnValue(ok({ cases: [] }));
    api.client.put.mockReturnValue(ok({ id: 'c1', good_example: false }));
    renderAt(<EvalSet />);
    await settle();
    expect(screen.getByText('payables · invoice.approve')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Remove payables invoice.approve case'));
    await settle();
    expect(api.client.put).toHaveBeenCalledTimes(1);
    expect(api.client.put).toHaveBeenCalledWith('/prime/corrections/c1/good-example', { good: false });
    expect(screen.queryByText('payables · invoice.approve')).toBeNull();
    expect(screen.getByText('No cases yet')).toBeTruthy();
  });
});
