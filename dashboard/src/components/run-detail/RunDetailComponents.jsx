import React, { useState, useEffect, useRef } from 'react';
import { CheckCircle2, XCircle, Clock, Loader2 } from 'lucide-react';

export const PHASE_LABELS = {
  p01_intake_requirements: 'Intake & Requirements',
  p02_architecture:        'Architecture',
  p02b_domain_ir:          'Domain IR',
  p03_scaffolding:         'Scaffolding',
  p04_backend:             'Backend Codegen',
  p05_frontend:            'Frontend Codegen',
  p06_review_security:     'Review & Security',
  p07_testing:             'Testing',
  p07b_self_healing:       'Self-Healing',
  p08_cicd_deployment:     'CI/CD & Deployment',
  p09_observability:       'Observability',
  p10_docs_delivery:       'Docs & Delivery',
  p11_deployment:          'Deployment',
  p11a_monitoring:         'Monitoring',
  p11b_error_tracking:     'Error Tracking',
  p11c_analytics:          'Analytics',
  p11d_alerting:           'Alerting',
  p12a_feature_flags:      'Feature Flags',
  p12b_ab_testing:         'A/B Testing',
  p13_app_memory:          'App Memory',
  p14_client_portal:       'Client Portal',
};

export const fmtDuration = (ms) => {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
};

export const fmtTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' });
  } catch {
    return iso;
  }
};

export const StatusBadge = ({ status }) => {
  const cfg = {
    running:      { label: 'Running',       cls: 'bg-accent/20 text-accent border-accent/40', pulse: true  },
    needs_review: { label: 'Needs Review',  cls: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/40', pulse: false },
    completed:    { label: 'Completed',     cls: 'bg-success/20 text-success border-success/40', pulse: false },
    failed:       { label: 'Failed',        cls: 'bg-danger/20 text-danger border-danger/40', pulse: false },
    paused:       { label: 'Paused',        cls: 'bg-blue-500/20 text-blue-400 border-blue-500/40', pulse: false },
    cancelled:    { label: 'Cancelled',     cls: 'bg-muted/20 text-muted border-border', pulse: false },
  };
  const c = cfg[status] || { label: status || 'Unknown', cls: 'bg-border text-muted border-border', pulse: false };
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-bold px-2.5 py-1 rounded-full border ${c.cls}`}>
      {c.pulse && <span className="relative flex h-1.5 w-1.5"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" /><span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" /></span>}
      {c.label}
    </span>
  );
};

const PhasePill = ({ status }) => {
  if (status === 'completed' || status === 'complete') return <CheckCircle2 className="w-4 h-4 text-success shrink-0" />;
  if (status === 'running')   return <Loader2 className="w-4 h-4 text-accent animate-spin shrink-0" />;
  if (status === 'failed')    return <XCircle className="w-4 h-4 text-danger shrink-0" />;
  if (status === 'skipped')   return <span className="w-4 h-4 text-muted shrink-0 text-[10px] font-bold flex items-center justify-center">–</span>;
  return <Clock className="w-4 h-4 text-muted/40 shrink-0" />;
};

export const PhaseRow = ({ name, phaseData }) => {
  const label = PHASE_LABELS[name] || name;
  const status = phaseData?.status || 'pending';
  const duration = phaseData?.duration_ms ?? phaseData?.duration_seconds != null ? (phaseData.duration_ms ?? phaseData.duration_seconds * 1000) : null;
  const bgCls = status === 'running' ? 'bg-accent/5 border-accent/20' : status === 'failed' ? 'bg-danger/5 border-danger/20' : 'border-transparent';
  return (
    <tr className={`border-b border-border/50 last:border-0 ${bgCls}`}>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <PhasePill status={status} />
          <span className="text-xs text-bright font-mono">{name}</span>
        </div>
      </td>
      <td className="px-4 py-3 text-xs text-muted">{label}</td>
      <td className="px-4 py-3">
        <span className={`text-[10px] font-bold uppercase tracking-wider ${
          status === 'completed' || status === 'complete' ? 'text-success' :
          status === 'running'   ? 'text-accent' :
          status === 'failed'    ? 'text-danger' :
          status === 'skipped'   ? 'text-muted/50' :
          'text-muted/40'
        }`}>{status}</span>
      </td>
      <td className="px-4 py-3 text-xs font-mono text-muted text-right">{fmtDuration(duration)}</td>
    </tr>
  );
};

export const LiveEventLog = ({ runId }) => {
  const [lines, setLines] = useState([]);
  const [connected, setConnected] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    const token = localStorage.getItem('aether_token');
    const url = `/api/factory/runs/${runId}/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`;
    const es = new EventSource(url);
    es.onopen = () => setConnected(true);
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        const msg = data.message || data.text || JSON.stringify(data);
        setLines(prev => [...prev.slice(-200), msg]);
      } catch {
        setLines(prev => [...prev.slice(-200), e.data]);
      }
    };
    es.onerror = () => { setConnected(false); es.close(); };
    return () => es.close();
  }, [runId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [lines]);

  return (
    <div className="rounded-xl border border-border bg-[#0a0c10] overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-border/10">
        <span className={`w-2 h-2 rounded-full ${connected ? 'bg-success animate-pulse' : 'bg-muted'}`} />
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted">
          {connected ? 'Live Stream' : 'Disconnected'}
        </span>
      </div>
      <div className="h-64 overflow-y-auto p-4 font-mono text-xs text-bright/80 space-y-0.5 custom-scrollbar">
        {lines.length === 0 ? (
          <span className="text-muted">Waiting for events…</span>
        ) : (
          lines.map((line, i) => <div key={i}>{line}</div>)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};
