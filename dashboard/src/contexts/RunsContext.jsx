import React, { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api';

import { RunsContext } from './useRuns';

const POLL_IDLE_MS   = 10_000;  // poll interval when no run is active
const POLL_ACTIVE_MS =  5_000;  // faster poll while a run is in-flight
const PAGE_SIZE      = 20;
const MAX_CACHED     = 100;     // cap to prevent unbounded memory

export function RunsProvider({ children }) {
  const [runs, setRuns]               = useState([]);
  const [total, setTotal]             = useState(0);
  const [page, setPage]               = useState(1);
  const [costs, setCosts]             = useState({ total_usd: 0, week_usd: 0, today_usd: 0, tokens_today: '—' });
  const [health, setHealth]           = useState(null);
  const [loading, setLoading]         = useState(true);
  const [runsTruncated, setRunsTruncated] = useState(false);
  const timerRef                      = useRef(null);
  const runsRef                       = useRef([]);
  // The poll timer reads the latest list from a ref, kept in step after each render.
  useEffect(() => { runsRef.current = runs; }, [runs]);

  // Promise chains with no state set before the request: these run from an effect.
  const fetchRuns = useCallback((pg = 1) => api.listRuns(pg, PAGE_SIZE)
    .then((res) => {
      const data = res.data;
      const items = Array.isArray(data) ? data : (data?.items ?? []);
      const count = data?.total ?? items.length;
      setRuns(prev => {
        if (pg === 1) return items.slice(0, MAX_CACHED);
        const seen = new Set(prev.map(r => r.id || r.run_id));
        const combined = [...prev, ...items.filter(r => !seen.has(r.id || r.run_id))];
        return combined.slice(0, MAX_CACHED);
      });
      if (items.length > MAX_CACHED || (pg > 1 && runsRef.current.length + items.length > MAX_CACHED)) {
        setRunsTruncated(true);
      }
      setTotal(count);
    })
    .catch((e) => console.debug('Run list refresh failed; keeping the last list', e))
    .finally(() => setLoading(false)), []);

  const fetchCosts = useCallback(() => api.getCosts()
    .then((res) => setCosts(res.data))
    .catch((e) => console.debug('Cost refresh failed', e)), []);

  const fetchHealth = useCallback(() => api.getHealth()
    .then((res) => setHealth(res.data))
    .catch((e) => console.debug('Health refresh failed', e)), []);

  const refresh = useCallback(() => {
    fetchRuns(1);
    fetchCosts();
    fetchHealth();
  }, [fetchRuns, fetchCosts, fetchHealth]);

  // Adaptive polling — single timeout, not setInterval
  useEffect(() => {
    refresh();
    const schedule = () => {
      const hasActive = runsRef.current.some(r => r.status === 'running' || r.status === 'pending');
      timerRef.current = setTimeout(() => { refresh(); schedule(); }, hasActive ? POLL_ACTIVE_MS : POLL_IDLE_MS);
    };
    schedule();
    return () => clearTimeout(timerRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadMore = useCallback(() => {
    const next = page + 1;
    setPage(next);
    fetchRuns(next);
  }, [page, fetchRuns]);

  const hasMore        = runs.length < total && total > PAGE_SIZE;
  const activeRunCount = runs.filter(r => r.status === 'running').length;
  const latestRunId    = (() => {
    if (!runs.length) return null;
    const newest = runs.reduce((latest, run) => {
      const latestTime = new Date(latest.started_at || latest.created_at || 0);
      const runTime    = new Date(run.started_at    || run.created_at    || 0);
      return runTime > latestTime ? run : latest;
    });
    return newest.id || newest.run_id || null;
  })();

  return (
    <RunsContext.Provider value={{
      runs, total, costs, health, loading, refresh,
      activeRunCount, latestRunId, hasMore, loadMore, runsTruncated,
    }}>
      {children}
    </RunsContext.Provider>
  );
}
