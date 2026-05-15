import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import PhaseBar from '../components/PhaseBar';
import PhaseBadge from '../components/PhaseBadge';
import CostPill from '../components/CostPill';
import { Play, Eye, CheckCircle2, Clock, Coins, AlertTriangle, Info, Zap } from 'lucide-react';
import { useRuns } from '../contexts/RunsContext';
import { useRole } from '../hooks/useRole';
import { api } from '../api';
import { SkeletonTable } from '../components/Skeleton';
import OnboardingBanner from '../components/OnboardingBanner';

const Dashboard = () => {
  const navigate = useNavigate();
  const { runs, costs, health, loading } = useRuns();
  const { isAdmin, isViewer, userId } = useRole();
  const [killing, setKilling] = useState(false);
  const [killResult, setKillResult] = useState(null);
  const [hasApiKey, setHasApiKey] = useState(false);

  useEffect(() => {
    api.client.get('/settings/api-keys').then(res => {
      const keys = res.data ?? {};
      setHasApiKey(Object.values(keys).some(v => v));
    }).catch(() => {});
  }, []);

  // Members/viewers see only their own runs; admins/owners see all
  const visibleRuns = isAdmin
    ? runs
    : runs.filter(r => !userId || r.user_id === userId || r.created_by === userId);

  const activeRuns = visibleRuns.filter(r => r.status === 'running' || r.status === 'RUNNING');

  const stats = [
    { label: 'Active Runs', value: activeRuns.length, icon: Play, color: 'text-accent' },
    { label: 'Completed Today', value: visibleRuns.filter(r => {
        if (!r.started_at) return false;
        const started = new Date(r.started_at);
        const today = new Date();
        return started.toDateString() === today.toDateString() && (r.status === 'PASSED' || r.status === 'passed' || r.status === 'completed');
      }).length, icon: CheckCircle2, color: 'text-success' },
    { label: 'Total Cost Today', value: `$${costs.today_usd?.toFixed(2) || '0.00'}`, icon: Clock, color: 'text-warning' },
    { label: 'Tokens Today', value: costs.tokens_today || '—', icon: Coins, color: 'text-success' },
  ];

  const noLLM = health && !health.anthropic_available && !health.gemini_available && !health.ollama_available;
  const onlyOllama = health && !health.anthropic_available && !health.gemini_available && health.ollama_available;

  const handleKillAll = async () => {
    if (!window.confirm('Emergency stop: kill ALL active pipeline runs for this organisation? This cannot be undone.')) return;
    setKilling(true);
    setKillResult(null);
    try {
      const res = await api.client.post('/admin/kill-all');
      setKillResult({ ok: true, count: res.data?.killed_count ?? 0 });
    } catch (e) {
      setKillResult({ ok: false, msg: e.response?.data?.detail || 'Kill-all failed.' });
    } finally {
      setKilling(false);
      setTimeout(() => setKillResult(null), 5000);
    }
  };

  return (
    <div className="space-y-8">
      {/* Onboarding banner — shown to new users until steps complete */}
      {!loading && runs.length === 0 && <OnboardingBanner hasRuns={false} hasApiKey={hasApiKey} />}

      {/* Admin kill switch */}
      {isAdmin && (
        <div className="flex items-center justify-between p-4 bg-danger/5 border border-danger/20 rounded-lg">
          <div className="flex items-center gap-3">
            <Zap className="w-4 h-4 text-danger" />
            <div>
              <span className="text-xs font-bold text-danger uppercase tracking-wider">Emergency Kill Switch</span>
              {killResult && (
                <span className={`ml-3 text-xs font-medium ${killResult.ok ? 'text-success' : 'text-danger'}`}>
                  {killResult.ok ? `✓ Stopped ${killResult.count} run(s)` : `✗ ${killResult.msg}`}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={handleKillAll}
            disabled={killing}
            className="bg-danger/20 hover:bg-danger/40 text-danger border border-danger/30 disabled:opacity-50 text-[10px] font-bold px-4 py-2 rounded-lg transition-colors uppercase tracking-wider"
          >
            {killing ? 'Stopping…' : 'Kill All Runs'}
          </button>
        </div>
      )}

      {noLLM && (
        <div className="bg-red-900/20 border border-red-600/50 rounded-lg p-4 flex items-center gap-4 animate-in fade-in slide-in-from-top-4 duration-500">
          <div className="bg-red-600 p-2 rounded-full">
            <AlertTriangle className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="text-red-200 font-bold uppercase tracking-wider text-xs">Critical: No LLM Configured</div>
            <div className="text-red-400 text-sm mt-0.5">
              Factory pipelines will fail immediately. Add an API key in Settings or configure a local Ollama instance.
            </div>
          </div>
          {!isViewer && (
            <button
              onClick={() => navigate('/settings')}
              className="ml-auto px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-xs font-bold rounded-lg transition-colors"
            >
              FIX IN SETTINGS
            </button>
          )}
        </div>
      )}

      {onlyOllama && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-4">
          <div className="bg-yellow-600 p-2 rounded-full">
            <Info className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="text-yellow-200 font-bold uppercase tracking-wider text-xs">Running on Ollama (Local)</div>
            <div className="text-yellow-400 text-sm mt-0.5">
              Processing may be slow depending on your local hardware. Cloud API keys are recommended for production speeds.
            </div>
          </div>
          {!isViewer && (
            <button
              onClick={() => navigate('/settings')}
              className="ml-auto px-4 py-2 bg-yellow-600/50 hover:bg-yellow-600 text-white text-xs font-bold rounded-lg transition-colors border border-yellow-600/30"
            >
              UPGRADE PROVIDER
            </button>
          )}
        </div>
      )}

      <div className="grid grid-cols-4 gap-6">
        {stats.map((stat) => (
          <div key={stat.label} className="panel p-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold text-muted uppercase tracking-wider">{stat.label}</span>
              <stat.icon className={`w-5 h-5 ${stat.color}`} />
            </div>
            <div className="text-2xl font-bold text-bright">{stat.value}</div>
          </div>
        ))}
      </div>

      <section>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold">
            {isAdmin ? 'Active Factory Runs' : 'My Active Runs'}
          </h3>
          {!isViewer && (
            <button
              onClick={() => navigate('/new-project')}
              className="bg-accent hover:bg-accent/90 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors flex items-center"
            >
              <Play className="w-3.5 h-3.5 mr-2" /> NEW PIPELINE
            </button>
          )}
        </div>

        <div className="panel overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-border/20 text-xs font-bold text-muted uppercase tracking-widest border-b border-border">
                <th className="px-6 py-4">Project</th>
                <th className="px-6 py-4">Status</th>
                <th className="px-6 py-4">Phase Progress</th>
                <th className="px-6 py-4 text-right">Cost</th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {activeRuns.map((run) => (
                <tr key={run.run_id || run.id} className="hover:bg-border/10 transition-colors">
                  <td className="px-6 py-4">
                    <button
                      onClick={() => navigate(`/project/${run.run_id || run.id}`)}
                      className="text-left group"
                    >
                      <div className="font-bold text-bright group-hover:text-accent transition-colors">{run.project_name || 'Untitled Project'}</div>
                      <div className="text-[10px] text-muted font-mono uppercase mt-0.5">{run.run_id || run.id}</div>
                    </button>
                  </td>
                  <td className="px-6 py-4">
                    <PhaseBadge status={run.status} />
                    <div className="text-[10px] text-muted font-mono mt-1 uppercase">Current: {run.current_phase || 'Initializing'}</div>
                  </td>
                  <td className="px-6 py-4 min-w-[200px]">
                    <PhaseBar phases={run.phases} />
                  </td>
                  <td className="px-6 py-4 text-right">
                    <CostPill cost={run.cost ?? 0} />
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => navigate(`/project/${run.run_id || run.id}`)}
                      className="p-2 text-muted hover:text-accent transition-colors"
                      title="View Details"
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {activeRuns.length === 0 && !loading && (
                <tr>
                  <td colSpan="5" className="px-6 py-12 text-center text-muted">
                    {isViewer ? 'No active runs to display.' : 'No active runs found. Start a new pipeline to begin.'}
                  </td>
                </tr>
              )}
              {loading && Array.from({ length: 3 }).map((_, i) => (
                <tr key={i} className="border-b border-border">
                  {Array.from({ length: 5 }).map((_, j) => (
                    <td key={j} className="px-6 py-4">
                      <div className="h-4 bg-border/40 rounded animate-pulse" style={{ width: `${55 + j * 10}%` }} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};

export default Dashboard;
