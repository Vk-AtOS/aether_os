import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { appPath } from '../appUrl';
import { useToast } from '../contexts/useToast';
import {
  Brain, CheckCircle, HelpCircle, Loader2, Star, Trophy,
  TrendingUp, Layers, Sparkles, RefreshCw, ChevronRight,
} from 'lucide-react';
import { apiError } from '../apiError';

const DOMAIN_COLORS = {
  ecommerce: 'text-orange-400 bg-orange-900/20 border-orange-800',
  marketplace: 'text-yellow-400 bg-yellow-900/20 border-yellow-800',
  saas: 'text-blue-400 bg-blue-900/20 border-blue-800',
  healthcare: 'text-green-400 bg-green-900/20 border-green-800',
  fintech: 'text-emerald-400 bg-emerald-900/20 border-emerald-800',
  logistics: 'text-purple-400 bg-purple-900/20 border-purple-800',
  hrtech: 'text-pink-400 bg-pink-900/20 border-pink-800',
  general: 'text-slate-400 bg-slate-900/20 border-slate-700',
};

const domainColor = (d) => DOMAIN_COLORS[d] || DOMAIN_COLORS.general;

const StarDisplay = ({ value, max = 5 }) => (
  <div className="flex items-center gap-0.5">
    {Array.from({ length: max }).map((_, i) => (
      <Star
        key={i}
        className={`w-3.5 h-3.5 ${i < Math.round(value) ? 'text-yellow-400 fill-yellow-400' : 'text-slate-700'}`}
      />
    ))}
    <span className="ml-1 text-xs font-bold text-yellow-400">{(value || 0).toFixed(1)}</span>
  </div>
);

const StatCard = ({ icon: Icon, label, value, sub, color = 'text-accent' }) => (
  <div className="bg-surface border border-border rounded-xl p-4 flex items-start gap-4">
    <div className={`p-2 rounded-lg bg-border/20 ${color}`}>
      <Icon className="w-5 h-5" />
    </div>
    <div>
      <p className="text-2xl font-black text-bright">{value}</p>
      <p className="text-xs font-bold text-muted uppercase tracking-wider">{label}</p>
      {sub && <p className="text-[10px] text-muted mt-0.5">{sub}</p>}
    </div>
  </div>
);

