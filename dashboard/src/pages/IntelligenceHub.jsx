import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import {
  Sparkles, RefreshCw, Loader2, CheckCircle2, AlertTriangle,
  TrendingUp, Shield, Scale, Lightbulb, Brain, ChevronDown, ChevronRight,
  GitMerge, Wrench, RotateCcw, Play, X,
} from 'lucide-react';

// API returns scores either as 0-1 fractions OR 0-100 integers — normalise either way
const normPct = (score) => {
  if (score == null) return 0;
  return score > 1 ? Math.round(score) : Math.round(score * 100);
};

const ScoreBadge = ({ score }) => {
  const pct = normPct(score);
  const color = pct >= 80 ? 'text-emerald-400' : pct >= 60 ? 'text-yellow-400' : 'text-red-400';
  return (
    <span className={`text-2xl font-bold font-mono tabular-nums ${color}`}>{pct}<span className="text-base">%</span></span>
  );
};

const Card = ({ title, icon: Icon, iconColor = 'text-accent', loading, error, children }) => (
  <div className="bg-panel border border-border rounded-xl overflow-hidden">
    <div className="px-5 py-4 border-b border-border flex items-center gap-2">
      <Icon className={`w-4 h-4 ${iconColor}`} />
      <h3 className="text-sm font-semibold text-bright">{title}</h3>
      {loading && <Loader2 className="w-3.5 h-3.5 animate-spin text-muted ml-auto" />}
    </div>
    <div className="p-5">
      {error
        ? <p className="text-xs text-danger">{error}</p>
        : loading
          ? <SkeletonBlock lines={3} />
          : children}
    </div>
  </div>
);

const SkeletonBlock = ({ lines = 3 }) => (
  <div className="space-y-2 animate-pulse">
    {Array.from({ length: lines }).map((_, i) => (
      <div key={i} className={`h-3 bg-border/40 rounded ${i === lines - 1 ? 'w-2/3' : 'w-full'}`} />
    ))}
  </div>
);

