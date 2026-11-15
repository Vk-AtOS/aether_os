import React, { useCallback, useEffect, useState } from 'react';
import { Server, Plus, RefreshCw, Trash2, KeyRound, Power, Activity } from 'lucide-react';
import { api } from '../../api';
import { confirmAction } from '../confirmAction';
import {
  LEVELS, LEVEL_HELP, testMessage, toggleLevel, keyShown, providerError, costText,
} from './providerHelpers';

const c = api.client;
const BASE = '/model-providers';
const field = 'w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent';
const label = 'text-[10px] font-bold text-muted uppercase tracking-wider block mb-1';
const EMPTY = { id: '', kind: 'openai_compatible', base_url: '', api_key: '', allow_local: false, free_pool: false, levels: ['public'] };

const Levels = ({ levels, freePool, onChange, idPrefix }) => (
  <div className="flex flex-wrap gap-3" role="group" aria-label="Data this provider may see">
    {LEVELS.map((l) => (
      <label key={l} className="flex items-center gap-1 text-xs text-bright" title={LEVEL_HELP[l]}>
        <input type="checkbox" id={`${idPrefix}-${l}`} checked={levels.includes(l)}
               disabled={freePool && l === 'restricted'} onChange={() => onChange(toggleLevel(levels, l, freePool))} />
        {l}
      </label>
    ))}
  </div>
);

// One provider: badges, sensitivity levels, test, rotate, disable, delete, models. The key is never shown.
const ProviderRow = ({ p, onChanged, setError }) => {
  const [test, setTest] = useState('');
  const [rotating, setRotating] = useState('');
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState(null);
  const act = async (fn) => { setError(''); try { await fn(); await onChanged(); } catch (e) { setError(providerError(e, 'That did not work.')); } };

  return (
    <li className="border border-border rounded-lg p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm text-bright">{p.id}</span>
        <span className="text-[10px] uppercase text-muted">{p.kind}</span>
        {p.free_pool && <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-yellow-400/10 text-yellow-400">free pool, no retention guarantee</span>}
        {!p.enabled && <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-border/30 text-muted">disabled</span>}
        <span className="text-xs text-muted font-mono ml-auto">{keyShown(p)}</span>
      </div>
      {p.base_url && <p className="text-xs text-muted font-mono break-all">{p.base_url}</p>}
      <Levels levels={p.sensitivity_allowed} freePool={p.free_pool} idPrefix={`lv-${p.id}`}
              onChange={(l) => act(() => c.put(`${BASE}/${p.id}`, { sensitivity_allowed: l }))} />
      <div className="flex flex-wrap gap-2">
        <button className="px-3 py-1.5 text-xs border border-border rounded flex items-center gap-1"
                onClick={async () => { setTest('Testing...'); try { setTest(testMessage((await c.post(`${BASE}/${p.id}/test`)).data)); } catch (e) { setTest(providerError(e, 'The test failed.')); } }}>
          <Activity className="w-3 h-3" /> Test connection
        </button>
        <button className="px-3 py-1.5 text-xs border border-border rounded flex items-center gap-1"
                onClick={() => act(() => c.put(`${BASE}/${p.id}`, { enabled: !p.enabled }))}>
          <Power className="w-3 h-3" /> {p.enabled ? 'Disable' : 'Enable'}
        </button>
        <button className="px-3 py-1.5 text-xs border border-border rounded flex items-center gap-1"
                onClick={async () => { const next = !open; setOpen(next); if (next && !models) setModels((await c.get(`${BASE}/${p.id}/models`)).data.models); }}>
          Models
        </button>
        <button className="px-3 py-1.5 text-xs text-danger border border-danger/40 rounded flex items-center gap-1"
                onClick={async () => { if (await confirmAction(`Delete provider ${p.id}? Calls that name it will fail.`, 'Delete provider')) act(() => c.delete(`${BASE}/${p.id}`)); }}>
          <Trash2 className="w-3 h-3" /> Delete
        </button>
      </div>
      {test && <p role="status" className="text-xs text-bright">{test}</p>}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (rotating) act(async () => { await c.post(`${BASE}/${p.id}/rotate`, { api_key: rotating }); setRotating(''); }); }}>
        <input type="password" autoComplete="off" value={rotating} onChange={(e) => setRotating(e.target.value)}
               placeholder="New key" aria-label={`New key for ${p.id}`} className={field} />
        <button type="submit" disabled={!rotating} className="px-3 py-1.5 text-xs border border-border rounded flex items-center gap-1 disabled:opacity-50">
          <KeyRound className="w-3 h-3" /> Rotate
        </button>
      </form>
      {open && (
        <div className="text-xs">
          <button className="text-muted underline mb-2 flex items-center gap-1"
                  onClick={async () => { try { await c.post(`${BASE}/${p.id}/models/refresh`); setModels((await c.get(`${BASE}/${p.id}/models`)).data.models); } catch (e) { setError(providerError(e, 'Could not refresh.')); } }}>
            <RefreshCw className="w-3 h-3" /> Refresh the list
          </button>
          {models && models.length === 0 ? <p className="text-muted">No models known yet.</p> : (
            <ul className="space-y-1">{(models || []).map((m) => (
              <li key={m.model} className="font-mono text-bright">{m.model}
                <span className="text-muted"> · context {m.context_window ?? 'unknown'} · tools {m.supports_tools == null ? 'unknown' : String(m.supports_tools)}</span></li>))}
            </ul>)}
        </div>
      )}
    </li>
  );
};

