import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { confirmAction } from '../confirmAction';
import { primeApi, errText } from './primeApi';
import { Spinner, Pill, Facts, Json, inputClass, labelClass } from './parts';
import { RISK_STYLE, EXECUTION, fmtDate, money } from './labels';
import EditForm from './EditForm';

const show = (v) => (v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v));

// Everything the decision covers, and the buttons. The hash sent with a decision is the one of the
// request as last loaded here; after an edit it is the new revision's hash.
const RequestDetail = ({ r: listed, onDone }) => {
  const [r, setR] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [raw, setRaw] = useState(false);
  const [reset, setReset] = useState(false);

  useEffect(() => {
    let alive = true;
    primeApi.get(listed.id)
      .then((res) => { if (alive) setR(res.data); })
      .catch((e) => { if (alive) setLoadError(errText(e, 'Could not load this request.')); });
    return () => { alive = false; };
  }, [listed.id]);

  if (loadError) return <p role="alert" className="border-t border-border px-5 py-4 text-sm text-danger">{loadError}</p>;
  if (!r) return <div className="border-t border-border"><Spinner /></div>;

  const a = r.action;
  const d = r.detail;
  const execution = r.execution && EXECUTION[r.execution.status];
  const canEdit = r.can_decide && r.state === 'pending' && Object.keys(d.editable_fields || {}).length > 0;

  const decide = async (approve) => {
    const amount = money(a.amount, a.currency);
    const ok = await confirmAction(
      approve
        ? `${r.what_will_happen} This happens as soon as you confirm${amount ? `, for ${amount}` : ''}, and it is recorded under your name.`
        : 'Nothing will be carried out. The rejection is recorded under your name.',
      approve ? `Approve ${a.type}?` : `Reject ${a.type}?`,
    );
    if (!ok) return;
    setBusy(approve ? 'approve' : 'reject'); setError('');
    try {
      const res = await (approve ? primeApi.approve : primeApi.reject)(r.id, r.request_hash, reason.trim());
      onDone(res.data);
      setR((await primeApi.get(r.id)).data);   // show the result, not the buttons, from now on
    } catch (e) {
      setError(errText(e, 'The decision was not recorded.'));
    } finally {
      setBusy('');
    }
  };

  const edited = async (view) => {
    // The edit endpoint returns the list view; reload the full one so the detail and hash are current.
    setEditing(false); setReset(true);
    try { setR((await primeApi.get(view.id)).data); } catch (e) { setError(errText(e, 'Reload to see the new revision.')); }
  };

  return (
    <div className="border-t border-border px-5 py-4 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Pill className={RISK_STYLE[d.risk_class]}>{d.risk_class} risk</Pill>
        {d.revision > 0 && <Pill className="text-sky-400 bg-sky-400/10">revision {d.revision}</Pill>}
      </div>
      {reset && (
        <p role="status" className="text-xs text-sky-400">
          Edited. Earlier approvals were reset: this is revision {d.revision}, and it needs a new decision from someone other than its editors.
        </p>
      )}
      <div>
        <p className={labelClass}>What will happen if approved</p>
        <p className="text-sm text-bright">{r.what_will_happen}</p>
      </div>
      <Facts rows={[
        ['Action', a.type],
        ['Amount', money(a.amount, a.currency)],
        ['On behalf of', a.on_behalf_of],
        ['Asked by', a.requested_by],
        ['Carried out by', r.executor],
        ['Policy', d.policy.reason],
        ['Autonomy level', d.policy.autonomy && `${d.policy.autonomy.level} (${d.policy.autonomy.name})`],
        ['Second person needed', d.policy.second_person_required ? 'yes' : 'no'],
        ['Who may decide', d.eligible_roles.join(', ')],
        ['Deputy', r.deputy],
        ['Asked', fmtDate(r.created_at)],
        ['Expires', fmtDate(r.expires_at)],
        ['Request hash', r.request_hash],
        ['Edited by', d.edited_by.join(', ')],
        ['Decided by', r.decided_by],
        ['Decided', fmtDate(r.decided_at)],
        ['Reason given', r.decision_reason],
      ]} />
      {d.money && (
        <div>
          <p className={labelClass}>Money</p>
          <Facts rows={[
            ['Amount', money(d.money.amount, d.money.currency)],
            ['Counted against', d.money.counted_against === 'delegation' ? 'the delegation limit' : 'the organisation ceiling'],
            ['Delegation limit', d.money.delegation_limit && money(d.money.delegation_limit, d.money.currency)],
            ['Within the limit', d.money.within_delegation_limit ? 'yes' : 'no'],
            ['Organisation ceiling', money(d.money.org_payment_ceiling, d.money.currency)],
          ]} />
        </div>
      )}
      {d.data_touched.length > 0 && (
        <div>
          <p className={labelClass}>Personal data in this request</p>
          <Facts rows={d.data_touched.map((x) => [`${x.field} (${x.kind})`, x.pseudonymised ? `${x.value} (hidden)` : x.value])} />
        </div>
      )}
      <div>
        <p className={labelClass}>Parameters</p>
        {raw || a.type === 'velaris.flow.call' ? <Json value={a.params} /> : (
          <Facts rows={Object.entries(a.params || {}).map(([k, v]) => [k, show(v)])} />
        )}
        {a.type !== 'velaris.flow.call' && (
          <button onClick={() => setRaw(!raw)} className="text-xs text-muted underline mt-1">{raw ? 'Show readable' : 'Show raw JSON'}</button>
        )}
      </div>
      {d.ledger.length > 0 && (
        <div>
          <p className={labelClass}>Timeline</p>
          <ol className="space-y-1 text-xs">
            {d.ledger.map((e) => (
              <li key={e.seq} className="flex flex-wrap gap-x-3">
                <span className="text-muted">{fmtDate(e.timestamp)}</span>
                <span className="font-mono text-bright">{e.action.replace('prime.', '')}</span>
                <span className="text-muted break-all">{e.actor}{e.reason ? ` · ${e.reason}` : ''}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {r.execution && (
        <div>
          <p className={labelClass}>Result</p>
          <p className={`text-sm font-bold ${execution?.color || 'text-bright'}`}>{execution?.label || r.execution.status}</p>
          {r.execution.result && <div className="mt-2"><Json value={r.execution.result} /></div>}
        </div>
      )}
      {r.state === 'expired' && <p className="text-xs text-muted">This request expired without a decision. It was not approved.</p>}
      {r.state === 'pending' && !r.can_decide && (
        <p className="text-xs text-muted">{r.blocked_reason || 'You cannot decide this request.'}</p>
      )}
      {editing && <EditForm r={r} onSaved={edited} onCancel={() => setEditing(false)} />}
      {r.can_decide && !editing && (
        <div className="space-y-3">
          {!r.can_approve && <p className="text-xs text-yellow-400">It can only be rejected: {r.blocked_reason}</p>}
          <div>
            <label htmlFor={`reason-${r.id}`} className={labelClass}>Reason (required to reject)</label>
            <input id={`reason-${r.id}`} value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} className={inputClass} />
          </div>
          {error && <p role="alert" className="text-xs text-danger">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button onClick={() => decide(true)} disabled={Boolean(busy) || !r.can_approve}
                    className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg">
              {busy === 'approve' && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Approve
            </button>
            <button onClick={() => decide(false)} disabled={Boolean(busy) || !reason.trim()}
                    title={reason.trim() ? '' : 'Give a reason to reject'}
                    className="flex items-center gap-2 px-4 py-2 text-danger border border-danger/40 hover:bg-danger/10 disabled:opacity-50 text-xs font-bold rounded-lg">
              {busy === 'reject' && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Reject
            </button>
            {canEdit && (
              <button onClick={() => setEditing(true)} disabled={Boolean(busy)}
                      className="px-4 py-2 border border-border text-xs font-bold rounded-lg hover:text-bright">Edit</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default RequestDetail;
