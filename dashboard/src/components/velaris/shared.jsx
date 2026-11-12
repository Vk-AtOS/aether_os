import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { CloudOff, Clock, Loader2 } from 'lucide-react';
import { ErrorBox, Spinner, inputClass, labelClass } from '../prime/parts';
import { btn } from './velarisApi';

export const DownBanner = () => (
  <div role="alert" className="flex items-start gap-3 bg-panel border border-warning/40 rounded-xl px-5 py-4 text-sm">
    <CloudOff className="w-4 h-4 text-warning mt-0.5 shrink-0" aria-hidden="true" />
    <div>
      <p className="font-semibold text-bright">Velaris is not reachable</p>
      <p className="text-muted text-xs mt-1">Nothing here can load or change until it is back. Try again in a moment; ask an owner to check the Velaris connection if this stays.</p>
    </div>
  </div>
);

// loading / down / error / empty in one place: <LoadView q={useVelaris(...)} empty={...}>{(data) => ...}</LoadView>
export const LoadView = ({ q, children, isEmpty, emptyText = 'Nothing here yet.' }) => {
  if (q.loading) return <Spinner />;
  if (q.down) return <DownBanner />;
  if (q.error) return <ErrorBox>{q.error}</ErrorBox>;
  if (q.data == null || (isEmpty && isEmpty(q.data))) return <p className="text-sm text-muted py-6 text-center">{emptyText}</p>;
  return children(q.data);
};

export const Notice = ({ tone = 'info', children }) => {
  const cls = { info: 'border-sky-400/30 text-sky-300', warn: 'border-warning/40 text-warning', ok: 'border-success/40 text-success' }[tone];
  return <div role="status" className={`bg-panel border rounded-lg px-4 py-3 text-xs ${cls}`}>{children}</div>;
};

export const PendingNotice = ({ run }) => (
  <Notice tone="warn">
    <Clock className="w-3.5 h-3.5 inline mr-1.5" aria-hidden="true" />
    Submitted, not done yet: this action needs approval before it takes effect{run?.run_id ? ` (run ${run.run_id})` : ''}.
    Decide it in <Link to="/prime/inbox" className="underline font-bold">Prime</Link>.
  </Notice>
);

export const Tabs = ({ tabs, value, onChange }) => (
  <div role="tablist" className="flex flex-wrap gap-1 border-b border-border">
    {tabs.map(([id, label]) => (
      <button key={id} role="tab" aria-selected={value === id} onClick={() => onChange(id)}
        className={`px-3 py-2 text-xs font-bold ${value === id ? 'text-bright border-b-2 border-accent' : 'text-muted hover:text-bright'}`}>
        {label}
      </button>
    ))}
  </div>
);

export const Card = ({ title, children, actions }) => (
  <section className="bg-panel border border-border rounded-xl p-4 space-y-3">
    {(title || actions) && (
      <div className="flex items-center justify-between gap-2">
        {title && <h3 className="text-xs font-bold text-muted uppercase tracking-wider">{title}</h3>}
        {actions}
      </div>
    )}
    {children}
  </section>
);

export const PageHead = ({ icon: Icon, title, sub, right }) => (
  <header className="flex items-start justify-between gap-3">
    <div className="flex items-center gap-3">
      {Icon && <Icon className="w-5 h-5 text-accent" aria-hidden="true" />}
      <div>
        <h1 className="text-xl font-bold text-bright">{title}</h1>
        {sub && <p className="text-xs text-muted mt-0.5">{sub}</p>}
      </div>
    </div>
    {right}
  </header>
);

// Rows as a table. cols: [[header, row => node]]
export const Table = ({ rows, cols, onRow, empty = 'Nothing here yet.' }) => (
  rows.length === 0 ? <p className="text-sm text-muted py-4 text-center">{empty}</p> : (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead><tr>{cols.map(([h]) => <th key={h} className="text-left text-[10px] uppercase tracking-wider text-muted font-bold py-2 pr-4">{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id ?? i} onClick={onRow ? () => onRow(r) : undefined}
              className={`border-t border-border ${onRow ? 'cursor-pointer hover:bg-surface/60' : ''}`}>
              {cols.map(([h, f]) => <td key={h} className="py-2 pr-4 text-bright align-top">{f(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
);

// A small form from field specs: {name, label, type: text|number|textarea|select|date|checkbox|list|json, options, required, help}
// onSubmit gets the typed values (numbers as numbers, list as an array, json parsed). Empty optional fields are left out.
export const SpecForm = ({ fields, submitLabel, onSubmit, busy, initial = {} }) => {
  const [v, setV] = useState(() => Object.fromEntries(fields.map((f) => [f.name, initial[f.name] ?? (f.type === 'checkbox' ? false : '')])));
  const [err, setErr] = useState('');
  const submit = (e) => {
    e.preventDefault();
    const out = {};
    try {
      for (const f of fields) {
        const raw = v[f.name];
        if (f.type === 'checkbox') { out[f.name] = raw; continue; }
        if (raw === '' || raw == null) { if (f.required) throw new Error(`${f.label} is required`); continue; }
        if (f.type === 'number') out[f.name] = Number(raw);
        else if (f.type === 'list') out[f.name] = String(raw).split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
        else if (f.type === 'json') { try { out[f.name] = JSON.parse(raw); } catch { throw new Error(`${f.label} is not valid JSON`); } }
        else out[f.name] = raw;
      }
    } catch (x) { setErr(x.message); return; }
    setErr('');
    onSubmit(out);
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {fields.map((f) => (
          <label key={f.name} className={f.type === 'textarea' || f.type === 'json' ? 'sm:col-span-2' : ''}>
            <span className={labelClass}>{f.label}{f.required && ' *'}</span>
            {f.type === 'textarea' || f.type === 'json' ? (
              <textarea rows={f.type === 'json' ? 5 : 3} className={`${inputClass} ${f.type === 'json' ? 'font-mono text-xs' : ''}`} value={v[f.name]}
                onChange={(e) => setV({ ...v, [f.name]: e.target.value })} placeholder={f.placeholder} />
            ) : f.type === 'select' ? (
              <select className={inputClass} value={v[f.name]} onChange={(e) => setV({ ...v, [f.name]: e.target.value })}>
                <option value="">{f.required ? 'Choose' : 'None'}</option>
                {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : f.type === 'checkbox' ? (
              <input type="checkbox" checked={v[f.name]} onChange={(e) => setV({ ...v, [f.name]: e.target.checked })} />
            ) : (
              <input type={f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text'} step={f.type === 'number' ? 'any' : undefined}
                className={inputClass} value={v[f.name]} onChange={(e) => setV({ ...v, [f.name]: e.target.value })} placeholder={f.placeholder} />
            )}
            {f.help && <span className="text-[10px] text-muted">{f.help}</span>}
          </label>
        ))}
      </div>
      {err && <p role="alert" className="text-xs text-danger">{err}</p>}
      <button type="submit" disabled={busy} className={btn()}>
        {busy ? <Loader2 className="w-3 h-3 animate-spin inline" aria-label="Working" /> : submitLabel}
      </button>
    </form>
  );
};
