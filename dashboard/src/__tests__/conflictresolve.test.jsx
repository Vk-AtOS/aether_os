// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { ok } from './helpers';

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../api', () => ({ api: { client }, default: { client } }));

import { ConflictResolverTool, findResolved } from '../components/intelligence/IntelligenceTools';

beforeEach(() => { cleanup(); vi.clearAllMocks(); });

const detect = () => fireEvent.click(screen.getByText(/detect/i, { selector: 'button' }));

describe('conflict resolution is org-wide (KAN-154)', () => {
  it('findResolved matches on the description, case-insensitively', () => {
    const shared = { k: { description: 'Latency vs consistency', resolved_by: 'u1' } };
    expect(findResolved(shared, ' latency VS consistency ')?.resolved_by).toBe('u1');
    expect(findResolved(shared, 'other')).toBeNull();
  });

  it('shows a conflict resolved by a colleague, with who resolved it', async () => {
    client.get.mockReturnValue(ok({ resolved: { k: { description: 'A vs B', resolution: 'pick A', resolved_by: 'colleague' } } }));
    client.post.mockReturnValue(ok({ conflicts: [{ id: 'C1', description: 'A vs B' }] }));
    render(<ConflictResolverTool />);
    detect();
    expect((await screen.findByTestId('resolved-by')).textContent).toContain('colleague');
    expect(screen.queryByText('Resolve')).toBeNull();
  });

  it('sends the description so the resolution is recorded for the whole org', async () => {
    client.get.mockReturnValue(ok({ resolved: {} }));
    client.post.mockImplementation((url) => ok(url.endsWith('detect')
      ? { conflicts: [{ id: 'C1', description: 'A vs B' }] }
      : { key: 'd-1', resolved_by: 'me' }));
    render(<ConflictResolverTool />);
    detect();
    fireEvent.click(await screen.findByText('Resolve'));
    fireEvent.change(screen.getByPlaceholderText('Describe the resolution…'), { target: { value: 'pick A' } });
    fireEvent.click(screen.getByText('Submit'));
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/intelligence/conflict-resolver/resolve',
      expect.objectContaining({ conflict_id: 'C1', description: 'A vs B', resolution: 'pick A' })));
    expect((await screen.findByTestId('resolved-by')).textContent).toContain('by me');
  });
});
