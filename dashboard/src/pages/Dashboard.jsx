import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import PhaseBar from '../components/PhaseBar';
import PhaseBadge from '../components/PhaseBadge';
import CostPill from '../components/CostPill';
import { Play, Eye, CheckCircle2, Clock, Coins, AlertTriangle, Info, Zap, Rocket, TrendingUp, Shield, ShieldAlert, ShieldCheck, ShieldOff } from 'lucide-react';
import { useRuns } from '../contexts/RunsContext';
import { useRole } from '../hooks/useRole';
import { useSettings } from '../contexts/SettingsContext';
import { api } from '../api';
import { SkeletonTable } from '../components/Skeleton';
import OnboardingBanner from '../components/OnboardingBanner';

// ── QualityTrendChart — pure SVG, no dependencies ────────────────────────────
const QualityTrendChart = () => {
  const [trendData, setTrendData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getQualityTrend(50)
      .then(r => setTrendData(r.data?.points || []))
      .catch(() => setTrendData([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-8 bg-white/[0.03] rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (!trendData || trendData.length < 1) {
    return (
      <div className="flex flex-col items-center justify-center h-40 space-y-2 text-center">
        <TrendingUp className="w-8 h-8 text-slate-600" />
        <p className="text-slate-500 text-sm">Complete your first run to start tracking build quality.</p>
      </div>
    );
  }

  const W = 600, H = 160, PAD_L = 40, PAD_R = 20, PAD_T = 16, PAD_B = 28;
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;

  const scores = trendData.map(p => p.quality_score);
  const minY = Math.max(0, Math.min(...scores) - 5);
  const maxY = Math.min(100, Math.max(...scores) + 5);
  const rangeY = maxY - minY || 1;

  const xOf = (i) => trendData.length === 1 ? PAD_L + innerW / 2 : PAD_L + (i / (trendData.length - 1)) * innerW;
  const yOf = (v) => PAD_T + innerH - ((v - minY) / rangeY) * innerH;

  const qualityPoints = trendData.map((p, i) => `${xOf(i)},${yOf(p.quality_score)}`).join(' ');

  const compPoints = trendData.filter(p => p.compliance_score != null);
  const hasCompliance = compPoints.length >= 2;
  const compLine = trendData.map((p, i) =>
    p.compliance_score != null ? `${xOf(i)},${yOf(p.compliance_score)}` : null
  ).filter(Boolean).join(' ');

  const first = scores[0];
  const last  = scores[scores.length - 1];
  const delta = last - first;
  const trendColor = delta > 0 ? '#34d399' : delta < 0 ? '#f87171' : '#94a3b8';
  const trendLabel = delta > 0 ? `+${delta} improving` : delta < 0 ? `${delta} declining` : 'stable';

  const gridLines = [0, 25, 50, 75, 100].filter(v => v >= minY && v <= maxY);

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }}>
        {gridLines.map(v => (
          <g key={v}>
            <line x1={PAD_L} y1={yOf(v)} x2={W - PAD_R} y2={yOf(v)} stroke="#ffffff08" strokeWidth="1" />
            <text x={PAD_L - 5} y={yOf(v) + 4} textAnchor="end" fontSize="9" fill="#475569">{v}</text>
          </g>
        ))}
        {hasCompliance && (
          <polyline points={compLine} fill="none" stroke="#7c3aed" strokeWidth="1.5" strokeDasharray="4 3" opacity="0.5" />
        )}
        <polyline points={qualityPoints} fill="none" stroke="#38bdf8" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {trendData.map((p, i) => (
          <circle key={i} cx={xOf(i)} cy={yOf(p.quality_score)} r="3"
            fill={p.quality_score >= 80 ? '#34d399' : p.quality_score >= 60 ? '#fbbf24' : '#f87171'}
            stroke="#050507" strokeWidth="1.5">
            <title>{`${p.project_name}: ${p.quality_score}`}</title>
          </circle>
        ))}
        {[0, Math.floor((trendData.length - 1) / 2), trendData.length - 1].map(i => (
          <text key={i} x={xOf(i)} y={H - 4} textAnchor="middle" fontSize="9" fill="#475569">
            {trendData[i]?.project_name?.slice(0, 10) || ''}
          </text>
        ))}
      </svg>
      <div className="flex items-center gap-4 mt-2 px-1">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-0.5 bg-sky-400" />
          <span className="text-[10px] text-slate-500">Quality Score</span>
        </div>
        {hasCompliance && (
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-0.5 bg-violet-400 opacity-60" style={{ borderTop: '1.5px dashed #7c3aed' }} />
            <span className="text-[10px] text-slate-500">Compliance Score</span>
          </div>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <TrendingUp className="w-3 h-3" style={{ color: trendColor }} />
          <span className="text-[10px] font-bold" style={{ color: trendColor }}>
            {trendData.length === 1 ? `First build: ${scores[0]}/100` : `${trendLabel} over last ${trendData.length} builds`}
          </span>
        </div>
      </div>
    </div>
  );
};

// ── Guardian mini-widget ─────────────────────────────────────────────────────
const THREAT_ICONS = { safe: ShieldCheck, low: Shield, medium: ShieldAlert, high: ShieldAlert, critical: ShieldOff };
const THREAT_STYLES = {
  safe:     'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  low:      'text-sky-400     bg-sky-500/10     border-sky-500/20',
  medium:   'text-yellow-400  bg-yellow-500/10  border-yellow-500/20',
  high:     'text-orange-400  bg-orange-500/10  border-orange-500/20',
  critical: 'text-red-400     bg-red-500/10     border-red-500/20',
};

const GuardianWidget = () => {
  const [data, setData] = useState(null);
  useEffect(() => {
    const load = () => {
      Promise.all([
        api.client.get('/guardian/status').catch(() => null),
        api.client.get('/guardian/stats').catch(() => null),
      ]).then(([s, st]) => {
        if (s || st) setData({ status: s?.data, stats: st?.data });
      });
    };
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  if (!data) return null;
  const level = data.status?.threat_level || 'unknown';
  const Icon = THREAT_ICONS[level] || Shield;
  const style = THREAT_STYLES[level] || 'text-slate-400 bg-white/[0.04] border-white/[0.06]';
  const today = data.stats?.threats_blocked_today ?? 0;
  const total = data.stats?.threats_blocked_total ?? 0;

  return (
    <Link to="/guardian" className={`flex items-center gap-3 p-4 rounded-2xl border transition-all hover:opacity-90 hover:-translate-y-0.5 ${style}`}>
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center border ${style}`}>
        <Icon className={`w-4 h-4 ${level === 'critical' || level === 'high' ? 'animate-pulse' : ''}`} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-widest">Guardian</span>
          <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${style}`}>{level}</span>
        </div>
        <p className="text-[11px] mt-0.5 opacity-80">
          {today > 0 ? `${today} threat${today !== 1 ? 's' : ''} blocked today` : 'No threats today'}
          {total > 0 && <span className="ml-1 opacity-60">· {total} total</span>}
        </p>
      </div>
    </Link>
  );
};

const TrialBanner = () => {
  const [usage, setUsage] = useState(null);
  useEffect(() => {
    api.client.get('/account/usage').then(r => setUsage(r.data)).catch(() => {});
  }, []);
  if (!usage || usage.plan !== 'trial') return null;
  const remaining = usage.runs_remaining ?? (usage.runs_limit - usage.runs_used);
  const pct = Math.round(((usage.runs_limit - remaining) / usage.runs_limit) * 100);
  return (
    <div className="bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4 flex items-center gap-4">
      <Rocket className="w-5 h-5 text-amber-400 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-bold text-amber-300">
          Trial — {remaining} run{remaining !== 1 ? 's' : ''} remaining
        </p>
        <div className="flex items-center gap-2 mt-1.5">
          <div className="flex-1 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-amber-400 to-orange-400 rounded-full transition-all" style={{ width: `${pct}%` }} />
          </div>
          <span className="text-[10px] text-slate-500">{usage.runs_used}/{usage.runs_limit} used</span>
        </div>
      </div>
      <Link to="/pricing"
        className="shrink-0 text-xs font-bold bg-amber-500 hover:bg-amber-400 text-black px-4 py-2 rounded-xl transition-colors">
        Upgrade
      </Link>
    </div>
  );
};

// Stat card component
const StatCard = ({ label, value, icon: Icon, iconBg }) => (
  <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-6 hover:border-white/[0.12] hover:bg-white/[0.03] transition-all duration-300 group">
    <div className="flex items-center justify-between mb-4">
      <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">{label}</span>
      <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${iconBg} flex items-center justify-center group-hover:scale-110 transition-transform duration-300`}>
        <Icon className="w-4 h-4 text-white" />
      </div>
    </div>
    <div className="text-3xl font-bold text-white mb-1">{value}</div>
  </div>
);

const Dashboard = () => {
  const navigate = useNavigate();
  const { runs, costs, health, loading } = useRuns();
  const { isAdmin, isViewer, userId } = useRole();
  const [killing, setKilling] = useState(false);
  const [killResult, setKillResult] = useState(null);
  const [hasApiKey, setHasApiKey] = useState(false);
  const [confirmKillAll, setConfirmKillAll] = useState(false);
  const [killOpen, setKillOpen] = useState(false);

  useEffect(() => {
    api.client.get('/settings/api-keys').then(res => {
      const keys = res.data ?? {};
      setHasApiKey(Object.values(keys).some(v => v));
    }).catch(() => {});
  }, []);

  const visibleRuns = isAdmin
    ? runs
    : runs.filter(r => !userId || r.user_id === userId || r.created_by === userId);

  const activeRuns = visibleRuns.filter(r => r.status === 'running' || r.status === 'RUNNING');

  const completedToday = visibleRuns.filter(r => {
    if (!r.started_at) return false;
    const started = new Date(r.started_at);
    const today = new Date();
    return started.toDateString() === today.toDateString() && (r.status === 'PASSED' || r.status === 'passed' || r.status === 'completed');
  }).length;

  const stats = [
    { label: 'Active Runs', value: activeRuns.length, icon: Play, iconBg: 'from-violet-600 to-violet-500' },
    { label: 'Completed Today', value: completedToday, icon: CheckCircle2, iconBg: 'from-emerald-600 to-emerald-500' },
    { label: 'Total Cost Today', value: `$${costs.today_usd?.toFixed(2) || '0.00'}`, icon: Clock, iconBg: 'from-amber-600 to-amber-500' },
    { label: 'Tokens (Month)', value: costs.tokens_today != null ? costs.tokens_today.toLocaleString() : '—', icon: Coins, iconBg: 'from-indigo-600 to-indigo-500' },
  ];

  const noLLM = health && !health.anthropic_available && !health.gemini_available && !health.ollama_available && !health.openrouter_available;
  const onlyOllama = health && !health.anthropic_available && !health.gemini_available && !health.openrouter_available && health.ollama_available;

  const handleKillAll = async () => {
    if (!confirmKillAll) { setConfirmKillAll(true); return; }
    setConfirmKillAll(false);
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
    <div className="space-y-6">
      {/* Trial banner */}
      <TrialBanner />

      {/* Onboarding banner */}
      {!loading && runs.length === 0 && <OnboardingBanner hasRuns={false} hasApiKey={hasApiKey} />}

      {/* Admin kill switch — collapsed by default, expand on demand */}
      {isAdmin && (
        <div className={`border rounded-2xl transition-all duration-300 ${
          activeRuns.length > 0 || killOpen
            ? 'border-red-500/30 bg-red-500/5'
            : 'border-white/[0.06] bg-white/[0.02]'
        }`}>
          <button
            onClick={() => setKillOpen(v => !v)}
            className="w-full flex items-center gap-3 px-5 py-3.5 text-left"
          >
            <Zap className={`w-4 h-4 ${activeRuns.length > 0 ? 'text-red-400' : 'text-slate-500'}`} />
            <span className={`text-xs font-bold uppercase tracking-wider ${activeRuns.length > 0 ? 'text-red-400' : 'text-slate-500'}`}>
              Emergency Kill Switch
            </span>
            {activeRuns.length > 0 && (
              <span className="ml-2 bg-red-500/20 border border-red-500/30 text-red-400 text-[10px] font-bold px-2 py-0.5 rounded-full">
                {activeRuns.length} active
              </span>
            )}
            {killResult && (
              <span className={`ml-2 text-xs font-medium ${killResult.ok ? 'text-emerald-400' : 'text-red-400'}`}>
                {killResult.ok ? `✓ Stopped ${killResult.count} run(s)` : `✗ ${killResult.msg}`}
              </span>
            )}
            <span className="ml-auto text-slate-600 text-xs">{killOpen ? '▲' : '▼'}</span>
          </button>
          {killOpen && (
            <div className="px-5 pb-4 flex items-center justify-end gap-3 border-t border-white/[0.06] pt-3">
              {confirmKillAll ? (
                <>
                  <span className="text-xs text-red-400 font-bold">Are you sure? This stops ALL runs.</span>
                  <button onClick={handleKillAll} disabled={killing}
                    className="bg-red-600 hover:bg-red-500 text-white text-xs font-bold px-4 py-2 rounded-xl transition-colors disabled:opacity-50">
                    {killing ? 'Stopping…' : 'Confirm Kill All'}
                  </button>
                  <button onClick={() => setConfirmKillAll(false)} className="text-xs text-slate-500 hover:text-white px-2 py-1 rounded-lg">
                    Cancel
                  </button>
                </>
              ) : (
                <button onClick={handleKillAll} disabled={killing}
                  className="bg-red-500/20 hover:bg-red-500/40 text-red-400 border border-red-500/30 text-xs font-bold px-4 py-2 rounded-xl transition-all disabled:opacity-50">
                  {killing ? 'Stopping…' : 'Kill All Runs'}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {noLLM && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-2xl p-4 flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-red-500/20 border border-red-500/30 flex items-center justify-center flex-shrink-0">
            <AlertTriangle className="w-5 h-5 text-red-400" />
          </div>
          <div className="flex-1">
            <div className="text-red-300 font-bold text-sm mb-0.5">No LLM Configured</div>
            <div className="text-red-400/80 text-xs">
              Factory pipelines will fail. Add an API key in Settings or configure Ollama.
            </div>
          </div>
          {!isViewer && (
            <button onClick={() => navigate('/settings')}
              className="shrink-0 px-4 py-2 bg-red-600 hover:bg-red-500 text-white text-xs font-bold rounded-xl transition-colors">
              Fix in Settings
            </button>
          )}
        </div>
      )}

      {onlyOllama && (
        <div className="bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4 flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center flex-shrink-0">
            <Info className="w-5 h-5 text-amber-400" />
          </div>
          <div className="flex-1">
            <div className="text-amber-300 font-bold text-sm mb-0.5">Running on Ollama (Local)</div>
            <div className="text-amber-400/80 text-xs">
              Processing may be slow. Cloud API keys are recommended for production speeds.
            </div>
          </div>
          {!isViewer && (
            <button onClick={() => navigate('/settings')}
              className="shrink-0 px-4 py-2 bg-amber-500/30 hover:bg-amber-500/50 border border-amber-500/30 text-amber-300 text-xs font-bold rounded-xl transition-colors">
              Upgrade Provider
            </button>
          )}
        </div>
      )}

      {/* Guardian widget */}
      <GuardianWidget />

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => (
          <StatCard key={stat.label} {...stat} />
        ))}
      </div>

      {/* Active runs table */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold text-white">
            {isAdmin ? 'Active Factory Runs' : 'My Active Runs'}
          </h3>
          {!isViewer && (
            <button
              onClick={() => navigate('/new')}
              className="flex items-center gap-1.5 bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 text-white text-xs font-semibold px-4 py-2 rounded-xl transition-all shadow-md shadow-violet-500/20"
            >
              <Play className="w-3.5 h-3.5" /> New Pipeline
            </button>
          )}
        </div>

        <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-white/[0.06]">
                <th className="px-6 py-3.5 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Project</th>
                <th className="px-6 py-3.5 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Status</th>
                <th className="px-6 py-3.5 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Phase Progress</th>
                <th className="px-6 py-3.5 text-[10px] font-bold text-slate-500 uppercase tracking-widest text-right">Cost</th>
                <th className="px-6 py-3.5 text-[10px] font-bold text-slate-500 uppercase tracking-widest text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {activeRuns.map((run) => (
                <tr key={run.run_id || run.id} className="hover:bg-white/[0.02] transition-colors">
                  <td className="px-6 py-4">
                    <button onClick={() => navigate(`/project/${run.run_id || run.id}`)} className="text-left group">
                      <div className="font-semibold text-white group-hover:text-violet-300 transition-colors">{run.project_name || 'Untitled Project'}</div>
                      <div className="text-[10px] text-slate-600 font-mono mt-0.5">{(run.run_id || run.id || '').slice(0, 8)}</div>
                    </button>
                  </td>
                  <td className="px-6 py-4">
                    <PhaseBadge status={run.status} />
                    <div className="text-[10px] text-slate-600 font-mono mt-1">{run.current_phase || 'Initializing'}</div>
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
                      className="p-2 text-slate-500 hover:text-violet-400 hover:bg-violet-500/10 rounded-lg transition-all"
                      title="View Details"
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {activeRuns.length === 0 && !loading && (
                <tr>
                  <td colSpan="5" className="py-20 text-center">
                    <div className="w-16 h-16 rounded-2xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center mx-auto mb-4 text-3xl">⚡</div>
                    <h3 className="text-white font-semibold text-base mb-2">No active runs</h3>
                    <p className="text-slate-500 text-sm mb-6 max-w-xs mx-auto">
                      {isViewer ? 'No active runs to display.' : 'Start your first factory run to generate a production application.'}
                    </p>
                    {!isViewer && (
                      <button
                        onClick={() => navigate('/new')}
                        className="bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 text-white px-6 py-2.5 rounded-xl font-medium text-sm transition-all shadow-lg shadow-violet-500/25">
                        New Pipeline →
                      </button>
                    )}
                  </td>
                </tr>
              )}
              {loading && Array.from({ length: 3 }).map((_, i) => (
                <tr key={i} className="border-b border-white/[0.04]">
                  {Array.from({ length: 5 }).map((_, j) => (
                    <td key={j} className="px-6 py-4">
                      <div className="h-4 bg-white/[0.04] rounded-lg animate-pulse" style={{ width: `${55 + j * 10}%` }} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Build Quality Trend */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-violet-400" />
            <h3 className="text-base font-bold text-white">Build Quality Trend</h3>
          </div>
          <span className="text-[10px] text-slate-600 uppercase tracking-wider font-bold">Cross-run Learning</span>
        </div>
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-5">
          <p className="text-xs text-slate-600 mb-4">
            Every build contributes to AetherOS&apos;s learning pool — watch quality scores improve as the system learns from each project.
          </p>
          <QualityTrendChart />
        </div>
      </section>
    </div>
  );
};

export default Dashboard;
