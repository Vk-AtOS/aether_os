import React, { useState, useEffect, useRef } from 'react';
import { CheckCircle2, XCircle, Clock, Loader2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { PHASE_LABELS, STAGE_STATUS_LABEL } from '../project/projectConstants';

import { fmtDuration } from './format';

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
  if (status === 'passed' || status === 'completed' || status === 'complete') return <CheckCircle2 className="w-4 h-4 text-success shrink-0" />;
  if (status === 'running')   return <Loader2 className="w-4 h-4 text-accent animate-spin shrink-0" />;
  if (status === 'failed' || status === 'timeout') return <XCircle className="w-4 h-4 text-danger shrink-0" />;
  if (status === 'skipped')   return <span className="w-4 h-4 text-muted shrink-0 text-[10px] font-bold flex items-center justify-center">–</span>;
  return <Clock className="w-4 h-4 text-muted/40 shrink-0" />;
};

// state: {status, reason} from stageStates() (12-stage runs); older runs fall back to the row status.
export const PhaseRow = ({ name, phaseData, state, href }) => {
  const label = PHASE_LABELS[name] || name;
  const status = state?.status || phaseData?.status || 'pending';
  const reason = state?.reason || '';
  const duration = phaseData?.duration_s != null ? phaseData.duration_s * 1000 : null;
  const bad = status === 'failed' || status === 'timeout';
  const grey = status === 'skipped' || status === 'not_run';
  const bgCls = status === 'running' ? 'bg-accent/5 border-accent/20' : bad ? 'bg-danger/10 border-danger/30' : 'border-transparent';
  return (
    <tr className={`border-b border-border/50 last:border-0 ${bgCls} ${grey ? 'opacity-60' : ''}`}>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <PhasePill status={status} />
          {href
            ? <Link to={href} className="text-xs text-bright font-mono hover:text-accent underline-offset-2 hover:underline">{name}</Link>
            : <span className="text-xs text-bright font-mono">{name}</span>}
        </div>
      </td>
      <td className="px-4 py-3 text-xs text-muted">
        {label}
        {reason && <div className={`mt-0.5 text-[11px] break-words ${bad ? 'text-danger' : 'text-muted'}`}>{reason}</div>}
      </td>
      <td className="px-4 py-3">
        <span className={`text-[10px] font-bold uppercase tracking-wider ${
          status === 'passed' || status === 'completed' || status === 'complete' ? 'text-success' :
          status === 'running' ? 'text-accent' :
          bad ? 'text-danger' :
          'text-muted/50'
        }`}>{STAGE_STATUS_LABEL[status] || status}</span>
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
    // The stream only accepts a short-lived, run-scoped token. Sending the session
    // JWT in the query string was rejected (401) and would leak it into server logs.
    let es = null;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/factory/runs/${runId}/sse-token`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${localStorage.getItem('aether_token')}` },
        });
        if (!res.ok || cancelled) return;
        const { sse_token } = await res.json();
        if (cancelled) return;
        es = new EventSource(`/api/factory/runs/${runId}/stream?sse_token=${encodeURIComponent(sse_token)}`);
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
      } catch (err) {
        console.warn('Live log: could not open the event stream', err);
      }
    })();
    return () => { cancelled = true; es?.close(); };
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
