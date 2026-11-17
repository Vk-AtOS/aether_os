import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api';
import { apiError } from '../../apiError';

// Velaris products through the gateway proxies (/chat, /mail, /control, /hr). Velaris errors arrive as
// {error: {code, message}}; gateway errors (503 when Velaris is out, 403 role) as {detail}.
export const vc = api.client;

export const vError = (e, fallback = 'The request failed.') =>
  e?.response?.data?.error?.message || apiError(e) || e?.message || fallback;
export const vCode = (e) => e?.response?.data?.error?.code || '';
export const isDown = (e) => e?.response?.status === 503;

// Loads fetcher() (memoise it with useCallback; a new fetcher loads again). Keeps data on screen while reloading.
export const useVelaris = (fetcher) => {
  const [tick, setTick] = useState(0);
  const [state, setState] = useState({ key: null, data: null, error: '', down: false });
  const key = `${tick}`;
  useEffect(() => {
    let alive = true;
    fetcher()
      .then((res) => { if (alive) setState({ fetcher, key, data: res.data, error: '', down: false }); })
      .catch((e) => { if (alive) setState({ fetcher, key, data: null, error: vError(e), down: isDown(e) }); });
    return () => { alive = false; };
  }, [fetcher, key]);
  const fresh = state.fetcher === fetcher;
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data: fresh ? state.data : null, error: fresh ? state.error : '', down: fresh ? state.down : false,
    loading: !fresh, reload };
};

// HR agent methods through the allow-listed proxy. Resolves {pending, run, result}. Throws Error(message):
// HTTP errors, and agent-level refusals (result.status other than ok).
export const hr = async (agent, method, args = {}) => {
  let res;
  try {
    res = await vc.post(`/hr/${agent}/${method}`, args);
  } catch (e) {
    const err = new Error(vError(e));
    err.down = isDown(e);
    throw err;
  }
  if (res.status === 202) return { pending: true, run: res.data.run || null, result: null };
  const result = res.data.result ?? {};
  if (result && result.status && result.status !== 'ok') {
    throw new Error(result.reason || (result.errors || []).join('; ') || String(result.status).replace(/_/g, ' '));
  }
  return { pending: false, run: null, result };
};

export const useHr = (agent, method, args = {}) => {
  const k = JSON.stringify(args);
  // An empty id (nothing chosen yet) is not a request: asking Velaris for "" only produces an error banner.
  const blank = Object.entries(args).some(([n, v]) => /_id$/.test(n) && (v === '' || v == null));
  const fetcher = useCallback(() => (blank ? Promise.resolve({ data: null }) : hr(agent, method, JSON.parse(k)).then((r) => ({ data: r.result }))), [agent, method, k, blank]);
  return useVelaris(fetcher);
};

export const when = (ts) => {
  const n = Number(ts);
  const d = Number.isFinite(n) && n > 0 ? new Date(n < 1e12 ? n * 1000 : n) : new Date(ts);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
};

export const btn = (kind = 'primary') => ({
  primary: 'px-3 py-1.5 bg-accent hover:bg-accent/90 text-white text-xs font-bold rounded-lg disabled:opacity-50 transition-colors',
  ghost: 'px-3 py-1.5 border border-border text-muted hover:text-bright text-xs font-bold rounded-lg disabled:opacity-50 transition-colors',
  danger: 'px-3 py-1.5 border border-danger/50 text-danger hover:bg-danger/10 text-xs font-bold rounded-lg disabled:opacity-50 transition-colors',
}[kind]);


const urlOf = (c) => (c.hr ? `/hr/${c.hr[0]}/${c.hr[1]}` : c.agent ? `/velaris/agents/${c.agent[0]}/${c.agent[1]}` : c.path);

const save = (name, data) => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

// -> {pending, run, result}. Throws Error(plain message) with .down for 503.
export const send = async (call, args = {}, { download } = {}) => {
  const method = (call.method || 'post').toLowerCase();
  if (call.hr && !download) return hr(call.hr[0], call.hr[1], args);
  let res;
  try {
    res = await vc.request({ method, url: urlOf(call), data: method === 'get' || call.asQuery ? undefined : args, params: method === 'get' || call.asQuery ? args : undefined });
  } catch (e) {
    const err = new Error(vError(e));
    err.down = isDown(e);
    throw err;
  }
  if (res.status === 202) return { pending: true, run: res.data.run || null, result: null };
  if (download) { save(download, res.data); return { pending: false, result: { saved: download } }; }
  const body = res.data;
  const result = call.agent || call.hr ? (body.result ?? {}) : body;
  if (result && result.status && result.status !== 'ok' && (call.agent || call.hr)) {
    throw new Error(result.reason || (result.errors || []).join('; ') || String(result.status).replace(/_/g, ' '));
  }
  return { pending: false, run: null, result };
};

