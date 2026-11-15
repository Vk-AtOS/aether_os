// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent, cleanup, render } from '@testing-library/react';
import { ok, fail } from './helpers';

const api = vi.hoisted(() => ({ getNotificationPrefs: vi.fn(), setNotificationPref: vi.fn(), setOrgNotificationPref: vi.fn() }));
const role = vi.hoisted(() => ({ isAdmin: false }));
vi.mock('../api', () => ({ api, default: api }));
vi.mock('../hooks/useRole', () => ({ useRole: () => role }));

import NotificationPrefs from '../components/settings/NotificationPrefs';

const events = (over = {}) => ({ events: [
  { event: 'run_completed', label: 'A build finished', in_app: true, email: true, source: 'default', ...over },
] });
beforeEach(() => { cleanup(); vi.clearAllMocks(); role.isAdmin = false; });

describe('NotificationPrefs', () => {
  it('turning an event off in the bell sends only that channel', async () => {
    api.getNotificationPrefs.mockReturnValue(ok(events()));
    api.setNotificationPref.mockReturnValue(ok(events({ in_app: false })));
    render(<NotificationPrefs />);
    const box = await screen.findByLabelText('A build finished in app');
    fireEvent.click(box);
    await waitFor(() => expect(api.setNotificationPref).toHaveBeenCalledWith({ event: 'run_completed', in_app: false }));
    await waitFor(() => expect(screen.getByLabelText('A build finished in app').checked).toBe(false));
    expect(screen.queryByText('Organisation default')).toBeNull();
  });

  it('admins get the organisation default; a refusal is shown', async () => {
    role.isAdmin = true;
    api.getNotificationPrefs.mockReturnValue(ok(events()));
    api.setOrgNotificationPref.mockReturnValue(fail(403, 'Only org owners/admins may change the organisation default'));
    render(<NotificationPrefs />);
    await screen.findByLabelText('A build finished in app');
    fireEvent.click(screen.getByText('Edit organisation default'));
    fireEvent.click(screen.getByLabelText('Organisation default: A build finished email'));
    expect((await screen.findByRole('alert')).textContent).toMatch(/owners\/admins/);
  });
});
