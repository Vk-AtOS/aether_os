import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, Check, Loader2, ExternalLink } from 'lucide-react';
import { api } from '../../api';
import { hslToHex, hexToHsl, isValidHex } from './DesignerData';

// ── SearchableSelect ───────────────────────────────────────────────────────────
export const SearchableSelect = ({ value, options, onChange, placeholder }) => {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const ref = useRef(null);
  useEffect(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  const filtered = options.filter(o => o.toLowerCase().includes(q.toLowerCase()));
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(p => !p)}
        className="w-full flex items-center justify-between px-3 py-2 bg-surface border border-border rounded-lg text-sm text-bright hover:border-accent/50 transition-colors">
        <span className={value ? 'text-bright' : 'text-muted'}>{value || placeholder || 'Select…'}</span>
        <ChevronDown className="w-3.5 h-3.5 text-muted shrink-0" />
      </button>
      {open && (
        <div className="absolute z-50 w-full mt-1 bg-panel border border-border rounded-lg shadow-xl max-h-48 overflow-hidden flex flex-col">
          <div className="p-1.5 border-b border-border">
            <input autoFocus className="w-full bg-surface border border-border text-sm text-bright rounded px-2 py-1 outline-none" placeholder="Search…" value={q} onChange={e => setQ(e.target.value)} />
          </div>
          <div className="overflow-y-auto">
            {filtered.map(opt => (
              <button key={opt} type="button" onClick={() => { onChange(opt); setOpen(false); setQ(''); }}
                className="w-full flex items-center justify-between px-3 py-2 text-sm text-left hover:bg-border/30 text-bright transition-colors">
                {opt}{value === opt && <Check className="w-3.5 h-3.5 text-accent" />}
              </button>
            ))}
            {filtered.length === 0 && <p className="px-3 py-2 text-xs text-muted">No results</p>}
          </div>
        </div>
      )}
    </div>
  );
};

// ── StackGroup ─────────────────────────────────────────────────────────────────
export const StackGroup = ({ title, fields, values, onChange }) => (
  <div>
    <h3 className="text-xs font-bold text-muted uppercase tracking-widest mb-3">{title}</h3>
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {fields.map(({ key, label, options }) => (
        <div key={key}>
          <label className="block text-xs text-muted mb-1">{label}</label>
          <SearchableSelect value={values[key]} options={options} onChange={v => onChange(key, v)} />
        </div>
      ))}
    </div>
  </div>
);

// ── HslPicker ──────────────────────────────────────────────────────────────────
export const HslPicker = ({ hex, onChange }) => {
  const [h, s, l] = isValidHex(hex) ? hexToHsl(hex) : [220, 70, 50];
  // Text typed into the hex box that is not (yet) a valid colour; otherwise the box shows the prop.
  const [draftHex, setDraftHex] = useState(null);
  const localHex = draftHex ?? hex;
  const squareRef = useRef(null);
  const hueRef = useRef(null);
  const dragging = useRef(null);

  const fromSquare = useCallback((e, ref) => {
    const r = ref.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    const y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
    const v = hslToHex(h, Math.round(x*100), Math.round((1-y)*100));
    onChange(v); setDraftHex(null);
  }, [h, onChange]);

  const fromHue = useCallback((e, ref) => {
    const r = ref.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    const v = hslToHex(Math.round(x*360), s, l);
    onChange(v); setDraftHex(null);
  }, [s, l, onChange]);

  useEffect(() => {
    const move = e => { if (dragging.current === 'sq') fromSquare(e, squareRef); else if (dragging.current === 'hue') fromHue(e, hueRef); };
    const up = () => { dragging.current = null; };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); };
  }, [fromSquare, fromHue]);

  return (
    <div className="space-y-3 select-none">
      <div ref={squareRef} className="relative w-full h-32 rounded-lg cursor-crosshair"
        style={{ background: `hsl(${h},100%,50%)` }}
        onMouseDown={e => { e.preventDefault(); dragging.current = 'sq'; fromSquare(e, squareRef); }}>
        <div className="absolute inset-0 rounded-lg" style={{ background: 'linear-gradient(to right,white,transparent)' }} />
        <div className="absolute inset-0 rounded-lg" style={{ background: 'linear-gradient(to top,black,transparent)' }} />
        <div className="absolute w-4 h-4 rounded-full border-2 border-white shadow-md -translate-x-1/2 -translate-y-1/2 pointer-events-none"
          style={{ left: `${s}%`, top: `${100-l}%`, background: hex }} />
      </div>
      <div ref={hueRef} className="relative w-full h-4 rounded-full cursor-pointer"
        style={{ background: 'linear-gradient(to right,hsl(0,100%,50%),hsl(60,100%,50%),hsl(120,100%,50%),hsl(180,100%,50%),hsl(240,100%,50%),hsl(300,100%,50%),hsl(360,100%,50%))' }}
        onMouseDown={e => { e.preventDefault(); dragging.current = 'hue'; fromHue(e, hueRef); }}>
        <div className="absolute top-1/2 w-5 h-5 rounded-full border-2 border-white shadow-md -translate-x-1/2 -translate-y-1/2 pointer-events-none"
          style={{ left: `${(h/360)*100}%`, background: `hsl(${h},100%,50%)` }} />
      </div>
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 rounded border border-border shrink-0" style={{ background: hex }} />
        <input className="flex-1 bg-surface border border-border text-bright text-xs rounded px-2 py-1 font-mono uppercase"
          value={localHex} maxLength={7} placeholder="#6366f1"
          onChange={e => { if (isValidHex(e.target.value)) { setDraftHex(null); onChange(e.target.value); } else setDraftHex(e.target.value); }} />
      </div>
    </div>
  );
};

