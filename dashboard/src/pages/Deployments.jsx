import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { Rocket, Loader2, RefreshCw, ExternalLink, Clock, CheckCircle2, AlertTriangle, XCircle, Globe, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { confirmAction } from '../components/confirmAction';

const STATUS_META = {
  deployed:   { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', icon: CheckCircle2 },
  completed:  { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', icon: CheckCircle2 },
  running:    { color: 'text-accent', bg: 'bg-accent/10 border-accent/30', icon: Loader2 },
  deploying:  { color: 'text-accent', bg: 'bg-accent/10 border-accent/30', icon: Loader2 },
  failed:     { color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30', icon: XCircle },
  pending:    { color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/30', icon: AlertTriangle },
};

const SkeletonRow = () => (
  <div className="animate-pulse flex items-center gap-4 p-4 border border-border rounded-xl">
    <div className="w-8 h-8 bg-border/40 rounded-lg" />
    <div className="flex-1 space-y-2">
      <div className="h-3.5 bg-border/40 rounded w-1/3" />
      <div className="h-2.5 bg-border/30 rounded w-1/2" />
    </div>
    <div className="w-20 h-6 bg-border/30 rounded-full" />
  </div>
);

const Deployments = () => {
  const [deployments, setDeployments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [undeploying, setUndeploying] = useState({});
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.listDeployments();
      const data = res.data;
      const items = Array.isArray(data) ? data : (data?.items || data?.deployments || []);
      setDeployments(items);
      // The preview is only served to a browser holding that run's preview cookie,
      // which the status call issues. Fetch it now so the "open" links work.
      items.filter((d) => d.run_id).forEach((d) => api.getRunAppStatus(d.run_id).catch(() => {}));
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load deployments');
    } finally {
      setLoading(false);
    }
  };

  const handleUndeploy = async (runId, e) => {
    e.preventDefault();
    if (!(await confirmAction('Stop this deployed app?'))) return;
    setUndeploying(p => ({ ...p, [runId]: true }));
    try {
      await api.stopDeploy(runId);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || 'Undeploy failed');
    } finally {
      setUndeploying(p => ({ ...p, [runId]: false }));
    }
  };

  useEffect(() => {
    load();
    const interval = setInterval(() => {
      setDeployments(prev => {
        const hasActive = prev.some(d => d.status === 'deploying' || d.status === 'running');
        if (hasActive) load();
        return prev;
      });
    }, 8000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
            <Rocket className="w-6 h-6 text-accent" /> Deployments
          </h1>
          <p className="text-sm text-muted mt-1">All deployed applications from your factory runs.</p>
        </div>
        <button onClick={load}
          className="flex items-center gap-2 px-4 py-2 bg-surface border border-border rounded-lg text-xs font-bold text-muted hover:text-bright hover:border-accent/40 transition-colors">
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {error && (
        <div className="bg-danger/10 border border-danger/30 rounded-xl p-4 text-sm text-danger">{error}</div>
      )}

      <div className="space-y-3">
        {loading
          ? Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} />)
          : deployments.length === 0
            ? (
              <div className="text-center py-20 border border-border rounded-xl bg-panel">
                <Rocket className="w-10 h-10 mx-auto text-muted/30 mb-3" />
                <p className="text-muted text-sm">No deployments yet.</p>
                <p className="text-xs text-muted/60 mt-1">Deploy a completed run to see it here.</p>
                <button onClick={() => navigate('/projects')}
                  className="mt-4 text-xs font-bold text-accent hover:underline">
                  View runs →
                </button>
              </div>
            )
            : deployments.map((dep, i) => {
              const meta = STATUS_META[dep.status] || STATUS_META.pending;
              const Icon = meta.icon;
              const ts = dep.started_at ? new Date(dep.started_at * 1000).toLocaleString() : (dep.deployed_at ? new Date(dep.deployed_at * 1000).toLocaleString() : '—');
              // Prefer the gateway proxy URL over raw docker port
              const appUrl = dep.run_id
                ? `/generated-app/${dep.run_id}/`
                : (dep.url || dep.live_url || null);
              const isSpinning = dep.status === 'deploying' || dep.status === 'running';
              return (
                <div key={dep.id || dep.run_id || i}
                  className="bg-panel border border-border hover:border-accent/30 rounded-xl p-4 transition-all">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-lg bg-surface border border-border flex items-center justify-center shrink-0">
                      <Globe className="w-5 h-5 text-accent" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <button onClick={() => navigate(`/project/${dep.run_id}`)}
                          className="text-sm font-semibold text-bright hover:text-accent transition-colors truncate">
                          {dep.project_name || dep.run_id?.substring(0, 8)}
                        </button>
                        <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${meta.bg} ${meta.color}`}>
                          <Icon className={`w-3 h-3 inline mr-0.5 ${isSpinning ? 'animate-spin' : ''}`} />
                          {dep.status}
                        </span>
                        {dep.domain && (
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/10 border border-indigo-500/30 text-indigo-400 font-medium">
                            {dep.domain}
                          </span>
                        )}
                        {dep.proc_status === 'running' && (
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-500/10 border border-green-500/30 text-green-400 font-medium">
                            live
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-[10px] text-muted flex-wrap">
                        <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{ts}</span>
                        {dep.run_id && <span className="font-mono opacity-60">{dep.run_id.substring(0, 8)}</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {appUrl && (
                        <a href={appUrl} target="_blank" rel="noopener noreferrer"
                          className="shrink-0 flex items-center gap-1.5 text-xs font-bold text-accent hover:text-accent/80 transition-colors border border-accent/30 rounded-lg px-3 py-1.5">
                          <ExternalLink className="w-3 h-3" /> Open App
                        </a>
                      )}
                      {dep.run_id && (dep.status === 'deployed' || dep.status === 'completed' || dep.proc_status === 'running') && (
                        <button
                          onClick={(e) => handleUndeploy(dep.run_id, e)}
                          disabled={undeploying[dep.run_id]}
                          className="shrink-0 flex items-center gap-1.5 text-xs font-bold text-danger hover:text-danger/80 transition-colors border border-danger/30 rounded-lg px-3 py-1.5 hover:bg-danger/10 disabled:opacity-50"
                        >
                          {undeploying[dep.run_id] ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                          Undeploy
                        </button>
                      )}
                    </div>
                  </div>
                  {dep.error && (
                    <div className="mt-3 bg-danger/10 border border-danger/20 rounded-lg px-3 py-2 text-xs text-danger">
                      {dep.error}
                    </div>
                  )}
                </div>
              );
            })}
      </div>
    </div>
  );
};

export default Deployments;
