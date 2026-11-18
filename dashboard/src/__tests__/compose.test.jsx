// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { ok, fail } from './helpers';

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock('../api', () => ({ api: { client }, default: { client } }));
vi.mock('../components/confirmAction', () => ({ confirmAction: vi.fn(() => Promise.resolve(true)) }));

import Compose from '../components/mail/Compose';

const DRAFTS = '/mail/mailboxes/mb1/drafts';
const send = () => {
  fireEvent.change(screen.getByLabelText('To'), { target: { value: 'a@example.com' } });
  fireEvent.click(screen.getByText('Send'));
};

beforeEach(() => { cleanup(); vi.clearAllMocks(); });

// KAN-154: sending is "create a draft, then submit it". The draft belongs to this form until it is submitted.
describe('Compose draft lifecycle', () => {
  it('removes the draft it created when the submit is refused', async () => {
    client.post.mockImplementation((url) => (url === DRAFTS ? ok({ id: 'd1' }) : fail(409, 'Sending is paused')));
    client.delete.mockReturnValue(ok({ deleted: true }));
    render(<Compose mb="mb1" onClose={() => {}} />);
    send();
    expect((await screen.findByRole('alert')).textContent).toContain('Sending is paused');
    expect(client.delete).toHaveBeenCalledWith(`${DRAFTS}/d1`);
  });

  it('a draft that could not be removed is removed on the next attempt or on Discard', async () => {
    client.post.mockImplementation((url) => (url === DRAFTS ? ok({ id: 'd1' }) : fail(503, 'Velaris is out')));
    client.delete.mockImplementation(() => fail(503, 'Velaris is out'));
    const onClose = vi.fn();
    render(<Compose mb="mb1" onClose={onClose} />);
    send();
    await screen.findByRole('alert');
    expect(client.delete).toHaveBeenCalledTimes(1);
    client.delete.mockReturnValue(ok({ deleted: true }));
    fireEvent.click(screen.getByText('Discard'));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(client.delete).toHaveBeenCalledTimes(2);
    expect(client.delete).toHaveBeenLastCalledWith(`${DRAFTS}/d1`);
  });

  it('keeps the draft when the submit is accepted', async () => {
    client.post.mockImplementation((url) => ok(url === DRAFTS ? { id: 'd1' } : { id: 's1', state: 'approved' }));
    client.get.mockReturnValue(ok({ id: 's1', state: 'approved' }));
    render(<Compose mb="mb1" onClose={() => {}} />);
    send();
    await screen.findByText('Message submitted');
    expect(client.delete).not.toHaveBeenCalled();
  });
});
