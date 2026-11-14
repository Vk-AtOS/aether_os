import { useEffect, useRef } from 'react';
import { api } from '../api';

// One SSE client for a run's event stream (ProjectView feed and LiveEventLog both use it).
// The stream takes a single-use, run-scoped token (never the JWT in a URL), so a native
// EventSource auto-reconnect would be rejected: on error we close, fetch a fresh token and
// reconnect with exponential backoff, passing last_event_id so the server resumes after the
// last event seen instead of replaying the run from the start.
// onEvent(event) gets each parsed event; onOpen/onClose(connected) report state. The stream
// ends for good on pipeline_complete.
export const nextDelay = (attempt) => Math.min(1000 * 2 ** attempt, 30000);

export const useRunStream = (runId, { enabled = true, onEvent, onOpen, onClose } = {}) => {
  const cb = useRef({});
  useEffect(() => { cb.current = { onEvent, onOpen, onClose }; });

  useEffect(() => {
    if (!enabled || !runId) return undefined;
    let cancelled = false;
    let finished = false;
    let es = null;
    let timer = null;
    let attempt = 0;
    let lastId = null;

    const retry = () => {
      if (cancelled || finished) return;
      timer = setTimeout(connect, nextDelay(attempt));
      attempt += 1;
    };

    async function connect() {
      try {
        // api.client (not fetch) so a 401 goes through the token-refresh interceptor.
        const { data } = await api.client.post(`/factory/runs/${runId}/sse-token`);
        if (cancelled) return;
        const resume = lastId !== null ? `&last_event_id=${encodeURIComponent(lastId)}` : '';
        es = new EventSource(`/api/factory/runs/${runId}/stream?sse_token=${encodeURIComponent(data.sse_token)}${resume}`);
        es.onopen = () => { attempt = 0; cb.current.onOpen?.(); };
        es.onmessage = (e) => {
          if (e.lastEventId) lastId = e.lastEventId;
          let event;
          try { event = JSON.parse(e.data); } catch { return; }
          cb.current.onEvent?.(event);
          if (event.type === 'pipeline_complete') { finished = true; es.close(); cb.current.onClose?.(); }
        };
        es.onerror = () => { es.close(); cb.current.onClose?.(); retry(); };
      } catch (err) {
        // 401/403/404 will not fix themselves: stop instead of retrying every few seconds forever.
        const status = err?.response?.status;
        if (status === 401 || status === 403 || status === 404) { finished = true; return; }
        retry();
      }
    }

    connect();
    return () => { cancelled = true; clearTimeout(timer); es?.close(); };
  }, [runId, enabled]);
};
