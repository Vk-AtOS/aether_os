import React, { useEffect, useState } from 'react';
import {
  Loader2, CheckCircle2, AlertTriangle, Lightbulb,
  ChevronDown, ChevronRight, GitMerge, Wrench, RotateCcw, Play, Sparkles,
} from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';
import { normPct } from './normPct';
import { findResolved } from './conflictHelpers';

// ── Helpers ────────────────────────────────────────────────────────────────────
export const ScoreBadge = ({ score }) => {
  const pct = normPct(score);
  const color = pct >= 80 ? 'text-emerald-400' : pct >= 60 ? 'text-yellow-400' : 'text-red-400';
  return (
    <span className={`text-2xl font-bold font-mono tabular-nums ${color}`}>{pct}<span className="text-base">%</span></span>
  );
};

export const SkeletonBlock = ({ lines = 3 }) => (
  <div className="space-y-2 animate-pulse">
    {Array.from({ length: lines }).map((_, i) => (
      <div key={i} className={`h-3 bg-border/40 rounded ${i === lines - 1 ? 'w-2/3' : 'w-full'}`} />
    ))}
  </div>
);

export const Card = ({ title, icon: Icon, iconColor = 'text-accent', loading, error, children }) => (
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

export const InsightItem = ({ text, type = 'info' }) => {
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

export const ExpandableSection = ({ label, children }) => {
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

export const ToolCard = ({ title, icon: Icon, iconColor, children }) => {
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

// ── ConflictResolverTool ───────────────────────────────────────────────────────
export const ConflictResolverTool = () => {
  const [req, setReq] = useState('');
  const [constraints, setConstraints] = useState('');
  const [archDoc, setArchDoc] = useState('');
  const [detecting, setDetecting] = useState(false);
  const [resolving, setResolving] = useState(null);
  const [conflicts, setConflicts] = useState(null);
  const [error, setError] = useState('');
  const [resolveInputId, setResolveInputId] = useState(null);
  const [resolveText, setResolveText] = useState('');
  const [resolveError, setResolveError] = useState('');
  // Resolutions are shared by the whole organisation: conflicts someone already resolved, and who did.
  const [shared, setShared] = useState({});
  useEffect(() => {
    api.client.get('/intelligence/conflict-resolver/resolved')
      .then((r) => setShared(r.data?.resolved || {}))
      .catch(() => {});
  }, []);

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
      setError(apiError(e) || 'Detection failed');
    } finally {
      setDetecting(false);
    }
  };

  const resolve = async (conflict_id, description = '') => {
    if (!resolveText.trim()) { setResolveError('Write the resolution first.'); return; }
    setResolving(conflict_id);
    setResolveError('');
    try {
      const r = await api.client.post('/intelligence/conflict-resolver/resolve', { conflict_id, resolution: resolveText, description, run_id: '' });
      setShared(s => ({ ...s, [r.data.key]: { resolution: resolveText, resolved_by: r.data.resolved_by, description } }));
      setResolveInputId(null);
      setResolveText('');
    } catch (e) {
      setResolveError('Resolve failed: ' + (apiError(e) || e.message));
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
              const done = findResolved(shared, msg);
              return (
                <div key={id} className={`p-3 rounded-lg border text-xs space-y-2 ${done ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-yellow-500/30 bg-yellow-500/5'}`}>
                  <div className="flex items-start gap-3">
                    {done ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" /> : <AlertTriangle className="w-3.5 h-3.5 text-yellow-400 mt-0.5 shrink-0" />}
                    <span className="flex-1 text-bright/90">{msg}
                      {done && <span className="block text-[10px] text-muted mt-1" data-testid="resolved-by">Resolved{done.resolved_by ? ` by ${done.resolved_by}` : ''}: {done.resolution}</span>}
                    </span>
                    {!done && resolveInputId !== id && (
                      <button
                        onClick={() => { setResolveInputId(id); setResolveText(''); setResolveError(''); }}
                        className="shrink-0 text-[10px] font-bold text-accent hover:text-bright border border-accent/30 px-2 py-1 rounded transition-colors"
                      >
                        Resolve
                      </button>
                    )}
                  </div>
                  {!done && resolveInputId === id && (
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
                          onClick={() => resolve(id, msg)}
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

// ── MaintenanceEngineTool ──────────────────────────────────────────────────────
export const MaintenanceEngineTool = () => {
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
      setError(apiError(e) || 'Scan failed');
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

// ── ImprovementLoopTool ────────────────────────────────────────────────────────
export const ImprovementLoopTool = () => {
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
      setError(apiError(e) || 'Improvement loop failed');
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
                  <div key={imp.id || msg || i} className="flex items-start gap-2.5 py-2 border-b border-border/40 last:border-0">
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
