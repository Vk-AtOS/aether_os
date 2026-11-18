import React, { useState, useEffect } from 'react';
import { Gauge, Loader2 } from 'lucide-react';
import { api } from '../api';
import { apiError } from '../apiError';
import DataView from '../components/operator/DataView';

// Platform-operator console: read-only. Everything here is platform-wide and the server answers 403 to anyone
// but a superadmin; deploy and save-file stay API-only on purpose (they write to the host).
const SECTIONS = [
  { id: 'flags', title: 'Feature flags', load: () => api.operator.featureFlags(), pick: (d) => d.flags },
  { id: 'health', title: 'Platform health', load: () => api.operator.platformHealth() },
  { id: 'errors', title: 'Error registry (by category)', load: () => api.operator.errorSummary(), pick: (d) => d.by_category },
  { id: 'workloop', title: 'Workloop monitor', load: () => api.operator.workloop() },
  { id: 'quality', title: 'Quality metrics (your org)', load: () => api.operator.qualityMetrics() },
  { id: 'costs', title: 'Run costs (your org)', load: () => api.operator.runCosts(), pick: (d) => d.runs ?? d },
  { id: 'latency', title: 'Phase latency (your org)', load: () => api.operator.phaseLatency() },
];

const Section = ({ title, load, pick }) => {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    let live = true;
    load()
      .then((res) => live && setState({ loading: false, data: pick ? pick(res.data) : res.data, error: null }))
      .catch((e) => live && setState({ loading: false, data: null, error: apiError(e) || 'Failed to load.' }));
    return () => { live = false; };
  }, [load, pick]);
  return (
    <section className="panel p-4 space-y-2">
      <h2 className="text-xs font-bold text-muted uppercase tracking-widest">{title}</h2>
      {state.loading ? <Loader2 className="w-4 h-4 animate-spin text-accent" />
        : state.error ? <p role="alert" className="text-xs text-danger">{title}: {state.error}</p>
        : <DataView data={state.data} />}
    </section>
  );
};

const OperatorConsole = () => (
  <div className="max-w-5xl mx-auto space-y-4">
    <header className="flex items-center gap-3">
      <Gauge className="w-6 h-6 text-accent" />
      <div>
        <h1 className="text-2xl font-bold text-bright">Operator console</h1>
        <p className="text-muted text-sm">Platform-wide, read-only. Platform operators only.</p>
      </div>
    </header>
    {SECTIONS.map((s) => <Section key={s.id} title={s.title} load={s.load} pick={s.pick} />)}
  </div>
);

export default OperatorConsole;
