import { describe, expect, it, vi } from 'vitest';

const store = {};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};

const { openPreviewInTab, previewOpenPath } = await import('../previewSession');

describe('Live App opens a same-origin page, not a blank tab steered later', () => {
  it('opens /dashboard/preview-open/<run> inside the click, with noopener', async () => {
    const open = vi.fn(() => null);
    globalThis.window = { open };
    expect(await openPreviewInTab('run 1')).toBeNull();
    expect(open).toHaveBeenCalledTimes(1);
    const [url, target, features] = open.mock.calls[0];
    expect(url).toBe(previewOpenPath('run 1'));
    expect(url).toMatch(/\/preview-open\/run%201$/);
    expect(url).not.toBe('about:blank');
    expect(target).toBe('_blank');
    expect(features).toBe('noopener');
  });
});
