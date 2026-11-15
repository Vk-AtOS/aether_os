import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { primeApi, errText } from './primeApi';
import { inputClass, labelClass } from './parts';
import { buildPatch, diffRows, fieldProblem, isEmptyPatch } from './editHelpers';

// Edit-before-approve. The form is generated from the fields the API says are editable for this
// action type. Saving makes a new revision: the request hash changes, so nobody can approve what
// they saw before, and the editor can never decide the request themselves.
const EditForm = ({ r, onSaved, onCancel }) => {
  const fields = r.detail.editable_fields;
  const current = { amount: r.action.amount, params: r.action.params || {} };
  const [typed, setTyped] = useState(() => Object.fromEntries(
    Object.keys(fields).map((k) => [k, k === 'amount' ? (current.amount ?? '') : String(current.params[k] ?? '')])));
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const patch = buildPatch(fields, current, typed);
  const rows = diffRows(current, patch);
  const problems = Object.entries(fields).map(([k, spec]) => fieldProblem(k, spec, typed[k])).filter(Boolean);
  const canSave = !isEmptyPatch(patch) && reason.trim() && problems.length === 0 && !busy;

  const save = async () => {
    setBusy(true); setError('');
    try {
      const res = await primeApi.edit(r.id, { request_hash: r.request_hash, reason: reason.trim(), ...patch });
      onSaved(res.data);
    } catch (e) {
      setError(errText(e, 'The edit was not saved.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="space-y-3 border border-border rounded-lg p-4" aria-label="Edit request"
          onSubmit={(e) => { e.preventDefault(); if (canSave) save(); }}>
      <p className="text-xs text-muted">
        Saving makes a new revision. Earlier approvals are reset, and because you edited it you cannot approve it yourself.
      </p>
      {Object.entries(fields).map(([name, spec]) => {
        const problem = fieldProblem(name, spec, typed[name]);
        const id = `edit-${r.id}-${name}`;
        return (
          <div key={name}>
            <label htmlFor={id} className={labelClass}>{name === 'amount' ? 'Amount (INR)' : name}</label>
            <input id={id} value={typed[name]} inputMode={spec.type === 'str' ? 'text' : 'decimal'}
                   maxLength={spec.type === 'str' ? spec.bound : undefined}
                   onChange={(e) => setTyped((t) => ({ ...t, [name]: e.target.value }))} className={inputClass}
                   aria-invalid={Boolean(problem)} />
            {problem && <p className="text-xs text-danger mt-1">{problem}</p>}
          </div>
        );
      })}
      {rows.length > 0 && (
        <table className="w-full text-xs" aria-label="Changes">
          <thead><tr className="text-muted text-left"><th>Field</th><th>Before</th><th>After</th></tr></thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.field}>
                <td className="font-mono">{x.field}</td>
                <td className="font-mono text-danger line-through break-all">{x.before}</td>
                <td className="font-mono text-emerald-400 break-all">{x.after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div>
        <label htmlFor={`edit-reason-${r.id}`} className={labelClass}>Why you are changing it (required)</label>
        <input id={`edit-reason-${r.id}`} value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)}
               className={inputClass} />
      </div>
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={!canSave}
                className="flex items-center gap-2 px-4 py-2 bg-accent disabled:opacity-50 text-white text-xs font-bold rounded-lg">
          {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Save edit
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-2 border border-border text-xs font-bold rounded-lg">Cancel</button>
      </div>
    </form>
  );
};

export default EditForm;