const Usage = ({ refreshKey }) => {
  const [data, setData] = useState(null);
  useEffect(() => { c.get(`${BASE}/usage?days=7`).then((r) => setData(r.data)).catch(() => setData(null)); }, [refreshKey]);
  if (!data) return null;
  return (
    <div>
      <p className={label}>Last 7 days (cost is an estimate from the model catalogue)</p>
      <table className="w-full text-xs" aria-label="Usage, last 7 days">
        <thead><tr className="text-muted text-left"><th>Day</th><th>Calls</th><th>Tokens in/out</th><th>Cost</th><th>Errors</th></tr></thead>
        <tbody>{data.days.map((d) => (
          <tr key={d.day}><td className="font-mono">{d.day}</td><td>{d.calls}</td><td>{d.tokens_in}/{d.tokens_out}</td><td>{costText(d)}</td><td>{d.errors}</td></tr>))}
        </tbody>
      </table>
    </div>
  );
};

const ModelProvidersPanel = ({ isAdmin }) => {
  const [list, setList] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  const load = useCallback(async () => { setList((await c.get(BASE)).data); setTick((t) => t + 1); }, []);
  useEffect(() => {
    if (!isAdmin) return undefined;
    let alive = true;
    c.get(BASE).then((r) => { if (alive) { setList(r.data); setTick((t) => t + 1); } })
      .catch((e) => { if (alive) setError(providerError(e, 'Could not load providers.')); });
    return () => { alive = false; };
  }, [isAdmin]);

  if (!isAdmin) return null;
  const applyPreset = (name) => setForm({ ...EMPTY, id: name, preset: name, kind: 'openai_compatible', base_url: 'http://localhost:20128/v1', allow_local: true, free_pool: true, levels: ['public', 'internal'] });
  const add = async (e) => {
    e.preventDefault(); setError('');
    const body = { id: form.id, kind: form.kind, base_url: form.base_url, allow_local: form.allow_local,
                   free_pool: form.free_pool, sensitivity_allowed: form.levels };
    if (form.api_key) body.api_key = form.api_key;
    if (form.preset) body.preset = form.preset;
    try { await c.post(BASE, body); setForm(EMPTY); await load(); } catch (err) { setError(providerError(err, 'Could not add the provider.')); }
  };

  return (
    <section className="panel overflow-hidden" aria-labelledby="providers-h">
      <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
        <Server className="w-4 h-4 mr-2 text-accent" />
        <h3 id="providers-h" className="text-xs font-bold text-muted uppercase tracking-widest">Model providers (Velaris)</h3>
      </div>
      <div className="p-6 space-y-6">
        <p className="text-[11px] text-muted">
          Where Velaris sends model calls, and what data each provider may see. A call whose data no enabled provider accepts is refused, never rerouted.
          Keys are stored encrypted and are never shown again after saving.
        </p>
        {error && <p role="alert" className="text-xs text-danger">{error}</p>}
        {list && list.providers.length === 0 && <p className="text-xs text-muted">No providers added yet.</p>}
        <ul className="space-y-3">{(list?.providers || []).map((p) => <ProviderRow key={p.id} p={p} onChanged={load} setError={setError} />)}</ul>
        <form onSubmit={add} className="space-y-3 border-t border-border pt-4" aria-label="Add provider">
          <div className="flex items-center justify-between">
            <p className={label}>Add a provider</p>
            {(list?.presets || []).map((n) => (
              <button key={n} type="button" onClick={() => applyPreset(n)} className="text-xs text-accent underline">Use the {n} preset</button>))}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className={label} htmlFor="prov-id">Name</label>
              <input id="prov-id" className={field} value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} placeholder="e.g. company-gateway" /></div>
            <div><label className={label} htmlFor="prov-kind">Kind</label>
              <select id="prov-kind" className={field} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                {(list?.kinds || ['openai_compatible']).map((k) => <option key={k}>{k}</option>)}</select></div>
          </div>
          <div><label className={label} htmlFor="prov-url">Base URL</label>
            <input id="prov-url" className={field} value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://host/v1" /></div>
          <div><label className={label} htmlFor="prov-key">API key</label>
            <input id="prov-key" type="password" autoComplete="off" className={field} value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} /></div>
          <div><p className={label}>May see</p>
            <Levels levels={form.levels} freePool={form.free_pool} idPrefix="new" onChange={(l) => setForm({ ...form, levels: l })} /></div>
          <div className="flex gap-4 text-xs text-bright">
            <label className="flex items-center gap-1"><input type="checkbox" checked={form.allow_local} onChange={(e) => setForm({ ...form, allow_local: e.target.checked })} /> allow local address</label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={form.free_pool}
              onChange={(e) => setForm({ ...form, free_pool: e.target.checked, levels: e.target.checked ? form.levels.filter((l) => l !== 'restricted') : form.levels })} /> free pool</label>
          </div>
          <button type="submit" disabled={!form.id} className="px-4 py-2 bg-accent text-white text-xs font-bold rounded flex items-center gap-1 disabled:opacity-50"><Plus className="w-3 h-3" /> Add</button>
        </form>
        <Usage refreshKey={tick} />
      </div>
    </section>
  );
};

export default ModelProvidersPanel;
