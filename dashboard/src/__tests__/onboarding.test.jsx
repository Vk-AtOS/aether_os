// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { renderAt, ok } from './helpers';

const api = vi.hoisted(() => ({ getOnboarding: vi.fn(), dismissOnboarding: vi.fn(), acceptDpa: vi.fn(), updateOrgSettings: vi.fn() }));
const role = vi.hoisted(() => ({ isAdmin: true }));
vi.mock('../api', () => ({ api, default: api }));
vi.mock('../hooks/useRole', () => ({ useRole: () => role }));

import OnboardingBanner from '../components/OnboardingBanner';

const steps = [
  { id: 'llm_key', title: 'Add an LLM API key', done: true, required: true, link: '/settings' },
  { id: 'first_run', title: 'Run your first pipeline', done: false, required: true, link: '/new' },
  { id: 'sso', title: 'Connect single sign-on', done: false, required: false, link: '/settings/sso' },
];
beforeEach(() => { cleanup(); vi.clearAllMocks(); role.isAdmin = true; });

describe('OnboardingBanner', () => {
  it('renders server steps and dismisses for the organisation', async () => {
    api.getOnboarding.mockReturnValue(ok({ steps, dismissed: false, complete: false }));
    api.dismissOnboarding.mockReturnValue(ok({ dismissed: true }));
    renderAt(<OnboardingBanner />);
    expect(await screen.findByText('1/3 steps complete')).toBeTruthy();
    expect(screen.getByText('optional')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Dismiss onboarding'));
    await waitFor(() => expect(api.dismissOnboarding).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText('Welcome to AetherOS Factory')).toBeNull());
  });

  it('stays hidden when dismissed or complete, and a non-admin cannot dismiss', async () => {
    api.getOnboarding.mockReturnValue(ok({ steps, dismissed: true, complete: false }));
    const { container } = renderAt(<OnboardingBanner />);
    await waitFor(() => expect(api.getOnboarding).toHaveBeenCalled());
    expect(container.textContent).toBe('');
    cleanup();
    role.isAdmin = false;
    api.getOnboarding.mockReturnValue(ok({ steps, dismissed: false, complete: false }));
    renderAt(<OnboardingBanner />);
    await screen.findByText('1/3 steps complete');
    expect(screen.queryByLabelText('Dismiss onboarding')).toBeNull();
  });

  it('the name step saves the organisation name and the DPA step records the accepted version', async () => {
    const todo = [
      { id: 'org_name', title: 'Name your organisation', done: false, required: true, link: '/settings' },
      { id: 'dpa', title: 'Accept the data processing agreement', done: false, required: true, link: '/legal?doc=dpa' }];
    api.getOnboarding.mockReturnValueOnce(ok({ steps: todo, dismissed: false, complete: false }))
      .mockReturnValueOnce(ok({ steps: [{ ...todo[0], done: true }, todo[1]], dismissed: false, complete: false }));
    api.updateOrgSettings.mockReturnValue(ok({}));
    api.acceptDpa.mockReturnValue(ok({ accepted: true }));
    renderAt(<OnboardingBanner />);
    fireEvent.change(await screen.findByLabelText('Organisation name'), { target: { value: ' Acme ' } });
    fireEvent.click(screen.getByText('Save name'));
    await waitFor(() => expect(api.updateOrgSettings).toHaveBeenCalledWith({ org_name: 'Acme' }));
    fireEvent.click(await screen.findByText('Accept the DPA'));
    await waitFor(() => expect(api.acceptDpa).toHaveBeenCalledWith('1.0'));
  });
});
