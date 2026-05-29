import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import {
  Shield, ShieldAlert, ShieldCheck, ShieldOff,
  RefreshCw, Loader2, Database, Clock, AlertTriangle,
  CheckCircle2, XCircle, Eye, RotateCcw, Camera,
  Cpu, Server, HardDrive, Wifi, Lock, Unlock, Info, Zap,
} from 'lucide-react';

// ── Threat level config ───────────────────────────────────────────────────────
const THREAT_CONFIG = {
  safe:     { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', ring: 'ring-emerald-500/40', icon: ShieldCheck,  label: 'SAFE',     pulse: false },
  low:      { color: 'text-sky-400',     bg: 'bg-sky-500/10 border-sky-500/30',         ring: 'ring-sky-500/40',     icon: Shield,       label: 'LOW',      pulse: false },
  medium:   { color: 'text-yellow-400',  bg: 'bg-yellow-500/10 border-yellow-500/30',   ring: 'ring-yellow-500/40',  icon: ShieldAlert,  label: 'MEDIUM',   pulse: true  },
  high:     { color: 'text-orange-400',  bg: 'bg-orange-500/10 border-orange-500/30',   ring: 'ring-orange-500/40',  icon: ShieldAlert,  label: 'HIGH',     pulse: true  },
  critical: { color: 'text-red-400',     bg: 'bg-red-500/10 border-red-500/30',         ring: 'ring-red-500/40',     icon: ShieldOff,    label: 'CRITICAL', pulse: true  },
  unknown:  { color: 'text-muted',       bg: 'bg-border/20 border-border',              ring: 'ring-border/40',      icon: Shield,       label: 'UNKNOWN',  pulse: false },
};

const SEV_CONFIG = {
  critical: { color: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/30'    },
  high:     { color: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/30' },
  medium:   { color: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30' },
  low:      { color: 'text-sky-400',    bg: 'bg-sky-500/10',    border: 'border-sky-500/30'    },
};

const EVENT_ICONS = {
  brute_force:   Lock,
  sql_injection: Database,
  rate_breach:   Wifi,
  file_tamper:   HardDrive,
  service_crash: Server,
  anomaly:       AlertTriangle,
  recovery:      RotateCcw,
};

function fmt(iso) {
  if (!iso) return '—';
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' });
}

function fmtBytes(b) {
  if (!b) return '0 B';
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

const ThreatBadge = ({ level }) => {
  const cfg = THREAT_CONFIG[level] || THREAT_CONFIG.unknown;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs font-bold uppercase tracking-wide ${cfg.bg} ${cfg.color} ${cfg.pulse ? 'animate-pulse' : ''}`}>
      <Icon className="w-3.5 h-3.5" />
      {cfg.label}
    </span>
  );
};

const SeverityPill = ({ sev }) => {
  const cfg = SEV_CONFIG[sev] || SEV_CONFIG.low;
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${cfg.bg} ${cfg.border} ${cfg.color}`}>
      {sev}
    </span>
  );
};

const EventRow = ({ event, onResolve }) => {
  const Icon = EVENT_ICONS[event.event_type] || AlertTriangle;
  const cfg = SEV_CONFIG[event.severity] || SEV_CONFIG.low;
  return (
    <div className={`flex items-start gap-3 p-3 rounded-lg border ${event.resolved ? 'opacity-50 border-border/30 bg-transparent' : `${cfg.bg} ${cfg.border}`}`}>
      <div className={`mt-0.5 shrink-0 w-7 h-7 rounded-full flex items-center justify-center ${cfg.bg} border ${cfg.border}`}>
        <Icon className={`w-3.5 h-3.5 ${cfg.color}`} />
      </div>
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-bright capitalize">{event.event_type.replace(/_/g, ' ')}</span>
          <SeverityPill sev={event.severity} />
          {event.resolved && (
            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
              Resolved
            </span>
          )}
        </div>
        {event.source_ip && (
          <p className="text-xs text-muted font-mono">Source: {event.source_ip}</p>
        )}
        {event.detail && (
          <p className="text-xs text-muted truncate">
            {Object.entries(event.detail).map(([k, v]) => `${k}: ${v}`).join(' · ')}
          </p>
        )}
        <p className="text-[11px] text-muted/70">{fmt(event.created_at)}</p>
      </div>
      {!event.resolved && (
        <button
          onClick={() => onResolve(event.id)}
          className="shrink-0 flex items-center gap-1 text-xs text-muted hover:text-emerald-400 transition-colors px-2 py-1 rounded border border-border hover:border-emerald-500/40"
          title="Mark resolved"
        >
          <CheckCircle2 className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Resolve</span>
        </button>
      )}
    </div>
  );
};

const SnapshotRow = ({ snap, onRestore, restoring }) => (
  <div className="flex items-center gap-3 p-3 rounded-lg border border-border bg-panel hover:border-accent/30 transition-colors">
    <Camera className="w-4 h-4 text-muted shrink-0" />
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-mono text-bright truncate">{snap.id.slice(0, 8)}</span>
        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${
          snap.status === 'ok' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' :
          snap.status === 'restored' ? 'bg-sky-500/10 border-sky-500/30 text-sky-400' :
          snap.status === 'restoring' ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400' :
          'bg-red-500/10 border-red-500/30 text-red-400'
        }`}>{snap.status}</span>
        <span className="text-[10px] text-muted capitalize">{snap.trigger}</span>
        <span className="text-[10px] text-muted">{snap.db_backend}</span>
        {!snap.file_exists && (
          <span className="text-[10px] text-red-400">file missing</span>
        )}
      </div>
      <div className="flex items-center gap-3 mt-1">
        <span className="text-xs text-muted">{fmt(snap.created_at)}</span>
        <span className="text-xs text-muted">{fmtBytes(snap.size_bytes)}</span>
        <span className="text-[10px] text-muted/60 font-mono hidden md:inline">{snap.integrity_hash.slice(0, 12)}…</span>
      </div>
      {snap.note && <p className="text-xs text-muted/70 mt-0.5 italic">{snap.note}</p>}
    </div>
    {snap.status === 'ok' && snap.file_exists && (
      <button
        onClick={() => onRestore(snap.id)}
        disabled={restoring}
        className="shrink-0 flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-orange-500/40 text-orange-400 hover:bg-orange-500/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        title="Restore from this snapshot"
      >
        {restoring ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
        <span className="hidden sm:inline">Restore</span>
      </button>
    )}
  </div>
);

// ── Stat counter card ─────────────────────────────────────────────────────────

const StatCard = ({ label, value, sub, color = 'text-bright', icon: Icon, pulse }) => (
  <div className="bg-panel border border-border rounded-xl p-4 space-y-1.5">
    <div className="flex items-center justify-between">
      <span className="text-[10px] text-muted font-bold uppercase tracking-wider">{label}</span>
      {Icon && <Icon className={`w-4 h-4 ${color} ${pulse ? 'animate-pulse' : ''}`} />}
    </div>
    <p className={`text-2xl font-black ${color}`}>{value ?? '—'}</p>
    {sub && <p className="text-[11px] text-muted/70">{sub}</p>}
  </div>
);

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Guardian() {
  const [status, setStatus] = useState(null);
  const [stats, setStats] = useState(null);
  const [events, setEvents] = useState([]);
  const [snapshots, setSnapshots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [snapshotting, setSnapshotting] = useState(false);
  const [restoring, setRestoring] = useState(null);
  const [baselineRefreshing, setBaselineRefreshing] = useState(false);
  const [tab, setTab] = useState('events');
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const [statusRes, statsRes, eventsRes, snapshotsRes] = await Promise.all([
        api.client.get('/guardian/status'),
        api.client.get('/guardian/stats'),
        api.client.get('/guardian/events?limit=50'),
        api.client.get('/guardian/snapshots?limit=20'),
      ]);
      setStatus(statusRes.data);
      setStats(statsRes.data);
      setEvents(eventsRes.data?.items || []);
      setSnapshots(snapshotsRes.data?.snapshots || []);
      setError(null);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const handleResolve = async (id) => {
    try {
      await api.client.post(`/guardian/events/${id}/resolve`);
      setEvents(ev => ev.map(e => e.id === id ? { ...e, resolved: true } : e));
    } catch (e) {
      alert('Failed to resolve: ' + (e.response?.data?.detail || e.message));
    }
  };

  const handleSnapshot = async () => {
    setSnapshotting(true);
    try {
      await api.client.post('/guardian/snapshots', { note: 'Manual snapshot' });
      setTimeout(load, 3000);
    } catch (e) {
      alert('Snapshot failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setSnapshotting(false);
    }
  };

  const handleRestore = async (snapId) => {
    if (!window.confirm('This will restore the database from this snapshot. AetherOS will be briefly unavailable. Continue?')) return;
    setRestoring(snapId);
    try {
      await api.client.post(`/guardian/restore/${snapId}`);
      alert('Restore started. AetherOS will restart. Please wait 30–60 seconds then refresh.');
    } catch (e) {
      alert('Restore failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setRestoring(null);
    }
  };

  const handleBaselineRefresh = async () => {
    if (!window.confirm('Refresh the file integrity baseline? Do this only after a planned code deployment.')) return;
    setBaselineRefreshing(true);
    try {
      const res = await api.client.post('/guardian/baseline/refresh');
      alert(`Baseline refreshed for: ${res.data.refreshed_files.join(', ')}`);
    } catch (e) {
      alert('Failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setBaselineRefreshing(false);
    }
  };

  const cfg = THREAT_CONFIG[status?.threat_level] || THREAT_CONFIG.unknown;
  const Icon = cfg.icon;
  const unresolvedCount = events.filter(e => !e.resolved).length;
  const counts = status?.event_counts_24h || {};

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-accent" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
            <Shield className="w-6 h-6 text-accent" />
            Guardian
          </h1>
          <p className="text-sm text-muted mt-0.5">Autonomous self-monitoring · threat detection · self-healing</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleBaselineRefresh}
            disabled={baselineRefreshing}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-muted hover:text-bright hover:border-accent/40 transition-colors disabled:opacity-50"
            title="Refresh file integrity baseline after a planned deploy"
          >
            {baselineRefreshing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Eye className="w-3.5 h-3.5" />}
            Refresh Baseline
          </button>
          <button
            onClick={handleSnapshot}
            disabled={snapshotting}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-muted hover:text-bright hover:border-accent/40 transition-colors disabled:opacity-50"
          >
            {snapshotting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Camera className="w-3.5 h-3.5" />}
            Snapshot Now
          </button>
          <button
            onClick={load}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-muted hover:text-bright hover:border-accent/40 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-lg border border-red-500/30 bg-red-500/10 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Hero threat card */}
      <div className={`rounded-2xl border p-6 ${cfg.bg} ring-2 ${cfg.ring}`}>
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-4">
            <div className={`w-16 h-16 rounded-2xl flex items-center justify-center ${cfg.bg} border ${cfg.bg.replace('bg-', 'border-').replace('/10', '/40')}`}>
              <Icon className={`w-8 h-8 ${cfg.color} ${cfg.pulse ? 'animate-pulse' : ''}`} />
            </div>
            <div>
              <p className="text-xs text-muted uppercase tracking-widest font-semibold mb-1">Current Threat Level</p>
              <div className="flex items-center gap-3">
                <h2 className={`text-3xl font-black ${cfg.color}`}>{cfg.label}</h2>
                <ThreatBadge level={status?.threat_level || 'unknown'} />
              </div>
              <p className="text-xs text-muted mt-1">
                {unresolvedCount} unresolved event{unresolvedCount !== 1 ? 's' : ''} in last 24h
              </p>
            </div>
          </div>

          {/* Severity breakdown */}
          <div className="grid grid-cols-4 gap-3">
            {['critical', 'high', 'medium', 'low'].map(sev => {
              const c = SEV_CONFIG[sev];
              return (
                <div key={sev} className={`text-center px-4 py-2 rounded-xl border ${c.bg} ${c.border}`}>
                  <p className={`text-2xl font-black ${c.color}`}>{counts[sev] || 0}</p>
                  <p className={`text-[10px] uppercase font-bold ${c.color}`}>{sev}</p>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Real-time prevention stats */}
      {stats && (
        <div>
          <h2 className="text-xs font-bold text-muted uppercase tracking-widest mb-3 flex items-center gap-2">
            <Zap className="w-3.5 h-3.5 text-accent" />
            Threats Prevented — Live Counters
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard
              label="Blocked Today"
              value={stats.threats_blocked_today}
              sub="threats detected & logged"
              color={stats.threats_blocked_today > 0 ? 'text-orange-400' : 'text-emerald-400'}
              icon={ShieldAlert}
              pulse={stats.threats_blocked_today > 0}
            />
            <StatCard
              label="Blocked This Week"
              value={stats.threats_blocked_week}
              sub="rolling 7-day window"
              color="text-bright"
              icon={Shield}
            />
            <StatCard
              label="All-Time Blocked"
              value={stats.threats_blocked_total}
              sub={`${stats.critical_incidents_total} critical incidents`}
              color="text-accent"
              icon={ShieldCheck}
            />
            <StatCard
              label="Auto-Recoveries"
              value={stats.auto_recoveries_performed}
              sub={`${stats.snapshots_available} snapshots ready`}
              color={stats.auto_recoveries_performed > 0 ? 'text-sky-400' : 'text-muted'}
              icon={RotateCcw}
            />
          </div>
          {/* Per-type breakdown */}
          {Object.keys(stats.by_type).length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(stats.by_type)
                .filter(([type]) => type !== 'recovery')
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => {
                  const Icon = EVENT_ICONS[type] || AlertTriangle;
                  return (
                    <div key={type} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-panel text-xs">
                      <Icon className="w-3.5 h-3.5 text-muted" />
                      <span className="text-bright font-bold">{count}</span>
                      <span className="text-muted capitalize">{type.replace(/_/g, ' ')}</span>
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      )}

      {/* Last snapshot card */}
      {status?.last_snapshot && (
        <div className="bg-panel border border-border rounded-xl p-4 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center shrink-0">
            <Camera className="w-4 h-4 text-accent" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs text-muted">Last Clean Snapshot</p>
            <p className="text-sm font-semibold text-bright truncate">
              {fmt(status.last_snapshot.created_at)}
              <span className="text-muted font-normal ml-2 text-xs">
                {fmtBytes(status.last_snapshot.size_bytes)} · {status.last_snapshot.db_backend} · trigger: {status.last_snapshot.trigger}
              </span>
            </p>
          </div>
          <span className="shrink-0 px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
            Ready
          </span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {[
          { key: 'events',    label: `Threats (${unresolvedCount})` },
          { key: 'snapshots', label: `Snapshots (${snapshots.length})` },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? 'border-accent text-accent'
                : 'border-transparent text-muted hover:text-bright'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Events tab */}
      {tab === 'events' && (
        <div className="space-y-2">
          {events.length === 0 ? (
            <div className="text-center py-16">
              <ShieldCheck className="w-12 h-12 text-emerald-400/40 mx-auto mb-3" />
              <p className="text-muted text-sm">No threat events recorded</p>
            </div>
          ) : (
            events.map(e => (
              <EventRow key={e.id} event={e} onResolve={handleResolve} />
            ))
          )}
        </div>
      )}

      {/* Snapshots tab */}
      {tab === 'snapshots' && (
        <div className="space-y-2">
          {snapshots.length === 0 ? (
            <div className="text-center py-16">
              <Camera className="w-12 h-12 text-muted/30 mx-auto mb-3" />
              <p className="text-muted text-sm">No snapshots yet — Guardian will take one automatically within 6 hours, or click "Snapshot Now"</p>
            </div>
          ) : (
            snapshots.map(s => (
              <SnapshotRow
                key={s.id}
                snap={s}
                onRestore={handleRestore}
                restoring={restoring === s.id}
              />
            ))
          )}
        </div>
      )}

      {/* Info footer */}
      <div className="flex items-start gap-2 p-3 rounded-lg border border-border/50 bg-panel/50">
        <Info className="w-4 h-4 text-muted shrink-0 mt-0.5" />
        <p className="text-xs text-muted/70 leading-relaxed">
          Guardian runs automatically — health checks every 30s, file integrity every 5 minutes, scheduled snapshots every 6 hours.
          On a HIGH threat, a pre-threat snapshot is taken automatically. On a CRITICAL service crash or file tamper, auto-recovery
          restores from the last clean snapshot without any manual intervention.
          After a planned code deployment, click "Refresh Baseline" so Guardian doesn't flag the new files as tampering.
        </p>
      </div>

    </div>
  );
}
