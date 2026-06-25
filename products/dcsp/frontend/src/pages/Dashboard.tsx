import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CheckCircle2, XCircle, AlertCircle, Clock,
  ArrowUpRight, RefreshCcw, ExternalLink,
  LayoutDashboard, Zap, TrendingUp, Database
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import ReconnectingWebSocket from 'reconnecting-websocket';
import api from '../lib/api';
import { Link } from 'react-router-dom';

interface Job {
  id: string;
  repo_name: string;
  branch?: string;
  error_type?: string;
  explanation?: string;
  status?: string;
  success: boolean;
  escalated: boolean;
  confidence: number;
  timestamp: string;
  detected_language?: string;
  slm_generated?: boolean;
  source?: string;
  sandbox_result?: string;
  approved_pr_url?: string;
}

function statusOf(job: Job) {
  if (job.success)    return { label: 'Patched',   cls: 'text-success bg-success/10 border-success/20',   Icon: CheckCircle2 };
  if (job.escalated)  return { label: 'Escalated', cls: 'text-warning bg-warning/10 border-warning/20',   Icon: AlertCircle };
  return               { label: 'Failed',          cls: 'text-error   bg-error/10   border-error/20',     Icon: XCircle };
}

const LangDot: Record<string, string> = {
  python: 'bg-blue-400', javascript: 'bg-yellow-400', java: 'bg-orange-400', unknown: 'bg-slate-500',
};

