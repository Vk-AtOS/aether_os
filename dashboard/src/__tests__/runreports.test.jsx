// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, cleanup, render } from '@testing-library/react';
import { ok, fail } from './helpers';

const api = vi.hoisted(() => ({ getTestReport: vi.fn(), listSnapshots: vi.fn(), getSnapshot: vi.fn() }));
vi.mock('../api', () => ({ api, default: api }));

import TestsPanel from '../components/project/TestsPanel';
import SnapshotsPanel from '../components/project/SnapshotsPanel';

beforeEach(() => { cleanup(); vi.clearAllMocks(); });

describe('TestsPanel', () => {
  it('shows pass/fail counts and the failure text', async () => {
    api.getTestReport.mockReturnValue(ok({ passed: 3, failed: 1, errors: ['assert 1 == 2'], tests_written: 4 }));
    render(<TestsPanel runId="r1" />);
    expect(await screen.findByText('3 passed')).toBeTruthy();
    expect(screen.getByText('1 failed')).toBeTruthy();
    expect(screen.getByText('assert 1 == 2')).toBeTruthy();
  });
  it('404 is an empty state, other errors are alerts', async () => {
    api.getTestReport.mockReturnValue(fail(404, 'Report not found'));
    render(<TestsPanel runId="r1" />);
    expect(await screen.findByText(/No test report was recorded/)).toBeTruthy();
    cleanup();
    api.getTestReport.mockReturnValue(fail(500, 'boom'));
    render(<TestsPanel runId="r1" />);
    expect((await screen.findByRole('alert')).textContent).toBe('boom');
  });
});

describe('SnapshotsPanel', () => {
  it('lists snapshots and opens one to read its content', async () => {
    api.listSnapshots.mockReturnValue(ok({ snapshots: [{ id: 's1', file_path: 'src/main.py', created_at: 1700000000 }] }));
    api.getSnapshot.mockReturnValue(ok({ content: 'print(1)' }));
    render(<SnapshotsPanel runId="r1" />);
    fireEvent.click(await screen.findByText('src/main.py'));
    expect(await screen.findByText('print(1)')).toBeTruthy();
    expect(api.getSnapshot).toHaveBeenCalledWith('r1', 's1');
  });
});
