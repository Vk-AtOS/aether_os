import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { confirmAction } from '../confirmAction';
import { primeApi, errText, useLoad } from './primeApi';
import { Spinner, ErrorBox, inputClass, labelClass } from './parts';
import { money } from './labels';

const LimitsForm = ({ limits, onSaved }) => {
  const [ceiling, setCeiling] = useState(limits.payment_ceiling);
  const [days, setDays] = useState(String(limits.max_delegation_days));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const unchanged = Number(ceiling) === Number(limits.payment_ceiling) && Number(days) === limits.max_delegation_days;

  const submit = async (e) => {
    e.preventDefault();
    setError(''); setSaved(false);
    const ok = await confirmAction(
      `Payment ceiling ${money(ceiling, limits.currency)}, longest delegation ${days} days. This applies to everyone in the organisation at once and is recorded in the ledger under your name.`,
      'Change Prime limits?',
    );
    if (!ok) return;
    setSaving(true);
    try {
      await primeApi.setLimits({ payment_ceiling: ceiling, max_delegation_days: Number(days) });
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(errText(err, 'The limits were not changed.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="bg-panel border border-border rounded-xl px-5 py-5 space-y-5" aria-labelledby="limits-h">
      <div>
        <h2 id="limits-h" className="text-sm font-bold text-bright">Limits for this organisation</h2>
        <p className="text-xs text-muted mt-1">
          Prime refuses any payment above the ceiling and nobody can grant a longer delegation, whatever a delegation says.
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label htmlFor="limit-ceiling" className={labelClass}>Payment ceiling ({limits.currency})</label>
          <input id="limit-ceiling" type="number" required min="1" max={limits.hard_payment_ceiling} step="1"
                 disabled={!limits.can_edit} value={ceiling} onChange={(e) => setCeiling(e.target.value)}
                 className={`${inputClass} disabled:opacity-60`} />
          <p className="text-xs text-muted mt-1.5">Cannot be above {money(limits.hard_payment_ceiling, limits.currency)}.</p>
        </div>
        <div>
          <label htmlFor="limit-days" className={labelClass}>Longest delegation (days)</label>
          <input id="limit-days" type="number" required min="1" max={limits.hard_max_delegation_days} step="1"
                 disabled={!limits.can_edit} value={days} onChange={(e) => setDays(e.target.value)}
                 className={`${inputClass} disabled:opacity-60`} />
          <p className="text-xs text-muted mt-1.5">Cannot be above {limits.hard_max_delegation_days} days. Existing delegations keep their dates.</p>
        </div>
      </div>
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      {saved && <p role="status" className="text-xs text-emerald-400">Limits changed.</p>}
      {limits.can_edit ? (
        <button type="submit" disabled={saving || unchanged}
                className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg">
          {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Save limits
        </button>
      ) : (
        <p className="text-xs text-muted">Only an organisation admin can change these.</p>
      )}
    </form>
  );
};

const LimitsSettings = () => {
  const { data, error, loading, reload } = useLoad(primeApi.getLimits, 'Could not load the limits.');
  if (loading && !data) return <Spinner />;
  if (!data) return <ErrorBox>{error}</ErrorBox>;
  // Keyed on the stored values so the form starts from them again after a save.
  return <LimitsForm key={`${data.payment_ceiling}-${data.max_delegation_days}`} limits={data} onSaved={reload} />;
};

export default LimitsSettings;
