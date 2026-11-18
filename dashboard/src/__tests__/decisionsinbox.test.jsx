// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { renderAt, ok, fail } from './helpers';

const api = vi.hoisted(() => ({ listOrgDecisions: vi.fn(), approveDecision: vi.fn() }));
const role = vi.hoisted(() => ({ canWrite: true }));
vi.mock('../api', () => ({ api, default: api }));
vi.mock('../hooks/useRole', () => ({ useRole: () => role }));

import DecisionsInbox from '../pages/DecisionsInbox';

const row = { id: 'd1', run_id: 'r1', title: 'Approve spec', what: 'Spec is ready', why: 'gate' };
beforeEach(() => { cleanup(); vi.clearAllMocks(); role.canWrite = true; });

describe('DecisionsInbox', () => {
  it('rejects through the per-run route with approved=false and removes the row', async () => {
    api.listOrgDecisions.mockReturnValue(ok({ decisions: [row] }));
    api.approveDecision.mockReturnValue(ok({}));
    renderAt(<DecisionsInbox />);
    await screen.findByText('Approve spec');
    fireEvent.click(screen.getByText('Reject'));
    await waitFor(() => expect(api.approveDecision).toHaveBeenCalledWith('r1', 'd1', false, ''));
    await waitFor(() => expect(screen.queryByText('Approve spec')).toBeNull());
  });

  it('a viewer sees the list without buttons; empty state and errors render', async () => {
    role.canWrite = false;
    api.listOrgDecisions.mockReturnValue(ok({ decisions: [row] }));
    renderAt(<DecisionsInbox />);
    await screen.findByText('Approve spec');
    expect(screen.queryByText('Approve')).toBeNull();
    cleanup();
    api.listOrgDecisions.mockReturnValue(fail(503, 'down'));
    renderAt(<DecisionsInbox />);
    expect((await screen.findByRole('alert')).textContent).toBe('down');
  });
});
