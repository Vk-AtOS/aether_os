// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { renderAt, ok } from './helpers';

const api = vi.hoisted(() => ({ getOnboarding: vi.fn(), dismissOnboarding: vi.fn() }));
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
});
