import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { api } from '../../api';
import { OUTCOME } from './labels';

const inputClass =
  'w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent';
const labelClass = 'text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block';

// Lets a person see what Prime would decide before they rely on a delegation.
const ActionCheck = ({ meta, onChecked }) => {
  const types = [...meta.action_types.map((a) => a.type), ...meta.never];
  const [type, setType] = useState(types[0]);
  const [amount, setAmount] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const monetary = meta.action_types.find((a) => a.type === type)?.monetary;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(''); setResult(null);
    try {
      const res = await api.checkPrimeAction({ type, amount: monetary && amount ? amount : null });
      setResult(res.data);
      onChecked();
    } catch (err) {
      const d = err.response?.data?.detail;
      setError(typeof d === 'string' ? d : 'Could not check the action.');
    } finally {
      setBusy(false);
    }
  };

  const outcome = result && OUTCOME[result.outcome];

  return (
    <form onSubmit={submit} className="bg-panel border border-border rounded-xl px-5 py-5 space-y-4" aria-labelledby="check-h">
      <div>
        <h2 id="check-h" className="text-sm font-bold text-bright">Test what Prime would do</h2>
        <p className="text-xs text-muted mt-1">Nothing is carried out. The test itself is recorded in the ledger.</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_10rem_auto] gap-3 items-end">
        <div>
          <label htmlFor="check-type" className={labelClass}>Action</label>
          <select id="check-type" value={type} onChange={(e) => setType(e.target.value)} className={`${inputClass} font-mono`}>
            {types.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="check-amount" className={labelClass}>Amount ({meta.currency})</label>
          <input id="check-amount" type="number" min="1" step="1" disabled={!monetary} value={monetary ? amount : ''}
                 onChange={(e) => setAmount(e.target.value)} className={`${inputClass} disabled:opacity-40`} />
        </div>
        <button type="submit" disabled={busy}
                className="flex items-center justify-center gap-2 px-4 py-2 border border-border hover:border-accent text-bright text-xs font-bold rounded-lg disabled:opacity-50">
          {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          Check
        </button>
      </div>
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      {result && (
        <div className="border-t border-border pt-4" aria-live="polite">
          <p className={`text-sm font-bold ${outcome?.color || 'text-bright'}`}>{outcome?.label || result.outcome}</p>
          <p className="text-xs text-muted mt-1 break-words">{result.reason}</p>
        </div>
      )}
    </form>
  );
};

export default ActionCheck;