// ── RunOutput ──────────────────────────────────────────────────────────────────
export const RunOutput = ({ runId }) => {
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await api.getRun(runId);
        if (!cancelled) {
          setRun(res.data); setLoading(false);
          if (!['completed','failed','cancelled','rejected'].includes(res.data?.status)) setTimeout(poll, 3000);
        }
      } catch (e) {
        console.warn('RunOutput poll failed:', e);
        if (!cancelled) setLoading(false);
      }
    };
    poll();
    return () => { cancelled = true; };
  }, [runId]);

  if (loading) return <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 text-accent animate-spin" /><span className="ml-3 text-muted">Loading run…</span></div>;
  if (!run) return <p className="text-muted py-10 text-center">Run not found.</p>;

  const phases = run.phases || [];
  const sc = { completed:'text-emerald-400', failed:'text-red-400', running:'text-accent', queued:'text-yellow-400' };
  const bc = { completed:'bg-emerald-400', failed:'bg-red-400', running:'bg-accent animate-pulse', queued:'bg-border' };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h3 className="text-lg font-bold text-bright">{run.project_name || 'Factory Run'}</h3>
          <span className={`text-sm font-semibold ${sc[run.status] || 'text-muted'}`}>{run.status}</span>
        </div>
        <button onClick={() => navigate(`/project/${runId}`)}
          className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-semibold rounded-lg transition-colors">
          <ExternalLink className="w-4 h-4" /> Full View
        </button>
      </div>
      {phases.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-bold text-muted uppercase tracking-widest">Phases</h4>
          {phases.map((ph, i) => (
            <div key={ph.name || ph.phase || i} className="flex items-center gap-3 p-3 bg-surface rounded-lg border border-border">
              <div className={`w-2 h-2 rounded-full shrink-0 ${bc[ph.status] || 'bg-border'}`} />
              <span className="text-sm text-bright flex-1">{ph.name || ph.phase}</span>
              <span className={`text-xs ${sc[ph.status] || 'text-muted'}`}>{ph.status}</span>
            </div>
          ))}
        </div>
      )}
      {run.status === 'completed' && (
        <div className="flex flex-wrap gap-3">
          {run.artifact_url && (
            <a href={run.artifact_url} className="flex items-center gap-2 px-4 py-2 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-sm font-semibold rounded-lg hover:bg-emerald-500/20 transition-colors">
              <ExternalLink className="w-4 h-4" /> Download Artifact
            </a>
          )}
          <button onClick={() => navigate(`/project/${runId}`)}
            className="flex items-center gap-2 px-4 py-2 bg-accent/10 border border-accent/30 text-accent text-sm font-semibold rounded-lg hover:bg-accent/20 transition-colors">
            <ExternalLink className="w-4 h-4" /> View Project
          </button>
        </div>
      )}
    </div>
  );
};