const Dashboard = () => {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [filter, setFilter] = useState<'all' | 'patched' | 'escalated' | 'failed'>('all');

  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api.get('/api/stats').then(r => r.data),
    refetchInterval: 30_000,
  });

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.get('/health').then(r => r.data),
    refetchInterval: 15_000,
  });

  useEffect(() => {
    api.get('/api/metrics').then(r => setJobs(r.data.recent_jobs ?? [])).catch(() => {});

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = (import.meta.env.VITE_WS_HOST as string) || window.location.host;
    const ws = new ReconnectingWebSocket(`${proto}://${host}/ws/dashboard`);
    ws.onopen  = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    ws.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.type === 'init') {
        // Merge WS seed jobs with HTTP-loaded jobs; HTTP data is authoritative so
        // we only add WS entries that aren't already present (dedup by id).
        setJobs(prev => {
          const existingIds = new Set(prev.map(j => j.id));
          const newJobs = (d.jobs as Job[]).filter(j => !existingIds.has(j.id));
          return [...prev, ...newJobs].sort((a, b) =>
            new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
          ).slice(0, 100);
        });
      }
      if (d.type === 'new_job') {
        setJobs(prev => {
          if (prev.some(j => j.id === d.job.id)) return prev;
          return [d.job as Job, ...prev].slice(0, 100);
        });
      }
      if (d.type === 'job_updated') setJobs(p => p.map(j => j.id === d.job.id ? d.job : j));
    };
    return () => ws.close();
  }, []);

  const visible = jobs.filter(j => {
    if (filter === 'patched')   return j.success;
    if (filter === 'escalated') return j.escalated;
    if (filter === 'failed')    return !j.success && !j.escalated;
    return true;
  });

  const statCards = [
    { label: 'Jobs Today',       value: stats?.jobs_today ?? 0,                                       icon: LayoutDashboard },
    { label: 'Success Rate',     value: `${((stats?.success_rate ?? 0) * 100).toFixed(1)}%`,          icon: TrendingUp,     cls: 'text-success' },
    { label: 'Avg Repair Time',  value: `${stats?.avg_repair_seconds ?? '—'}s`,                       icon: Clock },
    { label: 'Patterns Learned', value: stats?.patterns_learned ?? 0,                                 icon: Zap,            cls: 'text-accent' },
  ];

  return (
    <div className="space-y-7">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Live Feed</h2>
          <p className="text-slate-500 text-xs mt-0.5">Autonomous CI repair — real-time stream</p>
        </div>
        <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-bold uppercase tracking-wider ${
          wsConnected ? 'border-success/30 bg-success/5 text-success' : 'border-slate-700 bg-slate-800 text-slate-500'
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-success animate-pulse' : 'bg-slate-600'}`} />
          {wsConnected ? 'Connected' : 'Reconnecting'}
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((s, i) => (
          <div key={i} className="bg-surface border border-border rounded-lg p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-slate-500">{s.label}</span>
              <s.icon size={14} className="text-slate-600" />
            </div>
            <div className={`text-2xl font-bold ${s.cls ?? 'text-white'}`}>{s.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Job feed */}
        <div className="xl:col-span-2">
          {/* Filter tabs */}
          <div className="flex items-center gap-1 mb-4">
            {(['all', 'patched', 'escalated', 'failed'] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 rounded text-xs font-semibold capitalize transition-colors ${
                  filter === f ? 'bg-accent/15 text-accent border border-accent/30' : 'text-slate-500 hover:text-white'
                }`}
              >
                {f}
              </button>
            ))}
            <span className="ml-auto text-xs text-slate-600">{visible.length} jobs</span>
          </div>

          <div className="space-y-2.5">
            {visible.map(job => {
              const s = statusOf(job);
              return (
                <Link key={job.id} to={`/feed/jobs/${job.id}`} className="block bg-surface border border-border rounded-lg p-4 hover:border-slate-600 hover:bg-slate-900/40 transition-colors group cursor-pointer">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex gap-3 min-w-0">
                      <div className={`mt-0.5 p-1.5 rounded-md shrink-0 ${s.cls.split(' ').slice(1).join(' ')}`}>
                        <s.Icon size={16} className={s.cls.split(' ')[0]} />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-white font-semibold text-sm truncate">{job.repo_name}</span>
                          {job.branch && <span className="text-slate-600 text-xs">/{job.branch}</span>}
                          {job.detected_language && (
                            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${LangDot[job.detected_language] ?? LangDot.unknown}`} title={job.detected_language} />
                          )}
                        </div>
                        <p className="text-xs text-slate-400 mt-0.5 truncate">
                          {job.explanation ?? job.error_type ?? 'Unknown failure'}
                        </p>
                        <div className="flex items-center gap-3 mt-2 flex-wrap">
                          <span className={`text-[10px] px-2 py-0.5 rounded-full border font-bold ${s.cls}`}>
                            {s.label}
                          </span>
                          <span className="text-[10px] text-slate-500 flex items-center gap-1">
                            <Clock size={10} />
                            {formatDistanceToNow(new Date(job.timestamp))} ago
                          </span>
                          <span className="text-[10px] text-slate-500 flex items-center gap-1">
                            <Zap size={10} className="text-accent" />
                            {Math.round(job.confidence * 100)}%
                          </span>
                          {job.source === 'memory' && (
                            <span className="text-[10px] text-accent/70 font-medium">cached</span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="shrink-0 flex flex-col items-end gap-1.5">
                      <ArrowUpRight size={16} className="text-slate-600 group-hover:text-accent transition-colors" />
                      {job.approved_pr_url && (
                        <a href={job.approved_pr_url} target="_blank" rel="noreferrer"
                          onClick={e => e.stopPropagation()}
                          className="flex items-center gap-1 text-[10px] font-bold text-success hover:underline">
                          PR <ExternalLink size={9} />
                        </a>
                      )}
                    </div>
                  </div>
                </Link>
              );
            })}

            {visible.length === 0 && (
              <div className="bg-surface border border-dashed border-border rounded-lg p-12 text-center">
                <RefreshCcw size={24} className="text-slate-700 mx-auto mb-3" />
                <p className="text-slate-500 text-sm">
                  {filter === 'all' ? 'Waiting for CI webhooks…' : `No ${filter} jobs`}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Right panel */}
        <div className="space-y-4">
          {/* System health */}
          <div className="bg-surface border border-border rounded-lg p-5">
            <h3 className="text-white font-semibold text-sm mb-4 flex items-center gap-2">
              <Database size={14} className="text-slate-500" />
              System Health
            </h3>
            <div className="space-y-3">
              {[
                { label: 'AI Engine',  ok: !!health?.llm_provider },
                { label: 'Database',   ok: health?.database === 'connected' },
                { label: 'Queue',      ok: health?.redis === 'connected' },
                { label: 'Webhooks',   ok: wsConnected },
              ].map(({ label, ok }) => (
                <div key={label} className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">{label}</span>
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${ok ? 'text-success' : 'text-error'}`}>
                    {ok ? 'OK' : 'Down'}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Quick setup prompt if no LLM */}
          {!health?.llm_provider && (
            <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg p-4">
              <p className="text-amber-400 text-xs font-semibold mb-1">AI Engine not configured</p>
              <p className="text-slate-400 text-xs mb-3">Add an API key to start auto-repairing CI failures.</p>
              <Link to="/ai-engine" className="block text-center py-1.5 bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 text-xs font-bold rounded transition-colors">
                Configure now →
              </Link>
            </div>
          )}

          {/* Pipeline explanation card */}
          <div className="bg-surface border border-border rounded-lg p-5">
            <h3 className="text-white font-semibold text-sm mb-3">How it works</h3>
            <ol className="space-y-2.5">
              {[
                'CI fails → webhook received',
                'Log parsed, error localised',
                'AI generates minimal patch',
                'DSEE verifies: boundary, tests, impact',
                'Patch queued for your approval',
                'Approved → PR created automatically',
              ].map((step, i) => (
                <li key={i} className="flex gap-2.5 text-xs text-slate-400">
                  <span className="shrink-0 w-4 h-4 rounded-full bg-slate-800 border border-border text-slate-500 flex items-center justify-center text-[10px] font-bold">
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
