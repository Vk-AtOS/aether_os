// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent, cleanup, render } from '@testing-library/react';
import { ok, fail } from './helpers';

const api = vi.hoisted(() => ({
  listQuestionnaires: vi.fn(), getQuestionnaireStages: vi.fn(), sendQuestionnaire: vi.fn(), fillQuestionnaire: vi.fn(),
}));
vi.mock('../api', () => ({ api, default: api }));

import QuestionnairePanel from '../components/project/QuestionnairePanel';

const stages = [{ id: 's01_intake', label: 'Project Setup', questions: [{ id: 'app_name', label: 'Application name', type: 'text', required: true }] }];
beforeEach(() => {
  cleanup(); vi.clearAllMocks();
  api.listQuestionnaires.mockReturnValue(ok([{ id: 'q1', stage_id: 's01_intake', status: 'sent', respondent_email: 'c@x.com', expires_at: '2030-01-01T00:00:00', share_url: '/api/questionnaire/t' }]));
  api.getQuestionnaireStages.mockReturnValue(ok(stages));
});

describe('QuestionnairePanel', () => {
  it('lists sessions with status and sends one; with no email configured the link is shown', async () => {
    api.sendQuestionnaire.mockReturnValue(ok({ email_sent: false, share_url: 'https://app/api/questionnaire/abc', expires_at: '2030-01-01T00:00:00' }));
    render(<QuestionnairePanel runId="r1" />);
    expect(await screen.findByText('c@x.com')).toBeTruthy();
    fireEvent.change(await screen.findByLabelText('Stage to send'), { target: { value: 's01_intake' } });
    fireEvent.change(screen.getByLabelText('Client email'), { target: { value: 'n@x.com' } });
    fireEvent.click(screen.getByText('Send questionnaire'));
    await waitFor(() => expect(api.sendQuestionnaire).toHaveBeenCalledWith('r1', { stage_id: 's01_intake', respondent_email: 'n@x.com', respondent_name: '' }));
    expect((await screen.findByRole('status')).textContent).toMatch(/no email was sent.*https:\/\/app\/api\/questionnaire\/abc/);
  });

  it('fills on behalf from the stage questions and shows the server refusal', async () => {
    api.fillQuestionnaire.mockReturnValueOnce(fail(422, "'Application name' is required."));
    render(<QuestionnairePanel runId="r1" />);
    fireEvent.change(await screen.findByLabelText('Stage to fill'), { target: { value: 's01_intake' } });
    fireEvent.change(screen.getByLabelText('Application name *'), { target: { value: 'Acme' } });
    fireEvent.click(screen.getByText('Save answers'));
    await waitFor(() => expect(api.fillQuestionnaire).toHaveBeenCalledWith('r1', { stage_id: 's01_intake', answers: { app_name: 'Acme' } }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/is required/);
  });

  it('a viewer sees the list but no send or fill forms', async () => {
    render(<QuestionnairePanel runId="r1" isViewer />);
    await screen.findByText('c@x.com');
    expect(screen.queryByText('Send questionnaire')).toBeNull();
  });
});
