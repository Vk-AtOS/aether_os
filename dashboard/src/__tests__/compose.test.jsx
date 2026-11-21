// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { ok, fail } from './helpers';

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock('../api', () => ({ api: { client }, default: { client } }));
vi.mock('../components/confirmAction', () => ({ confirmAction: vi.fn(() => Promise.resolve(true)) }));

import Compose from '../components/mail/Compose';
import { MAX_ATT, draftReply } from '../components/mail/composeHelpers';

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

const attach = (name, bytes) => {
  const file = new File([new Uint8Array(bytes)], name, { type: 'text/plain' });
  fireEvent.change(screen.getByLabelText('Attach a file'), { target: { files: [file] } });
};

// KAN-154: the cap is for the whole message, not each file.
describe('Compose attachment total', () => {
  it('refuses a second file that takes the message over 45 KB in total', async () => {
    render(<Compose mb="mb1" onClose={() => {}} />);
    attach('a.txt', 30 * 1024);
    expect(await screen.findByText(/a\.txt/)).toBeTruthy();
    attach('b.txt', 20 * 1024);
    expect((await screen.findByRole('alert')).textContent).toMatch(/45 KB in total/);
    expect(screen.queryByText(/b\.txt/)).toBeNull();
  });

  it('accepts files that fit together', async () => {
    render(<Compose mb="mb1" onClose={() => {}} />);
    attach('a.txt', 20 * 1024);
    await screen.findByText(/a\.txt/);
    attach('b.txt', MAX_ATT - 20 * 1024);
    expect(await screen.findByText(/b\.txt/)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

// KAN-154 owner decision: Draft reply only creates a draft; it opens in the composer to be edited and sent.
describe('assistant draft reply', () => {
  it('opens with the draft text and sends as the person, replacing the assistant draft', async () => {
    const reply = draftReply('m1', { id: 'ad1', to: ['x@example.com'], subject: 'Re: hi', text: 'Thanks, noted.' });
    client.post.mockImplementation((url) => ok(url === DRAFTS ? { id: 'd2' } : { id: 's1', state: 'approved' }));
    client.delete.mockReturnValue(ok({ deleted: true }));
    client.get.mockReturnValue(ok({ id: 's1', state: 'approved' }));
    render(<Compose mb="mb1" reply={reply} onClose={() => {}} />);
    expect(screen.getByLabelText('Message body').value).toBe('Thanks, noted.');
    expect(screen.getByLabelText('To').value).toBe('x@example.com');
    expect(client.post).not.toHaveBeenCalled();   // opening it sends nothing
    fireEvent.click(screen.getByText('Send'));
    await screen.findByText('Message submitted');
    expect(client.delete).toHaveBeenCalledWith(`${DRAFTS}/ad1`);
  });
});
