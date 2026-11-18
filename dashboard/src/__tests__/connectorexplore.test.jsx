// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, cleanup, render } from '@testing-library/react';
import { ok, fail, settle } from './helpers';

const api = vi.hoisted(() => ({ salesforceValidate: vi.fn(), salesforceObjects: vi.fn(), ldapValidate: vi.fn(), ldapUsers: vi.fn() }));
vi.mock('../api', () => ({ api, default: api }));

import ConnectorExplore from '../components/ConnectorExplore';

beforeEach(() => { cleanup(); vi.clearAllMocks(); });

describe('ConnectorExplore', () => {
  it('other connectors get nothing', () => {
    const { container } = render(<ConnectorExplore pluginId="figma" />);
    expect(container.firstChild).toBeNull();
  });

  it('salesforce: credentials go in the request body; the result is shown; the password field is masked', async () => {
    api.salesforceObjects.mockReturnValue(ok(['Account', 'Contact']));
    render(<ConnectorExplore pluginId="salesforce" />);
    expect(screen.getByLabelText('Access token').type).toBe('password');
    fireEvent.change(screen.getByLabelText('Instance URL'), { target: { value: 'https://x.my.salesforce.com' } });
    fireEvent.change(screen.getByLabelText('Access token'), { target: { value: 'tok' } });
    fireEvent.click(screen.getByText('List objects'));
    await settle();
    expect(api.salesforceObjects).toHaveBeenCalledWith({ instance_url: 'https://x.my.salesforce.com', access_token: 'tok' });
    expect(screen.getByRole('status').textContent).toMatch(/Account/);
  });

  it('ldap: validate failure text and server errors are shown', async () => {
    api.ldapValidate.mockReturnValueOnce(ok({ ok: false, message: 'LDAP server rejected: blocked host' }));
    render(<ConnectorExplore pluginId="ldap" />);
    fireEvent.click(screen.getByText('Validate'));
    await settle();
    expect(screen.getByRole('status').textContent).toMatch(/blocked host/);
    api.ldapUsers.mockReturnValue(fail(403, { error: 'role_insufficient', required_role: 'admin' }));
    fireEvent.click(screen.getByText('List users'));
    await settle();
    expect(screen.getByRole('alert').textContent).toMatch(/admin role/);
  });
});
