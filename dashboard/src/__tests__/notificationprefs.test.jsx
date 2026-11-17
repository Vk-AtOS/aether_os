// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent, cleanup, render } from '@testing-library/react';
import { ok, fail, settle } from './helpers';

const api = vi.hoisted(() => ({ getNotificationPrefs: vi.fn(), setNotificationPref: vi.fn(), setOrgNotificationPref: vi.fn(), getQuietHours: vi.fn(), setQuietHours: vi.fn() }));
const role = vi.hoisted(() => ({ isAdmin: false }));
vi.mock('../api', () => ({ api, default: api }));
vi.mock('../hooks/useRole', () => ({ useRole: () => role }));

import NotificationPrefs from '../components/settings/NotificationPrefs';

const events = (over = {}) => ({ events: [
  { event: 'run_completed', label: 'A build finished', in_app: true, email: true, source: 'default', ...over },
] });
beforeEach(() => { cleanup(); vi.clearAllMocks(); role.isAdmin = false; api.getQuietHours.mockReturnValue(ok({ quiet_hours: null })); });

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

  it('quiet hours load, save with the zone, and a server refusal is shown', async () => {
    api.getNotificationPrefs.mockReturnValue(ok(events()));
    api.getQuietHours.mockReturnValue(ok({ quiet_hours: { start: '21:00', end: '06:30', tz: 'Asia/Kolkata', source: 'user' } }));
    api.setQuietHours.mockReturnValueOnce(ok({})).mockReturnValueOnce(fail(422, 'tz must be an IANA time zone'));
    render(<NotificationPrefs />);
    await settle();
    expect(screen.getByLabelText('Quiet hours start').value).toBe('21:00');
    fireEvent.click(screen.getByText('Save'));
    await settle();
    expect(api.setQuietHours).toHaveBeenCalledWith({ start: '21:00', end: '06:30', tz: 'Asia/Kolkata' });
    expect(screen.getByRole('status').textContent).toBe('Saved.');
    fireEvent.change(screen.getByLabelText('Quiet hours time zone'), { target: { value: 'Mars/Base' } });
    fireEvent.click(screen.getByText('Save'));
    await settle();
    expect(screen.getByRole('alert').textContent).toMatch(/IANA/);
  });
});
