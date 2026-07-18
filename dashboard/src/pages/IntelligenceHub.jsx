import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import {
  Sparkles, RefreshCw, CheckCircle2, Lightbulb,
  TrendingUp, Shield, Scale, Brain, GitMerge, Wrench, RotateCcw,
} from 'lucide-react';
import {
  normPct, ScoreBadge, Card, InsightItem, ExpandableSection, ToolCard,
  ConflictResolverTool, MaintenanceEngineTool, ImprovementLoopTool,
} from '../components/intelligence/IntelligenceTools';

const ANALYSIS_TIMEOUT_MS = 20000;

const withTimeout = (promise, ms) =>
  Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('Analysis timed out — click Refresh to retry')), ms)),
  ]);

const IntelligenceHub = () => {
  const [insights, setInsights]         = useState(null);
  const [benchmark, setBenchmark]       = useState(null);
  const [archReview, setArchReview]     = useState(null);
  const [tradeoff, setTradeoff]         = useState(null);
  const [truth, setTruth]               = useState(null);
  const [errors, setErrors]             = useState({});
  const [loading, setLoading]           = useState({});
  const [analysisRun, setAnalysisRun]   = useState(false);
  const [lastRefresh, setLastRefresh]   = useState(null);

  const setL = (key, v) => setLoading(p => ({ ...p, [key]: v }));
  const setE = (key, v) => setErrors(p => ({ ...p, [key]: v }));

  const loadGets = useCallback(() => {
    setLastRefresh(new Date());

    setL('insights', true);
    api.client.get('/intelligence/global-insights')
      .then(r => setInsights(r.data))
      .catch(e => setE('insights', e.response?.data?.detail || 'Failed to load insights'))
      .finally(() => setL('insights', false));

    setL('benchmark', true);
    api.client.get('/intelligence/quality-benchmark')
      .then(r => setBenchmark(r.data))
      .catch(e => setE('benchmark', e.response?.data?.detail || 'Failed to load benchmark'))
      .finally(() => setL('benchmark', false));
  }, []);

  const runAnalysis = useCallback(() => {
    setAnalysisRun(true);
    setLastRefresh(new Date());

    setL('arch', true);
    setE('arch', null);
    withTimeout(api.client.post('/intelligence/arch-governor/review', { run_id: 'global' }), ANALYSIS_TIMEOUT_MS)
      .then(r => setArchReview(r.data))
      .catch(e => setE('arch', e.message || e.response?.data?.detail || 'Failed'))
      .finally(() => setL('arch', false));

    setL('tradeoff', true);
    setE('tradeoff', null);
    withTimeout(api.client.post('/intelligence/tradeoff-engine/analyze', { scope: 'platform' }), ANALYSIS_TIMEOUT_MS)
      .then(r => setTradeoff(r.data))
      .catch(e => setE('tradeoff', e.message || e.response?.data?.detail || 'Failed'))
      .finally(() => setL('tradeoff', false));

    setL('truth', true);
    setE('truth', null);
    withTimeout(api.client.post('/intelligence/truth-engine/validate', { scope: 'platform' }), ANALYSIS_TIMEOUT_MS)
      .then(r => setTruth(r.data))
      .catch(e => setE('truth', e.message || e.response?.data?.detail || 'Failed'))
      .finally(() => setL('truth', false));
  }, []);

  const load = useCallback(() => { loadGets(); runAnalysis(); }, [loadGets, runAnalysis]);

  useEffect(() => { loadGets(); }, [loadGets]);

  const insightsList = insights?.insights || insights?.items || (Array.isArray(insights) ? insights : []);
  const benchmarkScore = benchmark?.overall_score ?? benchmark?.score ?? null;
  const archIssues = archReview?.issues || archReview?.violations || [];
  const tradeoffs = tradeoff?.recommendations || tradeoff?.tradeoffs || [];
  const truthScore = truth?.confidence ?? truth?.score ?? null;

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-accent" /> Intelligence Hub
          </h1>
          <p className="text-sm text-muted mt-1">
            AI self-assessment of output quality, architecture, and platform health.
            {lastRefresh && <span className="ml-2 text-muted/60">Last refreshed {lastRefresh.toLocaleTimeString()}</span>}
          </p>
        </div>
        <button onClick={load}
          className="flex items-center gap-2 px-4 py-2 bg-surface border border-border rounded-lg text-xs font-bold text-muted hover:text-bright hover:border-accent/40 transition-colors">
          <RefreshCw className="w-3.5 h-3.5" /> Refresh All
        </button>
        {!analysisRun && (
          <button onClick={runAnalysis}
            className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 rounded-lg text-xs font-bold text-white transition-colors">
            <Sparkles className="w-3.5 h-3.5" /> Run Analysis
          </button>
        )}
      </div>

      {/* Stat row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Quality Score', value: benchmarkScore !== null ? <ScoreBadge score={benchmarkScore} /> : '—', sub: 'vs target 80%', icon: TrendingUp, color: 'text-emerald-400' },
          { label: 'Truth Confidence', value: truthScore !== null ? <ScoreBadge score={truthScore} /> : '—', sub: 'output validity', icon: CheckCircle2, color: 'text-blue-400' },
          { label: 'Arch Issues', value: <span className="text-2xl font-bold font-mono text-bright">{archIssues.length}</span>, sub: 'detected', icon: Shield, color: 'text-yellow-400' },
          { label: 'Tradeoffs', value: <span className="text-2xl font-bold font-mono text-bright">{tradeoffs.length}</span>, sub: 'recommendations', icon: Scale, color: 'text-purple-400' },
        ].map(({ label, value, sub, icon: Icon, color }) => (
          <div key={label} className="bg-panel border border-border rounded-xl p-4 space-y-1">
            <div className="flex items-center gap-1.5 mb-2">
              <Icon className={`w-3.5 h-3.5 ${color}`} />
              <span className="text-[10px] font-bold text-muted uppercase tracking-wider">{label}</span>
            </div>
            {value}
            <p className="text-[10px] text-muted">{sub}</p>
          </div>
        ))}
      </div>

      {/* Main content grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* Global Insights */}
        <Card title="Global Insights" icon={Lightbulb} iconColor="text-yellow-400"
          loading={loading.insights} error={errors.insights}>
          {insightsList.length === 0
            ? <p className="text-xs text-muted">No insights yet — run a few pipelines to generate data.</p>
            : insightsList.map((ins, i) => (
                <InsightItem
                  key={ins.id || ins.message || ins.text || i}
                  text={typeof ins === 'string' ? ins : ins.message || ins.text || JSON.stringify(ins)}
                  type={ins.severity || ins.type || 'info'}
                />
              ))}
        </Card>

        {/* Quality Benchmark */}
        <Card title="Quality Benchmark" icon={TrendingUp} iconColor="text-emerald-400"
          loading={loading.benchmark} error={errors.benchmark}>
          {!benchmark
            ? <p className="text-xs text-muted">No benchmark data yet.</p>
            : (
              <div className="space-y-3">
                {Object.entries(benchmark)
                  .filter(([k]) => !['overall_score','score'].includes(k))
                  .slice(0, 6)
                  .map(([k, v]) => {
                    const pct = typeof v === 'number' ? normPct(v) : null;
                    return (
                      <div key={k} className="space-y-1">
                        <div className="flex justify-between items-center">
                          <span className="text-xs text-muted capitalize">{k.replace(/_/g,' ')}</span>
                          {pct !== null && <span className="text-xs font-mono text-bright">{pct}%</span>}
                        </div>
                        {pct !== null && (
                          <div className="h-1.5 bg-border rounded-full overflow-hidden">
                            <div className={`h-full rounded-full transition-all ${pct>=80?'bg-emerald-400':pct>=60?'bg-yellow-400':'bg-red-400'}`}
                              style={{ width: `${pct}%` }} />
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>
            )}
        </Card>

        {/* Architecture Governor */}
        <Card title="Architecture Governor" icon={Shield} iconColor="text-blue-400"
          loading={loading.arch} error={errors.arch}>
          {!analysisRun && !loading.arch
            ? <p className="text-xs text-muted">Click <strong>Run Analysis</strong> to check for architectural violations.</p>
            : archIssues.length === 0
              ? <div className="flex items-center gap-2 text-emerald-400 text-sm"><CheckCircle2 className="w-4 h-4" /> No architectural violations detected</div>
              : archIssues.map((issue, i) => (
                  <InsightItem key={issue.id || issue.message || i}
                    text={typeof issue === 'string' ? issue : issue.message || JSON.stringify(issue)}
                    type={issue.severity === 'critical' ? 'error' : issue.severity === 'warning' ? 'warning' : 'info'} />
                ))}
          {archReview?.summary && <ExpandableSection label="Full review">{archReview.summary}</ExpandableSection>}
        </Card>

        {/* Tradeoff Engine */}
        <Card title="Tradeoff Analysis" icon={Scale} iconColor="text-purple-400"
          loading={loading.tradeoff} error={errors.tradeoff}>
          {!analysisRun && !loading.tradeoff
            ? <p className="text-xs text-muted">Click <strong>Run Analysis</strong> to analyse platform tradeoffs.</p>
            : tradeoffs.length === 0
              ? <p className="text-xs text-muted">No tradeoff recommendations available.</p>
              : tradeoffs.map((t, i) => (
                  <InsightItem key={t.id || t.recommendation || t.message || i}
                    text={typeof t === 'string' ? t : t.recommendation || t.message || JSON.stringify(t)}
                    type={t.priority === 'high' ? 'warning' : 'info'} />
                ))}
        </Card>

        {/* Truth Engine (full width) */}
        <div className="lg:col-span-2">
          <Card title="Truth Engine — Output Validation" icon={Brain} iconColor="text-pink-400"
            loading={loading.truth} error={errors.truth}>
            {!analysisRun && !loading.truth
              ? <p className="text-xs text-muted">Click <strong>Run Analysis</strong> to validate platform output integrity.</p>
              : !truth
              ? <p className="text-xs text-muted">No validation data yet.</p>
              : (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {Object.entries(truth)
                    .filter(([k]) => k !== 'confidence')
                    .slice(0, 6)
                    .map(([k, v]) => (
                      <div key={k} className="bg-surface border border-border rounded-lg p-3">
                        <p className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1.5">{k.replace(/_/g,' ')}</p>
                        <p className="text-xs text-bright break-words">
                          {typeof v === 'boolean' ? (v ? '✓ Pass' : '✗ Fail')
                           : typeof v === 'number' ? `${normPct(v)}%`
                           : String(v)}
                        </p>
                      </div>
                    ))}
                </div>
              )}
          </Card>
        </div>
      </div>

      {/* Interactive AI Tools */}
      <div>
        <h2 className="text-xs font-bold text-muted/60 uppercase tracking-widest mb-3">Interactive AI Tools</h2>
        <div className="space-y-3">
          <ToolCard title="Conflict Resolver — Detect & Resolve Requirements Conflicts" icon={GitMerge} iconColor="text-orange-400">
            <ConflictResolverTool />
          </ToolCard>
          <ToolCard title="Maintenance Engine — Dependency & Tech Debt Scanner" icon={Wrench} iconColor="text-cyan-400">
            <MaintenanceEngineTool />
          </ToolCard>
          <ToolCard title="Improvement Loop — Generate Actionable Run Improvements" icon={RotateCcw} iconColor="text-violet-400">
            <ImprovementLoopTool />
          </ToolCard>
        </div>
      </div>
    </div>
  );
};

export default IntelligenceHub;
