// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const api = vi.hoisted(() => ({ client: { post: vi.fn() } }));
vi.mock('../api', () => ({ api, default: api }));

import { useRunStream } from '../hooks/useRunStream';

class FakeES {
  static all = [];
  constructor(url) { this.url = url; this.closed = false; FakeES.all.push(this); }
  close() { this.closed = true; }
  emit(id, event) { this.onmessage({ lastEventId: String(id), data: JSON.stringify(event) }); }
}

const flush = async (ms = 0) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };

beforeEach(() => {
  vi.useFakeTimers();
  FakeES.all = [];
  globalThis.EventSource = FakeES;
  let n = 0;
  api.client.post.mockImplementation(() => Promise.resolve({ data: { sse_token: `tok${++n}` } }));
});
afterEach(() => { vi.useRealTimers(); });

describe('useRunStream reconnect (KAN-157)', () => {
  it('after a drop it asks for events after the last one seen, so each event is delivered once', async () => {
    const seen = [];
    renderHook(() => useRunStream('run1', { onEvent: (e) => seen.push(e.n) }));
    await flush();
    const first = FakeES.all[0];
    expect(first.url).toContain('sse_token=tok1');
    expect(first.url).not.toContain('last_event_id');
    first.emit(0, { n: 0 }); first.emit(1, { n: 1 });

    first.onerror();                     // connection killed mid-run
    expect(first.closed).toBe(true);
    await flush(1000);                   // first backoff step
    const second = FakeES.all[1];
    expect(second.url).toContain('sse_token=tok2');      // a fresh single-use token
    expect(second.url).toContain('last_event_id=1');     // resume after what was shown
    second.emit(2, { n: 2 });
    expect(seen).toEqual([0, 1, 2]);
  });

  it('pipeline_complete ends the stream for good; an unauthorised token request does not retry', async () => {
    const onClose = vi.fn();
    renderHook(() => useRunStream('run1', { onEvent: () => {}, onClose }));
    await flush();
    FakeES.all[0].emit(5, { type: 'pipeline_complete' });
    expect(onClose).toHaveBeenCalled();
    FakeES.all[0].onerror?.();
    await flush(60000);
    expect(FakeES.all.length).toBe(1);

    api.client.post.mockReset();
    api.client.post.mockRejectedValue({ response: { status: 403 } });
    renderHook(() => useRunStream('run2', { onEvent: () => {} }));
    await flush(60000);
    expect(api.client.post).toHaveBeenCalledTimes(1);
  });
});