const Learning = () => {
  const [tab, setTab] = useState('overview');
  const [stats, setStats] = useState(null);
  const [goldenBuilds, setGoldenBuilds] = useState([]);
  const [patterns, setPatterns] = useState([]);
  const [clarifications, setClarifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [answers, setAnswers] = useState({});
  const [submitting, setSubmitting] = useState({});
  const toast = useToast();

  const showToast = (msg, type = 'info') => toast(msg, type);

  // Promise chain with no state set before the request: this runs from an effect.
  const load = useCallback(() => Promise.all([
    api.client.get('/learning/stats').catch(() => ({ data: null })),
    api.client.get('/learning/golden-builds').catch(() => ({ data: { golden_builds: [] } })),
    api.client.get('/learning/context').catch(() => ({ data: { patterns: [] } })),
    api.client.get('/learning/clarifications').catch(() => ({ data: { clarifications: [] } })),
  ])
    .then(([statsRes, goldenRes, ctxRes, clrRes]) => {
      setStats(statsRes.data);
      setGoldenBuilds(goldenRes.data?.golden_builds || []);
      const raw = ctxRes.data?.patterns;
      setPatterns(Array.isArray(raw) ? raw : Object.entries(raw || {}).map(([k, v]) => ({ description: typeof v === 'string' ? v : JSON.stringify(v), domain: k })));
      setClarifications(clrRes.data?.clarifications || []);
    })
    .finally(() => setLoading(false)), []);

  useEffect(() => { load(); }, [load]);

  const handleAnswer = async (id) => {
    const answer = answers[id];
    if (!answer?.trim()) return showToast('Please enter an answer', 'error');
    setSubmitting(s => ({ ...s, [id]: true }));
    try {
      await api.client.post(`/learning/clarifications/${id}/answer`, { answer });
      showToast('Answer saved', 'success');
      setClarifications(c => c.filter(q => q.id !== id));
    } catch (e) {
      showToast('Failed: ' + (apiError(e) || e.message), 'error');
    } finally {
      setSubmitting(s => ({ ...s, [id]: false }));
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-muted">
      <Loader2 className="w-6 h-6 animate-spin mr-2" /> Loading learning data…
    </div>
  );

  const tabs = [
    { id: 'overview', label: 'Overview', icon: Brain },
    { id: 'golden', label: 'Golden Builds', icon: Trophy },
    { id: 'patterns', label: 'Patterns', icon: CheckCircle },
    ...(clarifications.length > 0 ? [{ id: 'questions', label: `Questions (${clarifications.length})`, icon: HelpCircle }] : []),
  ];

  return (
    <div className="max-w-5xl mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
            <Brain className="w-6 h-6 text-accent" />
            Self-Improvement Engine
          </h1>
          <p className="text-sm text-muted mt-1">
            AetherOS learns from every build. High-rated apps become golden examples that make future generations better.
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-xs text-muted hover:text-bright border border-border hover:border-accent/40 rounded-lg px-3 py-2 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard icon={Star} label="Total Ratings" value={stats.total_feedback} sub="User feedback collected" color="text-yellow-400" />
          <StatCard icon={Trophy} label="Golden Builds" value={stats.golden_builds} sub="Promoted to few-shot examples" color="text-amber-400" />
          <StatCard icon={TrendingUp} label="Avg Rating" value={`${(stats.avg_rating || 0).toFixed(1)}★`} sub="Across all rated builds" color="text-emerald-400" />
          <StatCard icon={Layers} label="Domains" value={(stats.domain_stats || []).length} sub="With golden examples" color="text-accent" />
        </div>
      )}

      {/* How it works banner */}
      <div className="bg-accent/5 border border-accent/20 rounded-xl p-4 flex items-start gap-4">
        <Sparkles className="w-5 h-5 text-accent shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="text-sm font-bold text-bright">How self-improvement works</p>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
            <span className="flex items-center gap-1"><span className="w-5 h-5 rounded-full bg-accent/20 text-accent text-[10px] font-bold flex items-center justify-center">1</span> You rate a completed build (1–5 stars)</span>
            <ChevronRight className="w-3 h-3 text-muted/40 hidden sm:block self-center" />
            <span className="flex items-center gap-1"><span className="w-5 h-5 rounded-full bg-accent/20 text-accent text-[10px] font-bold flex items-center justify-center">2</span> 4★+ builds are auto-promoted to golden examples</span>
            <ChevronRight className="w-3 h-3 text-muted/40 hidden sm:block self-center" />
            <span className="flex items-center gap-1"><span className="w-5 h-5 rounded-full bg-accent/20 text-accent text-[10px] font-bold flex items-center justify-center">3</span> Future runs inject golden code as LLM few-shot context</span>
            <ChevronRight className="w-3 h-3 text-muted/40 hidden sm:block self-center" />
            <span className="flex items-center gap-1"><span className="w-5 h-5 rounded-full bg-accent/20 text-accent text-[10px] font-bold flex items-center justify-center">4</span> Each generation is better than the last</span>
          </div>
        </div>
      </div>

      {/* Tab nav */}
      <div className="flex gap-1 bg-surface border border-border rounded-xl p-1">
        {tabs.map(t => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-bold transition-colors ${
                tab === t.id ? 'bg-accent text-white' : 'text-muted hover:text-bright hover:bg-white/5'
              }`}
            >
              <Icon className="w-3.5 h-3.5" /> {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab: Overview — domain stats */}
      {tab === 'overview' && (
        <div className="space-y-4">
          {(stats?.domain_stats || []).length === 0 ? (
            <div className="bg-surface border border-border rounded-xl p-10 text-center space-y-3">
              <Brain className="w-12 h-12 text-muted/20 mx-auto" />
              <p className="text-muted text-sm">No golden examples yet.</p>
              <p className="text-xs text-muted">Complete a pipeline run, then rate the build from the project view to start training AetherOS.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {(stats.domain_stats || []).map(ds => (
                <div key={ds.domain} className={`border rounded-xl p-4 space-y-2 ${domainColor(ds.domain)}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider capitalize">{ds.domain}</span>
                    <span className="text-xs font-mono">{ds.count} golden</span>
                  </div>
                  <StarDisplay value={ds.avg_rating} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab: Golden Builds */}
      {tab === 'golden' && (
        <div className="space-y-3">
          {goldenBuilds.length === 0 ? (
            <div className="bg-surface border border-border rounded-xl p-10 text-center space-y-3">
              <Trophy className="w-12 h-12 text-muted/20 mx-auto" />
              <p className="text-muted text-sm">No golden builds yet.</p>
              <p className="text-xs text-muted">Rate a completed build 4★ or higher to promote it as a golden example.</p>
            </div>
          ) : (
            goldenBuilds.map(gb => (
              <div key={gb.id} className="bg-surface border border-border rounded-xl p-4 space-y-2">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <Trophy className="w-3.5 h-3.5 text-amber-400" />
                      <span className="text-sm font-bold text-bright">{gb.project_name}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${domainColor(gb.domain)}`}>
                        {gb.domain}
                      </span>
                    </div>
                    {gb.prompt_summary && (
                      <p className="text-xs text-muted mt-1 line-clamp-2">{gb.prompt_summary}</p>
                    )}
                  </div>
                  <div className="text-right shrink-0 ml-4">
                    {gb.user_rating != null && <StarDisplay value={gb.user_rating} />}
                    {gb.quality_score != null && (
                      <p className="text-[10px] text-muted mt-1">QS: {Math.round(gb.quality_score)}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-4 text-[10px] text-muted">
                  {gb.entity_count != null && <span>{gb.entity_count} entities</span>}
                  {gb.created_at && <span>{new Date(gb.created_at).toLocaleDateString()}</span>}
                  <a href={appPath(`/project/${gb.run_id}`)} className="text-accent hover:underline ml-auto">View run →</a>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Tab: Learned Patterns */}
      {tab === 'patterns' && (
        <div className="space-y-2">
          {patterns.length === 0 ? (
            <div className="bg-surface border border-border rounded-xl p-8 text-center">
              <CheckCircle className="w-10 h-10 text-muted/30 mx-auto mb-3" />
              <p className="text-muted text-sm">No learned patterns yet. Run more pipelines and AetherOS will start personalising results.</p>
            </div>
          ) : (
            patterns.map((p, i) => (
              <div key={i} className="bg-surface border border-border rounded-lg px-4 py-3 flex items-start gap-3">
                <span className="text-xs text-accent font-mono mt-0.5">{String(i + 1).padStart(2, '0')}</span>
                <div className="flex-1">
                  <p className="text-sm text-bright">{typeof p === 'string' ? p : p.description || JSON.stringify(p)}</p>
                  {p.domain && <span className="text-[10px] text-muted">{p.domain}</span>}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Tab: Pending Questions */}
      {tab === 'questions' && clarifications.length > 0 && (
        <div className="space-y-4">
          <p className="text-xs text-muted">Answering these helps AetherOS generate better code for your specific context.</p>
          {clarifications.map(q => (
            <div key={q.id} className="bg-surface border border-border rounded-xl p-4 space-y-3">
              <p className="text-sm text-bright">{q.question}</p>
              {q.context && <p className="text-xs text-muted italic">{q.context}</p>}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={answers[q.id] || ''}
                  onChange={e => setAnswers(a => ({ ...a, [q.id]: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && handleAnswer(q.id)}
                  placeholder="Your answer…"
                  className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                />
                <button
                  onClick={() => handleAnswer(q.id)}
                  disabled={submitting[q.id]}
                  className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-sm font-bold rounded-lg transition-colors"
                >
                  {submitting[q.id] ? '…' : 'Save'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default Learning;
