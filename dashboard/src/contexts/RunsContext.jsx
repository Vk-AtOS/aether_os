import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api';

const RunsContext = createContext(null);

const POLL_IDLE_MS   = 10_000;  // poll interval when no run is active
const POLL_ACTIVE_MS =  5_000;  // faster poll while a run is in-flight
const PAGE_SIZE      = 20;
const MAX_CACHED     = 100;     // cap to prevent unbounded memory

export function RunsProvider({ children }) {
  const [runs, setRuns]       = useState([]);
  const [total, setTotal]     = useState(0);
  const [page, setPage]       = useState(1);
  const [costs, setCosts]     = useState({ total_usd: 0, week_usd: 0, today_usd: 0, tokens_today: '—' });
  const [health, setHealth]   = useState(null);
  const [loading, setLoading] = useState(true);
  const timerRef              = useRef(null);
  const runsRef               = useRef([]);
  runsRef.current = runs;

  const fetchRuns = useCallback(async (pg = 1) => {
    try {
      const res = await api.listRuns(pg, PAGE_SIZE);
      const data = res.data;
      const items = Array.isArray(data) ? data : (data?.items ?? []);
      const count = data?.total ?? items.length;
      setRuns(prev => {
        if (pg === 1) {
          const result = items.slice(0, MAX_CACHED);
          if (items.length > MAX_CACHED) {
            console.warn(`[RunsContext] Capped at ${MAX_CACHED} runs; ${items.length - MAX_CACHED} older runs not displayed.`);
          }
          return result;
        }
        const seen = new Set(prev.map(r => r.id || r.run_id));
        const fresh = items.filter(r => !seen.has(r.id || r.run_id));
        const combined = [...prev, ...fresh];
        if (combined.length > MAX_CACHED) {
          console.warn(`[RunsContext] Run cache at limit (${MAX_CACHED}); oldest runs dropped.`);
          return combined.slice(0, MAX_CACHED);
        }
        return combined;
      });
      setTotal(count);
    } catch {
      // stale data is acceptable
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchCosts = useCallback(async () => {
    try { const res = await api.getCosts(); setCosts(res.data); } catch {}
  }, []);

  const fetchHealth = useCallback(async () => {
    try { const res = await api.getHealth(); setHealth(res.data); } catch {}
  }, []);

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
  const latestRunId    = runs.length > 0 ? (runs[0].id || runs[0].run_id || null) : null;

  return (
    <RunsContext.Provider value={{
      runs, total, costs, health, loading, refresh,
      activeRunCount, latestRunId, hasMore, loadMore,
    }}>
      {children}
    </RunsContext.Provider>
  );
}

export function useRuns() {
  const ctx = useContext(RunsContext);
  if (!ctx) throw new Error('useRuns must be used inside RunsProvider');
  return ctx;
}
