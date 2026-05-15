import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api';

const RunsContext = createContext(null);

export function RunsProvider({ children }) {
  const [runs, setRuns] = useState([]);
  const [costs, setCosts] = useState({ total_usd: 0, week_usd: 0, today_usd: 0, tokens_today: '—' });
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const intervalRef = useRef(null);

  const fetchRuns = useCallback(async () => {
    try {
      const res = await api.listRuns();
      const data = res.data;
      // Handle both paginated ({items: [...]}) and legacy ([...]) responses
      setRuns(Array.isArray(data) ? data : (data?.items ?? []));
    } catch {
      // ignore — stale data is fine
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchCosts = useCallback(async () => {
    try {
      const res = await api.getCosts();
      setCosts(res.data);
    } catch {}
  }, []);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await api.getHealth();
      setHealth(res.data);
    } catch {}
  }, []);

  const refresh = useCallback(() => {
    fetchRuns();
    fetchCosts();
    fetchHealth();
  }, [fetchRuns, fetchCosts, fetchHealth]);

  useEffect(() => {
    refresh();
    // Single polling interval shared by all consumers
    intervalRef.current = setInterval(refresh, 10000);
    return () => clearInterval(intervalRef.current);
  }, [refresh]);

  const activeRunCount = runs.filter((r) => r.status === 'running').length;
  const latestRunId = runs.length > 0 ? (runs[0].id || runs[0].run_id || null) : null;

  return (
    <RunsContext.Provider value={{ runs, costs, health, loading, refresh, activeRunCount, latestRunId }}>
      {children}
    </RunsContext.Provider>
  );
}

export function useRuns() {
  const ctx = useContext(RunsContext);
  if (!ctx) throw new Error('useRuns must be used inside RunsProvider');
  return ctx;
}
