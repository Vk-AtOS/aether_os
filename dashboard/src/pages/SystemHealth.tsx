import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import {
  Activity, RefreshCw, Loader2, CheckCircle2, AlertTriangle, XCircle,
  Server, Database, Cpu, HardDrive, Wifi, Clock, Zap, MemoryStick,
  ShieldCheck, Eye,
} from 'lucide-react';
import { apiError } from '../apiError';

const STATUS = {
  ok:             { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', icon: CheckCircle2,  label: 'OK' },
  healthy:        { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', icon: CheckCircle2,  label: 'Healthy' },
  degraded:       { color: 'text-yellow-400',  bg: 'bg-yellow-500/10 border-yellow-500/30',   icon: AlertTriangle, label: 'Degraded' },
  warning:        { color: 'text-yellow-400',  bg: 'bg-yellow-500/10 border-yellow-500/30',   icon: AlertTriangle, label: 'Warning' },
  error:          { color: 'text-red-400',     bg: 'bg-red-500/10 border-red-500/30',          icon: XCircle,       label: 'Error' },
  unavailable:    { color: 'text-muted',       bg: 'bg-border/20 border-border',               icon: AlertTriangle, label: 'Unavailable' },
  not_configured: { color: 'text-muted',       bg: 'bg-border/20 border-border',               icon: AlertTriangle, label: 'Not Configured' },
  unreachable:    { color: 'text-yellow-400',  bg: 'bg-yellow-500/10 border-yellow-500/30',   icon: AlertTriangle, label: 'Unreachable' },
  unknown:        { color: 'text-muted',       bg: 'bg-border/20 border-border',               icon: AlertTriangle, label: 'Unknown' },
};

const getStatus = (s) => STATUS[s?.toLowerCase()] || STATUS.unknown;

const SkeletonCard = () => (
  <div className="bg-panel border border-border rounded-xl p-5 animate-pulse space-y-3">
    <div className="flex items-center gap-2">
      <div className="w-4 h-4 rounded bg-border/40" />
      <div className="h-3.5 w-32 bg-border/40 rounded" />
    </div>
    <div className="h-2.5 w-full bg-border/30 rounded" />
    <div className="h-2.5 w-2/3 bg-border/30 rounded" />
  </div>
);

const MetricBar = ({ label, value, max = 100, unit = '%', warn = 70, crit = 90 }) => {
  const pct = Math.min(100, Math.round((value / max) * 100));
  const color = pct >= crit ? 'bg-red-400' : pct >= warn ? 'bg-yellow-400' : 'bg-emerald-400';
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span className="font-mono text-bright">{typeof value === 'number' ? value.toFixed(1) : value}{unit}</span>
      </div>
      <div className="h-1.5 bg-border rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
};

const ServiceCard = ({ name, icon: Icon, status, details = [] }) => {
  const meta = getStatus(status);
  const StatusIcon = meta.icon;
  return (
    <div className={`bg-panel border rounded-xl p-4 ${meta.bg}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${meta.color}`} />
          <span className="text-sm font-semibold text-bright">{name}</span>
        </div>
        <span className={`flex items-center gap-1 text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${meta.bg} ${meta.color}`}>
          <StatusIcon className="w-3 h-3" />
          {meta.label}
        </span>
      </div>
      {details.map(({ label, value }) => (
        <div key={label} className="flex justify-between text-xs mt-1">
          <span className="text-muted">{label}</span>
          <span className="text-bright font-mono">{value ?? '—'}</span>
        </div>
      ))}
    </div>
  );
};

const SystemHealth = () => {
  const [health, setHealth]         = useState(null);
  const [metrics, setMetrics]       = useState(null);
  const [sla, setSla]               = useState(null);
  const [observability, setObs]     = useState(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState('');
  const [lastTs, setLastTs]         = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [hRes, mRes, slaRes, obsRes] = await Promise.allSettled([
        api.getHealth(),
        api.client.get('/system/metrics'),
        api.client.get('/health/sla'),
        api.client.get('/health/observability'),
      ]);
      if (hRes.status === 'fulfilled') setHealth(hRes.value.data);
      else setError('Could not reach gateway');
      if (mRes.status === 'fulfilled') setMetrics(mRes.value.data);
      if (slaRes.status === 'fulfilled') setSla(slaRes.value.data);
      if (obsRes.status === 'fulfilled') setObs(obsRes.value.data);
      setLastTs(new Date());
    } catch (e) {
      setError(apiError(e) || 'Failed to load health data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); const iv = setInterval(load, 15_000); return () => clearInterval(iv); }, [load]);

  const overallStatus = health?.status || 'unknown';
  const overallMeta   = getStatus(overallStatus);
  const OverallIcon   = overallMeta.icon;

  const services = [
    {
      name: 'API Gateway', icon: Server, status: health?.status,
      details: [
        { label: 'Version',  value: health?.version },
        { label: 'Uptime',   value: health?.uptime ? `${Math.round(health.uptime / 3600)}h` : null },
        { label: 'Env',      value: health?.env || health?.environment },
      ],
    },
    {
      name: 'Database', icon: Database, status: health?.db || health?.database,
      details: [
        { label: 'Pool size', value: health?.db_pool_size },
        { label: 'Checked',   value: health?.db_checked_at },
      ],
    },
    {
      name: 'Redis / Cache', icon: Zap, status: health?.redis || health?.cache,
      details: [
        { label: 'Used memory', value: metrics?.redis?.used_memory_human },
        { label: 'Clients',     value: metrics?.redis?.connected_clients },
      ],
    },
    {
      name: 'LLM Provider', icon: Cpu, status: health?.llm || health?.provider,
      details: [
        { label: 'Provider', value: health?.active_provider || health?.llm_provider },
        { label: 'Model',    value: health?.active_model },
      ],
    },
    {
      name: 'Sandbox', icon: HardDrive, status: health?.sandbox,
      details: [
        { label: 'Engine', value: health?.sandbox_engine },
        { label: 'Active',  value: health?.active_sandboxes },
      ],
    },
    {
      name: 'Network', icon: Wifi, status: health?.network || health?.status,
      details: [
        { label: 'Latency',  value: metrics?.latency_ms ? `${metrics.latency_ms}ms` : null },
        { label: 'Requests', value: metrics?.requests_total },
      ],
    },
  ];

  const systemMetrics = metrics?.system || {};
  const hasMetrics = Object.keys(systemMetrics).length > 0;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
            <Activity className="w-6 h-6 text-accent" /> System Health
          </h1>
          <p className="text-sm text-muted mt-1">
            Live status of all platform services.
            {lastTs && <span className="ml-2 text-muted/60">Updated {lastTs.toLocaleTimeString()}</span>}
          </p>
        </div>
        <button onClick={load}
          className="flex items-center gap-2 px-4 py-2 bg-surface border border-border rounded-lg text-xs font-bold text-muted hover:text-bright hover:border-accent/40 transition-colors">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {error && (
        <div className="bg-danger/10 border border-danger/30 rounded-xl p-4 text-sm text-danger">{error}</div>
      )}

      {/* Overall status banner */}
      {!loading && health && (
        <div className={`flex items-center gap-4 p-4 border rounded-xl ${overallMeta.bg}`}>
          <OverallIcon className={`w-6 h-6 ${overallMeta.color}`} />
          <div>
            <p className={`text-base font-bold ${overallMeta.color}`}>
              Platform {overallMeta.label}
            </p>
            <p className="text-xs text-muted mt-0.5">All systems are monitored in real time. Auto-refreshes every 15s.</p>
          </div>
          {lastTs && (
            <div className="ml-auto flex items-center gap-1 text-xs text-muted">
              <Clock className="w-3 h-3" />
              {lastTs.toLocaleTimeString()}
            </div>
          )}
        </div>
      )}

      {/* Service cards grid */}
      <div>
        <h2 className="text-xs font-bold text-muted/60 uppercase tracking-widest mb-3">Services</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {loading
            ? Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)
            : services.map((svc) => <ServiceCard key={svc.name} {...svc} />)
          }
        </div>
      </div>

      {/* System resource metrics */}
      {hasMetrics && (
        <div className="bg-panel border border-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-bright mb-4 flex items-center gap-2">
            <MemoryStick className="w-4 h-4 text-accent" /> System Resources
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {systemMetrics.cpu_pct     !== undefined && <MetricBar label="CPU"    value={systemMetrics.cpu_pct}                                  warn={70} crit={90} />}
            {systemMetrics.mem_pct     !== undefined && <MetricBar label="Memory" value={systemMetrics.mem_pct}                                  warn={75} crit={90} />}
            {systemMetrics.disk_pct    !== undefined && <MetricBar label="Disk"   value={systemMetrics.disk_pct}                                 warn={80} crit={95} />}
            {systemMetrics.swap_pct    !== undefined && <MetricBar label="Swap"   value={systemMetrics.swap_pct}                                 warn={50} crit={80} />}
            {systemMetrics.load_1m     !== undefined && <MetricBar label="Load 1m" value={systemMetrics.load_1m} max={systemMetrics.cpu_cores||8} unit="" warn={60} crit={90} />}
            {systemMetrics.load_5m     !== undefined && <MetricBar label="Load 5m" value={systemMetrics.load_5m} max={systemMetrics.cpu_cores||8} unit="" warn={60} crit={90} />}
          </div>
        </div>
      )}

      {/* SLA Metrics */}
      {sla && (
        <div className="bg-panel border border-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-bright mb-4 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-accent" /> SLA Metrics
            <span className="ml-auto text-[10px] font-bold text-muted uppercase tracking-wider">
              Last {sla.window_days}d · {sla.sla_tier} tier · Target: {sla.sla_target}
            </span>
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { label: 'Total Runs', value: sla.total_runs ?? '—' },
              { label: 'Completed', value: sla.completed_runs ?? '—' },
              { label: 'Failed', value: sla.failed_runs ?? '—' },
              {
                label: 'Completion Rate',
                value: sla.completion_rate != null ? `${(sla.completion_rate * 100).toFixed(1)}%` : '—',
              },
            ].map(({ label, value }) => (
              <div key={label} className="space-y-1">
                <div className="text-[10px] font-bold text-muted uppercase tracking-wider">{label}</div>
                <div className="text-lg font-bold text-bright font-mono">{value}</div>
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
            {[
              { label: 'P50 Duration', value: sla.duration_p50_s != null ? `${sla.duration_p50_s}s` : '—' },
              { label: 'P95 Duration', value: sla.duration_p95_s != null ? `${sla.duration_p95_s}s` : '—' },
              {
                label: 'SLA Met',
                value: sla.uptime_sla_met === true ? '✓ Yes' : sla.uptime_sla_met === false ? '✗ No' : '—',
                color: sla.uptime_sla_met === true ? 'text-emerald-400' : sla.uptime_sla_met === false ? 'text-red-400' : 'text-muted',
              },
            ].map(({ label, value, color }) => (
              <div key={label} className="flex justify-between items-center py-2 border-b border-border/30 last:border-0 sm:border-0">
                <span className="text-xs text-muted">{label}</span>
                <span className={`text-xs font-mono font-bold ${color || 'text-bright'}`}>{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Observability */}
      {observability && (
        <div className="bg-panel border border-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-bright mb-4 flex items-center gap-2">
            <Eye className="w-4 h-4 text-accent" /> Observability
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {[
              {
                label: 'LangSmith',
                value: observability.langsmith ?? '—',
                color: observability.langsmith === 'ok' || observability.langsmith === 'healthy' ? 'text-emerald-400'
                     : observability.langsmith === 'disabled' ? 'text-muted' : 'text-red-400',
              },
              { label: 'Traces Today', value: observability.traces_today ?? '—' },
              { label: 'Last Trace ID', value: observability.last_trace_id ? observability.last_trace_id.slice(0, 16) + '…' : '—' },
            ].map(({ label, value, color }) => (
              <div key={label} className="space-y-1">
                <div className="text-[10px] font-bold text-muted uppercase tracking-wider">{label}</div>
                <div className={`text-sm font-bold font-mono ${color || 'text-bright'}`}>{value}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Raw health data toggle */}
      {health && (
        <details className="bg-panel border border-border rounded-xl overflow-hidden">
          <summary className="px-5 py-3 text-xs font-bold text-muted cursor-pointer hover:text-bright transition-colors select-none">
            Raw health payload
          </summary>
          <pre className="px-5 pb-4 text-[11px] text-bright/80 overflow-auto max-h-64 font-mono leading-relaxed">
            {JSON.stringify(health, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
};

export default SystemHealth;
