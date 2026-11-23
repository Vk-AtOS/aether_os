// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, cleanup, fireEvent } from '@testing-library/react';
import { renderAt, ok, fail, settle } from './helpers';

const api = vi.hoisted(() => ({ client: { get: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock('../api', () => ({ api, default: api }));
vi.mock('../components/confirmAction', () => ({ confirmAction: vi.fn(() => Promise.resolve(true)) }));

import YourData from '../components/prime/YourData';

const SW = ['all', 'git', 'jira', 'calendar', 'attendance'];
const state = (on = {}, counts = {}, newest = []) => ({
  notice: 'Shown to you alone.', notice_version: 'v1', retention_days: 365, newest,
  counts: { git: 0, jira: 0, calendar: 0, attendance: 0, ...counts },
  switches: SW.map((source) => ({ source, enabled: !!on[source], purpose: `${source} purpose`,
    enabled_at: on[source] ? '2026-11-20T09:00:00' : null })),
});

beforeEach(() => { cleanup(); vi.clearAllMocks(); });

describe('YourData', () => {
  it('starts with every switch off and the sources locked until the overall switch is on', async () => {
    api.client.get.mockReturnValue(ok(state()));
    renderAt(<YourData />);
    await settle();
    expect(screen.getAllByRole('switch').map((s) => s.getAttribute('aria-checked'))).toEqual(SW.map(() => 'false'));
    expect(screen.getByRole('switch', { name: 'Git' }).disabled).toBe(true);
    expect(screen.getByText('Nothing learned yet.')).toBeTruthy();
  });

  it('switching a source off sends the notice version and reports what was deleted', async () => {
    api.client.get.mockReturnValue(ok(state({ all: true, git: true }, { git: 2 },
      [{ id: 'i1', source: 'git', summary: 'Merged PR', learned_at: '2026-11-21T09:00:00' }])));
    api.client.put.mockReturnValue(ok({ erased: 2 }));
    renderAt(<YourData />);
    await settle();
    expect(screen.getByText('Merged PR')).toBeTruthy();
    fireEvent.click(screen.getByRole('switch', { name: 'Git' }));
    await settle();
    expect(api.client.put).toHaveBeenCalledWith('/prime/data/me/consent', { source: 'git', enabled: false, notice_version: 'v1' });
    expect(screen.getByRole('status').textContent).toBe('Git is off. 2 learned items deleted.');
  });

  it('erasing one source calls the API with that source; a failure is shown', async () => {
    api.client.get.mockReturnValue(ok(state({ all: true, jira: true }, { jira: 1 })));
    api.client.delete.mockReturnValueOnce(fail(403, 'Learned data is visible to that person alone'));
    renderAt(<YourData />);
    await settle();
    fireEvent.click(screen.getByLabelText('Erase Jira data'));
    await settle();
    expect(api.client.delete).toHaveBeenCalledWith('/prime/data/me/learned', { params: { source: 'jira' } });
    expect(screen.getByRole('alert').textContent).toContain('that person alone');
  });
});
