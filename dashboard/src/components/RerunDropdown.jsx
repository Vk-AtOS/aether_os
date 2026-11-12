import React, { useState, useRef, useEffect } from 'react';
import {
  RotateCcw, Play, Pencil, Layers, ChevronDown, ChevronRight, X, Loader2, Rocket,
} from 'lucide-react';
// One stage list for the whole dashboard; reruns must name a stage the pipeline knows.
import { PHASES, PHASE_NAMES } from './project/projectConstants';


// ── Edit & Restart modal ─────────────────────────────────────────────────────

const EditModal = ({ rawInput, onConfirm, onClose }) => {
  const [value, setValue] = useState(rawInput || '');

  // Esc to close
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={(e) => { e.stopPropagation(); if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="relative w-full max-w-xl mx-4 bg-panel border border-border rounded-2xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center space-x-3">
            <div className="w-7 h-7 rounded-lg bg-yellow-500/15 flex items-center justify-center">
              <Pencil className="w-3.5 h-3.5 text-yellow-400" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-bright">Edit & Restart</h3>
              <p className="text-[11px] text-muted mt-0.5">Modify the requirement, then start a new run</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-muted hover:text-bright transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={8}
            autoFocus
            className="w-full bg-black/40 border border-border rounded-lg px-3 py-2.5 font-mono text-sm text-bright focus:outline-none focus:border-accent resize-none custom-scrollbar placeholder:text-muted/50"
            placeholder="Describe your project requirement…"
          />

          <div className="flex justify-end space-x-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-muted hover:text-bright transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => { if (value.trim()) onConfirm(value.trim()); }}
              disabled={!value.trim()}
              className="flex items-center space-x-2 px-5 py-2 text-sm bg-accent hover:bg-accent/90 text-white font-bold rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Rocket className="w-3.5 h-3.5" />
              <span>Start New Run</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ── RerunDropdown ────────────────────────────────────────────────────────────
//
// Props:
//   status        — current run status string
//   rawInput      — original requirement text (for Edit & Restart)
//   onContinue()  — called for "Continue from here"
//   onEditRestart(editedReq) — called after user confirms Edit & Restart
//   onRerunPhase(phase)      — called with a phase key
//   onFullRestart()          — called for Full restart (new run from s01_intake)
//   onRestart()              — failed/cancelled only: resume this run at its blocked stage
//   loading       — show spinner on trigger
//   variant       — 'compact' (icon-only, for table rows) | 'button' (full pill, for detail view)

const RerunDropdown = ({
  status,
  rawInput,
  onContinue,
  onEditRestart,
  onRerunPhase,
  onFullRestart,
  onRestart,
  loading = false,
  variant = 'compact',
}) => {
  const [open, setOpen]               = useState(false);
  const [phaseExpanded, setPhaseExpanded] = useState(false);
  const [editOpen, setEditOpen]       = useState(false);
  const wrapRef = useRef(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
        setPhaseExpanded(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const canContinue = status === 'paused' || status === 'interrupted';
  const canRestart = Boolean(onRestart) && (status === 'failed' || status === 'cancelled');

  const handleToggle = (e) => {
    e.stopPropagation();
    setOpen((v) => !v);
    if (open) setPhaseExpanded(false);
  };

  const closeAll = () => {
    setOpen(false);
    setPhaseExpanded(false);
  };

  return (
    <>
      <div className="relative" ref={wrapRef}>

        {/* ── Trigger ── */}
        {variant === 'compact' ? (
          <button
            onClick={handleToggle}
            disabled={loading}
            className="p-1.5 rounded text-indigo-400 hover:bg-indigo-400/10 transition-colors disabled:opacity-50"
            title="Run options"
          >
            {loading
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : <RotateCcw className="w-4 h-4" />}
          </button>
        ) : (
          <button
            onClick={handleToggle}
            disabled={loading}
            className="flex items-center space-x-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-bold rounded-lg transition-colors disabled:opacity-50 text-sm"
          >
            {loading
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : <RotateCcw className="w-4 h-4" />}
            <span>Re-run options</span>
            <ChevronDown className={`w-4 h-4 transition-transform ${open ? 'rotate-180' : ''}`} />
          </button>
        )}

        {/* ── Dropdown card ── */}
        {open && (
          <div
            className="absolute bottom-full right-0 mb-2 z-50 w-68 min-w-[260px] bg-[#12131f] border border-white/[0.08] rounded-2xl shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >

            {/* 1. Continue from here — only when status allows */}
            {canContinue && (
              <button
                onClick={() => { closeAll(); onContinue?.(); }}
                className="w-full flex items-start space-x-3 px-4 py-3 hover:bg-white/[0.05] transition-colors text-left group"
              >
                <div className="w-7 h-7 rounded-lg bg-emerald-500/15 flex items-center justify-center shrink-0 mt-0.5">
                  <Play className="w-3.5 h-3.5 text-emerald-400" />
                </div>
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold text-bright leading-tight">Continue from here</div>
                  <div className="text-[11px] text-muted mt-0.5">Resume the paused pipeline</div>
                </div>
              </button>
            )}

            {canRestart && (
              <button
                onClick={() => { closeAll(); onRestart(); }}
                className="w-full flex items-start space-x-3 px-4 py-3 hover:bg-white/[0.05] transition-colors text-left group"
              >
                <div className="w-7 h-7 rounded-lg bg-emerald-500/15 flex items-center justify-center shrink-0 mt-0.5">
                  <Play className="w-3.5 h-3.5 text-emerald-400" />
                </div>
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold text-bright leading-tight">Restart this run</div>
                  <div className="text-[11px] text-muted mt-0.5">Resume at the stage that stopped it</div>
                </div>
              </button>
            )}

            {/* 2. Edit & Restart */}
            <button
              onClick={() => { closeAll(); setEditOpen(true); }}
              className="w-full flex items-start space-x-3 px-4 py-3 hover:bg-white/[0.05] transition-colors text-left group"
            >
              <div className="w-7 h-7 rounded-lg bg-yellow-500/15 flex items-center justify-center shrink-0 mt-0.5">
                <Pencil className="w-3.5 h-3.5 text-yellow-400" />
              </div>
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-bright leading-tight">Edit &amp; Restart</div>
                <div className="text-[11px] text-muted mt-0.5">Modify requirement, start fresh</div>
              </div>
            </button>

            {/* 3. Re-run from phase (expandable) */}
            <div>
              <button
                onClick={() => setPhaseExpanded((v) => !v)}
                className="w-full flex items-start space-x-3 px-4 py-3 hover:bg-white/[0.05] transition-colors text-left"
              >
                <div className="w-7 h-7 rounded-lg bg-indigo-500/15 flex items-center justify-center shrink-0 mt-0.5">
                  <Layers className="w-3.5 h-3.5 text-indigo-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-semibold text-bright leading-tight">Re-run from stage</div>
                  <div className="text-[11px] text-muted mt-0.5">New run starting at the stage you pick</div>
                </div>
                <ChevronRight
                  className={`w-3.5 h-3.5 text-muted shrink-0 mt-1 transition-transform ${phaseExpanded ? 'rotate-90' : ''}`}
                />
              </button>

              {/* Phase submenu */}
              {phaseExpanded && (
                <div className="border-t border-white/[0.06] bg-black/25 max-h-48 overflow-y-auto custom-scrollbar">
                  {PHASES.map((p, i) => (
                    <button
                      key={p}
                      onClick={() => { closeAll(); onRerunPhase?.(p); }}
                      className="w-full flex items-center space-x-3 px-5 py-2.5 hover:bg-white/[0.05] transition-colors text-left"
                    >
                      <span className="text-[10px] font-mono text-muted/60 w-4 shrink-0">{String(i + 1).padStart(2, '0')}</span>
                      <span className="text-[12px] text-muted hover:text-bright transition-colors">{PHASE_NAMES[p]}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Divider */}
            <div className="border-t border-white/[0.06]" />

            {/* 4. Full restart */}
            <button
              onClick={() => { closeAll(); onFullRestart?.(); }}
              className="w-full flex items-start space-x-3 px-4 py-3 hover:bg-white/[0.05] transition-colors text-left group"
            >
              <div className="w-7 h-7 rounded-lg bg-red-500/15 flex items-center justify-center shrink-0 mt-0.5">
                <RotateCcw className="w-3.5 h-3.5 text-red-400" />
              </div>
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-bright leading-tight">Full restart</div>
                <div className="text-[11px] text-muted mt-0.5">New run through all 12 stages</div>
              </div>
            </button>

          </div>
        )}
      </div>

      {/* Edit modal — rendered outside the relative wrapper so it stacks correctly */}
      {editOpen && (
        <EditModal
          rawInput={rawInput}
          onConfirm={(req) => { setEditOpen(false); onEditRestart?.(req); }}
          onClose={() => setEditOpen(false)}
        />
      )}
    </>
  );
};

export default RerunDropdown;
