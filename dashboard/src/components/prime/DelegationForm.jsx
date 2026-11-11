import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { api } from '../../api';
import { AUTONOMY } from './labels';

const inputClass =
  'w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent';
const labelClass = 'text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block';

// datetime-local wants "YYYY-MM-DDTHH:mm" in local time.
const localInput = (date) => {
  const d = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return d.toISOString().slice(0, 16);
};

const DelegationForm = ({ meta, onCreated }) => {
  const now = new Date();
  const [scope, setScope] = useState([]);
  const [autonomy, setAutonomy] = useState(2);
  const [from, setFrom] = useState(localInput(now));
  const [until, setUntil] = useState(localInput(new Date(now.getTime() + 7 * 86400000)));
  const [deputy, setDeputy] = useState('');
  const [maxAmount, setMaxAmount] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const monetary = meta.action_types.filter((a) => a.monetary && scope.includes(a.type)).length > 0;
  const toggle = (type) =>
    setScope((s) => (s.includes(type) ? s.filter((t) => t !== type) : [...s, type]));

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (scope.length === 0) return setError('Choose at least one thing Prime may do.');
    if (monetary && !maxAmount) return setError('Set an amount limit for the money actions you chose.');
    setSaving(true);
    try {
      await api.createDelegation({
        scope, autonomy, deputy: deputy.trim(),
        valid_from: new Date(from).toISOString(),
        valid_until: new Date(until).toISOString(),
        max_amount: monetary ? maxAmount : null,
      });
      setScope([]); setDeputy(''); setMaxAmount('');
      onCreated();
    } catch (err) {
      const d = err.response?.data?.detail;
      setError(typeof d === 'string' ? d : 'Could not grant the delegation. Check the dates and the deputy.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="bg-panel border border-border rounded-xl px-5 py-5 space-y-5" aria-labelledby="grant-h">
      <h2 id="grant-h" className="text-sm font-bold text-bright">Grant a delegation</h2>

      <fieldset>
        <legend className={labelClass}>Prime may</legend>
        <div className="flex flex-wrap gap-2">
          {meta.action_types.map((a) => {
            const on = scope.includes(a.type);
            return (
              <button
                type="button" key={a.type} onClick={() => toggle(a.type)} aria-pressed={on}
                className={`px-3 py-1.5 text-xs font-mono rounded-lg border transition-colors ${
                  on ? 'border-accent bg-accent/15 text-bright' : 'border-border text-muted hover:text-bright'
                }`}
              >
                {a.type}
              </button>
            );
          })}
        </div>
      </fieldset>

      <div>
        <label htmlFor="prime-autonomy" className={labelClass}>How much freedom</label>
        <select id="prime-autonomy" value={autonomy} onChange={(e) => setAutonomy(Number(e.target.value))} className={inputClass}>
          {meta.autonomy_levels.map((l) => (
            <option key={l.level} value={l.level}>{l.level} · {AUTONOMY[l.level]?.label}</option>
          ))}
        </select>
        <p className="text-xs text-muted mt-1.5">{AUTONOMY[autonomy]?.help}</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label htmlFor="prime-from" className={labelClass}>From</label>
          <input id="prime-from" type="datetime-local" required value={from} onChange={(e) => setFrom(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label htmlFor="prime-until" className={labelClass}>Until (at most {meta.max_delegation_days} days)</label>
          <input id="prime-until" type="datetime-local" required value={until} onChange={(e) => setUntil(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label htmlFor="prime-deputy" className={labelClass}>Deputy for everything else</label>
          <input id="prime-deputy" type="email" required value={deputy} onChange={(e) => setDeputy(e.target.value)}
                 placeholder="name@company.com" className={inputClass} />
        </div>
        {monetary && (
          <div>
            <label htmlFor="prime-max" className={labelClass}>Amount limit ({meta.currency})</label>
            <input id="prime-max" type="number" min="1" max={meta.payment_ceiling} step="1" value={maxAmount}
                   onChange={(e) => setMaxAmount(e.target.value)} className={inputClass} />
          </div>
        )}
      </div>

      {error && <p role="alert" className="text-xs text-danger">{error}</p>}

      <button type="submit" disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg">
        {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
        Grant delegation
      </button>
    </form>
  );
};

export default DelegationForm;
