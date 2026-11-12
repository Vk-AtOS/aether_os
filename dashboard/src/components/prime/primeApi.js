import { useEffect, useState } from 'react';
import { api } from '../../api';
import { apiError } from '../../apiError';

// Prime endpoints beyond the ones in src/api.js, on the same axios client.
const c = api.client;
export const primeApi = {
  inbox: (params) => c.get('/prime/inbox', { params }),
  approve: (id, request_hash, reason) => c.post(`/prime/requests/${id}/approve`, { request_hash, reason }),
  reject: (id, request_hash, reason) => c.post(`/prime/requests/${id}/reject`, { request_hash, reason }),
  deputies: () => c.get('/prime/deputies'),
  getLimits: () => c.get('/prime/limits'),
  setLimits: (data) => c.put('/prime/limits', data),
  ledgerEntries: (params) => c.get('/prime/ledger/entries', { params }),
  ledgerEntry: (seq) => c.get(`/prime/ledger/entries/${seq}`),
  ledgerVerify: () => c.get('/prime/ledger/verify'),
  anchorLatest: () => c.get('/prime/ledger/anchor/latest'),
  anchorExport: () => c.get('/prime/ledger/anchor/export', { responseType: 'blob' }),
  eraseSubject: (subject) => c.post('/prime/ledger/subjects/erase', { subject }),
};

export const errText = (e, fallback) => {
  return apiError(e) || fallback;
};

// Loads `fetcher()` (memoise it with useCallback) and again on reload().
// Keeps the last data on screen while a reload is in flight.
export const useLoad = (fetcher, fallback = 'Could not load.') => {
  const [state, setState] = useState({ data: null, error: '', loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    fetcher()
      .then((res) => { if (alive) setState({ data: res.data, error: '', loading: false }); })
      .catch((e) => { if (alive) setState((s) => ({ ...s, error: errText(e, fallback), loading: false })); });
    return () => { alive = false; };
  }, [fetcher, fallback, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
};
