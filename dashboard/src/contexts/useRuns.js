import { createContext, useContext } from 'react';

export const RunsContext = createContext(null);

export function useRuns() {
  const ctx = useContext(RunsContext);
  if (!ctx) throw new Error('useRuns must be used inside RunsProvider');
  return ctx;
}