const InsightItem = ({ text, type = 'info' }) => {
  const colors = { info: 'text-accent', warning: 'text-yellow-400', success: 'text-emerald-400', error: 'text-red-400' };
  const icons = { info: Lightbulb, warning: AlertTriangle, success: CheckCircle2, error: AlertTriangle };
  const Icon = icons[type] || Lightbulb;
  return (
    <div className="flex items-start gap-2.5 py-2 border-b border-border/40 last:border-0">
      <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${colors[type]}`} />
      <p className="text-xs text-bright/90 leading-relaxed">{text}</p>
    </div>
  );
};

const ExpandableSection = ({ label, children }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-border/40 mt-3 pt-3">
      <button onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 text-xs text-muted hover:text-bright transition-colors w-full text-left">
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {label}
      </button>
      {open && <div className="mt-2 text-xs text-bright/80 leading-relaxed whitespace-pre-wrap">{children}</div>}
    </div>
  );
};

const ToolCard = ({ title, icon: Icon, iconColor, children }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="bg-panel border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full px-5 py-4 flex items-center gap-2 hover:bg-surface/50 transition-colors text-left"
      >
        <Icon className={`w-4 h-4 ${iconColor}`} />
        <h3 className="text-sm font-semibold text-bright flex-1">{title}</h3>
        {open ? <ChevronDown className="w-3.5 h-3.5 text-muted" /> : <ChevronRight className="w-3.5 h-3.5 text-muted" />}
      </button>
      {open && <div className="px-5 pb-5 border-t border-border">{children}</div>}
    </div>
  );
};

const ConflictResolverTool = () => {
  const [req, setReq] = useState('');
  const [constraints, setConstraints] = useState('');
  const [archDoc, setArchDoc] = useState('');
  const [detecting, setDetecting] = useState(false);
  const [resolving, setResolving] = useState(null);
  const [conflicts, setConflicts] = useState(null);
  const [error, setError] = useState('');
  const [resolveInputId, setResolveInputId] = useState(null);
  const [resolveText, setResolveText] = useState('');

  const detect = async () => {
    setDetecting(true);
    setError('');
    setConflicts(null);
    try {
      const res = await api.client.post('/intelligence/conflict-resolver/detect', {
        requirements: req, constraints, architecture_doc: archDoc,
      });
      setConflicts(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Detection failed');
    } finally {
      setDetecting(false);
    }
  };

  const [resolveError, setResolveError] = useState('');

  const resolve = async (conflict_id) => {
    setResolving(conflict_id);
    setResolveError('');
    try {
      await api.client.post('/intelligence/conflict-resolver/resolve', { conflict_id, resolution: resolveText, run_id: '' });
      setConflicts(c => {
        const items = c?.conflicts || c?.items || [];
        return { ...c, conflicts: items.map(ci => ci.id === conflict_id ? { ...ci, resolved: true } : ci) };
      });
      setResolveInputId(null);
      setResolveText('');
    } catch (e) {
      setResolveError('Resolve failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setResolving(null);
    }
  };

  const conflictList = conflicts?.conflicts || conflicts?.items || (Array.isArray(conflicts) ? conflicts : []);

  return (
    <div className="pt-4 space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {[
          { label: 'Requirements', value: req, set: setReq, placeholder: 'Describe system requirements…' },
          { label: 'Constraints', value: constraints, set: setConstraints, placeholder: 'List constraints (budget, tech stack…)' },
          { label: 'Architecture Doc', value: archDoc, set: setArchDoc, placeholder: 'Paste architecture summary…' },
        ].map(({ label, value, set, placeholder }) => (
          <div key={label}>
            <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">{label}</label>
            <textarea
              value={value}
              onChange={e => set(e.target.value)}
              placeholder={placeholder}
              rows={4}
              className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs text-bright resize-none focus:outline-none focus:border-accent"
            />
          </div>
        ))}
      </div>
      {error && <p className="text-xs text-danger">{error}</p>}
      <button
        onClick={detect}
        disabled={detecting}
        className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors"
      >
        {detecting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
        {detecting ? 'Detecting…' : 'Detect Conflicts'}
      </button>
      {conflicts && (
        <div className="space-y-2">
          {conflictList.length === 0
            ? <p className="text-xs text-emerald-400 flex items-center gap-2"><CheckCircle2 className="w-3.5 h-3.5" /> No conflicts detected.</p>
            : conflictList.map((c, i) => {
              const id = c.id || String(i);
              const msg = typeof c === 'string' ? c : c.description || c.message || JSON.stringify(c);
              return (
                <div key={id} className={`p-3 rounded-lg border text-xs space-y-2 ${c.resolved ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-yellow-500/30 bg-yellow-500/5'}`}>
                  <div className="flex items-start gap-3">
                    {c.resolved ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" /> : <AlertTriangle className="w-3.5 h-3.5 text-yellow-400 mt-0.5 shrink-0" />}
                    <span className="flex-1 text-bright/90">{msg}</span>
                    {!c.resolved && resolveInputId !== id && (
                      <button
                        onClick={() => { setResolveInputId(id); setResolveText(''); setResolveError(''); }}
                        className="shrink-0 text-[10px] font-bold text-accent hover:text-bright border border-accent/30 px-2 py-1 rounded transition-colors"
                      >
                        Resolve
                      </button>
                    )}
                  </div>
                  {!c.resolved && resolveInputId === id && (
                    <div className="space-y-2 pl-6">
                      <input
                        value={resolveText}
                        onChange={e => setResolveText(e.target.value)}
                        placeholder="Describe the resolution…"
                        className="w-full bg-surface border border-border rounded px-2 py-1 text-xs text-bright focus:outline-none focus:border-accent"
                      />
                      {resolveError && <p className="text-[10px] text-danger">{resolveError}</p>}
                      <div className="flex gap-2">
                        <button
                          onClick={() => resolve(id)}
                          disabled={resolving === id || !resolveText.trim()}
                          className="text-[10px] font-bold text-accent hover:text-bright border border-accent/30 px-2 py-1 rounded transition-colors disabled:opacity-50"
                        >
                          {resolving === id ? '…' : 'Submit'}
                        </button>
                        <button
                          onClick={() => setResolveInputId(null)}
                          className="text-[10px] text-muted hover:text-bright px-2 py-1 rounded transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
};

const MaintenanceEngineTool = () => {
  const [mode, setMode] = useState('deps'); // 'deps' | 'code' | 'run'
  const [depsText, setDepsText] = useState('');
  const [codeText, setCodeText] = useState('');
  const [language, setLanguage] = useState('python');
  const [runId, setRunId] = useState('');
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const scan = async () => {
    setScanning(true);
    setError('');
    setResult(null);
    try {
      const payload = {};
      if (mode === 'deps' && depsText) payload.requirements_txt = depsText;
      if (mode === 'code' && codeText) { payload.code = codeText; payload.language = language; }
      if (mode === 'run' && runId) payload.run_id = runId;
      const res = await api.client.post('/intelligence/maintenance-engine/scan', payload);
      setResult(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Scan failed');
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="pt-4 space-y-4">
      <div className="flex gap-2">
        {[['deps','Dependencies'], ['code','Code Debt'], ['run','Project Health']].map(([m, label]) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-colors ${mode === m ? 'bg-accent text-white' : 'bg-surface border border-border text-muted hover:text-bright'}`}
          >
            {label}
          </button>
        ))}
      </div>
      {mode === 'deps' && (
        <div>
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">requirements.txt contents</label>
          <textarea
            value={depsText}
            onChange={e => setDepsText(e.target.value)}
            placeholder={'fastapi==0.100.0\nsqlalchemy>=2.0\nredis>=4.5'}
            rows={5}
            className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono text-bright resize-none focus:outline-none focus:border-accent"
          />
        </div>
      )}
      {mode === 'code' && (
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <label className="text-[10px] font-bold text-muted uppercase tracking-wider">Language</label>
            <select
              value={language}
              onChange={e => setLanguage(e.target.value)}
              className="bg-surface border border-border rounded px-2 py-1 text-xs text-bright focus:outline-none"
            >
              {['python','javascript','typescript','go','java','rust'].map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
          <textarea
            value={codeText}
            onChange={e => setCodeText(e.target.value)}
            placeholder="Paste code for tech debt analysis…"
            rows={6}
            className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono text-bright resize-none focus:outline-none focus:border-accent"
          />
        </div>
      )}
      {mode === 'run' && (
        <div>
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Run ID</label>
          <input
            value={runId}
            onChange={e => setRunId(e.target.value)}
            placeholder="Paste a run ID to check its health…"
            className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono text-bright focus:outline-none focus:border-accent"
          />
        </div>
      )}
      {error && <p className="text-xs text-danger">{error}</p>}
      <button
        onClick={scan}
        disabled={scanning}
        className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors"
      >
        {scanning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
        {scanning ? 'Scanning…' : 'Run Scan'}
      </button>
      {result && (
        <pre className="text-[11px] font-mono text-bright/80 bg-surface border border-border rounded-lg p-4 overflow-auto max-h-64 leading-relaxed whitespace-pre-wrap">
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
};

const ImprovementLoopTool = () => {
  const [runId, setRunId] = useState('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const runCycle = async () => {
    if (!runId.trim()) { setError('Run ID is required'); return; }
    setRunning(true);
    setError('');
    setResult(null);
    try {
      const res = await api.client.post(`/intelligence/improvement-loop/cycle?run_id=${encodeURIComponent(runId.trim())}`);
      setResult(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Improvement loop failed');
    } finally {
      setRunning(false);
    }
  };

  const improvements = result?.improvements || result?.suggestions || (Array.isArray(result) ? result : []);

  return (
    <div className="pt-4 space-y-4">
      <div>
        <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Run ID</label>
        <input
          value={runId}
          onChange={e => setRunId(e.target.value)}
          placeholder="Enter a completed run ID to generate improvements…"
          className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono text-bright focus:outline-none focus:border-accent"
        />
        <p className="text-[10px] text-muted mt-1">Analyses the run's output and generates actionable improvement suggestions.</p>
      </div>
      {error && <p className="text-xs text-danger">{error}</p>}
      <button
        onClick={runCycle}
        disabled={running || !runId.trim()}
        className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors"
      >
        {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
        {running ? 'Running cycle…' : 'Run Improvement Cycle'}
      </button>
      {result && (
        improvements.length === 0
          ? <p className="text-xs text-muted">No specific improvements generated. The run may already be optimal.</p>
          : <div className="space-y-2">
              {improvements.map((imp, i) => {
                const msg = typeof imp === 'string' ? imp : imp.suggestion || imp.message || JSON.stringify(imp);
                const priority = imp.priority || 'info';
                const color = priority === 'high' ? 'text-yellow-400' : 'text-accent';
                return (
                  <div key={i} className="flex items-start gap-2.5 py-2 border-b border-border/40 last:border-0">
                    <Sparkles className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${color}`} />
                    <p className="text-xs text-bright/90 leading-relaxed">{msg}</p>
                  </div>
                );
              })}
            </div>
      )}
    </div>
  );
};

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
                  key={i}
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
                  <InsightItem key={i}
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
                  <InsightItem key={i}
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
