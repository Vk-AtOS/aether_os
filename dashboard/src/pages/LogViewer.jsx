/**
 * AetherOS — LogViewer
 *
 * Structured phase-by-phase log view for a pipeline run.
 * - Shows each phase as a collapsible section with status badge and duration
 * - Displays key artifacts produced per phase
 * - Live updates via SSE when run is in progress (passed as feedLines prop)
 * - Shows LLM call count per phase when available
 * - Auto-scrolls to the latest active phase
 * - Copy logs button
 *
 * Props:
 *   run       {object}  — run detail object from /factory/runs/{id}
 *   feedLines {string[]} — raw SSE terminal lines (from ProjectView)
 *   isRunning {boolean}
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  ChevronDown, ChevronRight, CheckCircle2, XCircle, Clock,
  Loader2, Copy, Check, FileText, Cpu, AlertTriangle,
} from 'lucide-react';

// ── Phase display metadata ────────────────────────────────────────────────────

const PHASE_LABELS = {
  p01_intake_requirements: 'Intake & Requirements',
  p02_architecture:        'Architecture Design',
  p02b_domain_ir:          'Domain IR Extraction',
  p03_scaffolding:         'Project Scaffolding',
  p04_backend:             'Backend Codegen',
  p05_frontend:            'Frontend Codegen',
  p06_review_security:     'Code Review & Security',
  p07_testing:             'Testing Suite',
  p07b_self_healing:       'Self-Healing',
  p08_cicd_deployment:     'CI/CD & Deployment',
  p09_observability:       'Observability',
  p10_docs_delivery:       'Docs & Delivery',
  p11_deployment:          'Deployment',
  p11a_monitoring:         'Monitoring & Metrics',
  p11b_error_tracking:     'Error Tracking',
  p11c_analytics:          'Analytics',
  p11d_alerting:           'Alerting & Runbooks',
  p12a_feature_flags:      'Feature Flags',
  p12b_ab_testing:         'A/B Testing',
  p13_app_memory:          'App Memory Layer',
  p14_client_portal:       'Client Portal',
};

// ── Status badge ─────────────────────────────────────────────────────────────

const StatusBadge = ({ status }) => {
  if (!status) return null;

  const cfg = {
    passed:    { icon: CheckCircle2, color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20' },
    completed: { icon: CheckCircle2, color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20' },
    failed:    { icon: XCircle,      color: 'text-red-400 bg-red-400/10 border-red-400/20'             },
    timeout:   { icon: Clock,        color: 'text-orange-400 bg-orange-400/10 border-orange-400/20'    },
    running:   { icon: Loader2,      color: 'text-accent bg-accent/10 border-accent/20'                },
    skipped:   { icon: ChevronRight, color: 'text-slate-500 bg-slate-500/10 border-slate-500/20'       },
  }[status.toLowerCase()] || { icon: null, color: 'text-muted bg-border/20 border-border' };

  const Icon = cfg.icon;
  const isSpinning = status.toLowerCase() === 'running';

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${cfg.color}`}>
      {Icon && <Icon className={`w-3 h-3 ${isSpinning ? 'animate-spin' : ''}`} />}
      {status}
    </span>
  );
};

// ── Phase Row ─────────────────────────────────────────────────────────────────

const PhaseRow = ({ phaseKey, phaseData, phaseLines, isActive, autoExpand }) => {
  const [open, setOpen] = useState(autoExpand || isActive);
  const rowRef = useRef(null);

  // Auto-expand when this phase becomes active
  useEffect(() => {
    if (isActive && !open) setOpen(true);
  }, [isActive]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll into view when active
  useEffect(() => {
    if (isActive && rowRef.current) {
      rowRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [isActive]);

  const label    = PHASE_LABELS[phaseKey] || phaseKey;
  const status   = phaseData?.status || (isActive ? 'running' : null);
  const duration = phaseData?.duration_seconds ?? null;

  // Extract artifact names from output (file_written events or output.files)
  const artifacts = (() => {
    const out = phaseData?.output;
    if (!out) return [];
    if (Array.isArray(out?.files))   return out.files.slice(0, 6);
    if (Array.isArray(out?.artifacts)) return out.artifacts.slice(0, 6).map(a => a.name || a.path || a);
    return [];
  })();

  // Count LLM calls if tracked
  const llmCalls = phaseData?.output?.llm_calls ?? phaseData?.llm_calls ?? null;

  // Filter SSE lines that belong to this phase
  const phasePrefix = `[${phaseKey}]`;
  const relevantLines = phaseLines?.filter(l => l.includes(phasePrefix)) ?? [];

  return (
    <div
      ref={rowRef}
      className={`border-b border-border/40 last:border-0 transition-colors ${
        isActive ? 'bg-accent/5' : ''
      }`}
    >
      {/* Phase header row */}
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-border/20 transition-colors group"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <span className="text-muted group-hover:text-bright transition-colors shrink-0">
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </span>

        {/* Phase name */}
        <span className={`text-xs font-bold flex-1 min-w-0 truncate ${isActive ? 'text-bright' : 'text-muted'}`}>
          {label}
        </span>

        {/* Meta row */}
        <div className="flex items-center gap-3 shrink-0">
          {llmCalls != null && (
            <span className="hidden sm:flex items-center gap-1 text-[10px] text-muted">
              <Cpu className="w-3 h-3" />
              {llmCalls} LLM calls
            </span>
          )}
          {duration != null && (
            <span className="hidden sm:inline text-[10px] font-mono text-muted">
              {duration}s
            </span>
          )}
          {status ? (
            <StatusBadge status={status} />
          ) : (
            <span className="text-[10px] text-muted/40 uppercase tracking-wider">pending</span>
          )}
        </div>
      </button>

      {/* Expanded content */}
      {open && (
        <div className="px-4 pb-4 space-y-3">
          {/* Artifacts list */}
          {artifacts.length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1.5">
                Key Artifacts
              </p>
              <ul className="space-y-1">
                {artifacts.map((f, i) => (
                  <li key={i} className="flex items-center gap-2 text-[11px] text-muted font-mono">
                    <FileText className="w-3 h-3 text-accent/60 shrink-0" />
                    <span className="truncate">{typeof f === 'string' ? f : (f.path || f.name || JSON.stringify(f))}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* SSE log lines relevant to this phase */}
          {relevantLines.length > 0 && (
            <div className="rounded bg-black/40 border border-border/30 overflow-hidden">
              <p className="text-[9px] font-bold text-muted uppercase tracking-wider px-3 py-1.5 border-b border-border/20">
                Log Output
              </p>
              <div className="p-3 font-mono text-[10px] space-y-0.5 max-h-40 overflow-y-auto custom-scrollbar">
                {relevantLines.map((line, i) => (
                  <div key={i} className="text-slate-400 whitespace-pre-wrap break-all">{line}</div>
                ))}
              </div>
            </div>
          )}

          {/* No output yet for pending/empty phases */}
          {artifacts.length === 0 && relevantLines.length === 0 && (
            <p className="text-[11px] text-muted/50 italic">
              {isActive ? 'Phase in progress…' : status ? 'No structured output captured.' : 'Phase not yet started.'}
            </p>
          )}
        </div>
      )}
    </div>
  );
};

// ── Main LogViewer ─────────────────────────────────────────────────────────────

const LogViewer = ({ run, feedLines = [], isRunning }) => {
  const [copied, setCopied] = useState(false);
  const bottomRef = useRef(null);

  const phases  = run?.phases  || {};
  const events  = run?.events  || [];
  const current = run?.current_phase || null;

  // Build ordered phase list: known phases first, then any extras from run.phases
  const orderedPhases = (() => {
    const knownOrder = Object.keys(PHASE_LABELS);
    const runPhaseKeys = Object.keys(phases);
    const extra = runPhaseKeys.filter(k => !knownOrder.includes(k));
    return [...knownOrder.filter(k => runPhaseKeys.includes(k) || k === current), ...extra];
  })();

  // Auto-scroll when live
  useEffect(() => {
    if (isRunning && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [isRunning, feedLines.length]);

  // Copy all logs to clipboard
  const handleCopy = useCallback(() => {
    const lines = [
      `Run: ${run?.run_id || run?.id || ''}`,
      `Status: ${run?.status || ''}`,
      `Project: ${run?.project_name || ''}`,
      '',
      '=== Phase Summary ===',
      ...orderedPhases.map(pk => {
        const ph = phases[pk];
        const label = PHASE_LABELS[pk] || pk;
        const status = ph?.status || 'pending';
        const dur = ph?.duration_seconds != null ? ` (${ph.duration_seconds}s)` : '';
        return `${label}: ${status}${dur}`;
      }),
      '',
      '=== Event Log ===',
      ...events.map(e => {
        const ts = e.timestamp ? new Date(e.timestamp * 1000).toISOString() : '';
        return `[${ts}] ${e.agent || ''} ${e.action || ''} — ${e.detail || ''}`;
      }),
      '',
      '=== Live Feed ===',
      ...feedLines,
    ];
    navigator.clipboard.writeText(lines.join('\n'))
      .then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); })
      .catch(() => {});
  }, [run, orderedPhases, phases, events, feedLines]);

  // Summary stats
  const totalPhases    = orderedPhases.length;
  const passedCount    = orderedPhases.filter(k => phases[k]?.status === 'passed' || phases[k]?.status === 'completed').length;
  const failedCount    = orderedPhases.filter(k => phases[k]?.status === 'failed').length;
  const totalDuration  = orderedPhases.reduce((acc, k) => acc + (phases[k]?.duration_seconds || 0), 0);

  if (!run) {
    return (
      <div className="p-8 text-center text-muted text-sm">
        <Loader2 className="w-5 h-5 animate-spin mx-auto mb-3" />
        Loading run details…
      </div>
    );
  }

  return (
    <div className="flex flex-col" style={{ minHeight: '420px' }}>
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-border/10 shrink-0">
        <div className="flex items-center gap-4">
          <span className="text-[10px] font-bold text-muted uppercase tracking-wider">Phase Log</span>
          {totalPhases > 0 && (
            <div className="flex items-center gap-3 text-[10px] font-mono">
              <span className="text-emerald-400">{passedCount} passed</span>
              {failedCount > 0 && <span className="text-red-400">{failedCount} failed</span>}
              <span className="text-muted">{totalPhases} total</span>
              {totalDuration > 0 && (
                <span className="text-muted">{Math.round(totalDuration)}s total</span>
              )}
            </div>
          )}
          {isRunning && (
            <span className="flex items-center gap-1.5 text-[10px] font-bold text-emerald-400">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Live
            </span>
          )}
        </div>

        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-bold text-muted border border-border rounded-md hover:text-bright hover:border-accent/50 transition-colors"
          title="Copy all logs to clipboard"
        >
          {copied ? (
            <><Check className="w-3 h-3 text-emerald-400" /> Copied</>
          ) : (
            <><Copy className="w-3 h-3" /> Copy logs</>
          )}
        </button>
      </div>

      {/* Phase list */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {orderedPhases.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full py-12 text-muted gap-3">
            <AlertTriangle className="w-8 h-8 opacity-30" />
            <p className="text-sm">No phase data available yet.</p>
            <p className="text-xs opacity-60">Start a run to see pipeline progress here.</p>
          </div>
        ) : (
          orderedPhases.map((phaseKey) => (
            <PhaseRow
              key={phaseKey}
              phaseKey={phaseKey}
              phaseData={phases[phaseKey] ?? null}
              phaseLines={feedLines}
              isActive={phaseKey === current && isRunning}
              autoExpand={phaseKey === current}
            />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};

export default LogViewer;
