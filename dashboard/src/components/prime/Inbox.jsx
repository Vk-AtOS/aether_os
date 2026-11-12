import React, { useCallback, useState } from 'react';
import { Inbox as InboxIcon, Loader2 } from 'lucide-react';
import EmptyState from '../EmptyState';
import { confirmAction } from '../confirmAction';
import { primeApi, errText, useLoad } from './primeApi';
import { Spinner, ErrorBox, Pill, Facts, Json, inputClass, labelClass } from './parts';
import { STATE_STYLE, EXECUTION, fmtDate, money } from './labels';

const FILTERS = [['pending', 'Waiting'], ['decided', 'Decided'], ['expired', 'Expired'], ['all', 'All']];
const PAGE = 20;

// Everything the decision covers, and the two buttons. The hash sent with the
// decision is the one of the request as it is shown here.
const RequestDetail = ({ r, onDone }) => {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const a = r.action;
  const execution = r.execution && EXECUTION[r.execution.status];

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
    } catch (e) {
      setError(errText(e, 'The decision was not recorded.'));
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="border-t border-border px-5 py-4 space-y-4">
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
        ['Why it is here', r.why],
        ['Deputy', r.deputy],
        ['Asked', fmtDate(r.created_at)],
        ['Expires', fmtDate(r.expires_at)],
        ['Request hash', r.request_hash],
        ['Decided by', r.decided_by],
        ['Decided', fmtDate(r.decided_at)],
        ['Reason given', r.decision_reason],
      ]} />
      {a.type === 'velaris.flow.call' ? (
        <div className="space-y-2">
          <p className={labelClass}>Velaris step</p>
          <Facts rows={[['Tool', a.params.tool], ['Run', a.params.run_id], ['Why it waits', a.params.reason],
                        ['Call hash', a.params.call_hash]]} />
          <p className={labelClass}>Arguments</p>
          <Json value={a.params.args} />
        </div>
      ) : (
        <div>
          <p className={labelClass}>Arguments</p>
          <Json value={a.params} />
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
      {r.can_decide && (
        <div className="space-y-3">
          {!r.can_approve && <p className="text-xs text-yellow-400">It can only be rejected: {r.blocked_reason}</p>}
          <div>
            <label htmlFor={`reason-${r.id}`} className={labelClass}>Reason (optional)</label>
            <input id={`reason-${r.id}`} value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} className={inputClass} />
          </div>
          {error && <p role="alert" className="text-xs text-danger">{error}</p>}
          <div className="flex gap-2">
            <button onClick={() => decide(true)} disabled={Boolean(busy) || !r.can_approve}
                    className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg">
              {busy === 'approve' && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Approve
            </button>
            <button onClick={() => decide(false)} disabled={Boolean(busy)}
                    className="flex items-center gap-2 px-4 py-2 text-danger border border-danger/40 hover:bg-danger/10 disabled:opacity-50 text-xs font-bold rounded-lg">
              {busy === 'reject' && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Reject
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

const Inbox = () => {
  const [state, setState] = useState('pending');
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(null);
  // Requests decided on this screen stay where they are, showing their result,
  // until the list is loaded again.
  const [decided, setDecided] = useState({});
  const fetcher = useCallback(() => primeApi.inbox({ state, offset, limit: PAGE }), [state, offset]);
  const { data, error, loading } = useLoad(fetcher, 'Could not load your inbox.');

  const pick = (s) => { setState(s); setOffset(0); setOpen(null); setDecided({}); };
  const requests = (data?.requests || []).map((r) => decided[r.id] || r);

  return (
    <section className="space-y-4" aria-labelledby="inbox-h">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="inbox-h" className="text-sm font-bold text-bright">Requests for your decision</h2>
        <div className="flex gap-1" role="group" aria-label="Filter requests">
          {FILTERS.map(([key, label]) => (
            <button key={key} onClick={() => pick(key)} aria-pressed={state === key}
                    className={`px-3 py-1.5 text-xs font-bold rounded-lg border ${
                      state === key ? 'border-accent bg-accent/15 text-bright' : 'border-border text-muted hover:text-bright'}`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && <ErrorBox>{error}</ErrorBox>}
      {loading && !data ? <Spinner /> : requests.length === 0 && !error ? (
        <div className="bg-panel border border-border rounded-xl">
          <EmptyState
            icon={InboxIcon}
            title={state === 'pending' ? 'Nothing is waiting for you' : 'Nothing here'}
            description="Requests appear here when Prime needs a decision from you, as the owner or as someone's deputy."
          />
        </div>
      ) : (
        <ul className="space-y-2">
          {requests.map((r) => (
            <li key={r.id} className="bg-panel border border-border rounded-xl">
              <button onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id}
                      className="w-full text-left px-5 py-4 flex flex-wrap items-center gap-x-4 gap-y-2">
                <Pill className={STATE_STYLE[r.state]}>{r.state}</Pill>
                <div className="flex-1 min-w-[14rem]">
                  <p className="text-sm text-bright font-mono">
                    {r.action.type}{r.action.amount && ` · ${money(r.action.amount, r.action.currency)}`}
                  </p>
                  <p className="text-xs text-muted mt-0.5 break-all">
                    for {r.action.on_behalf_of} · asked by {r.action.requested_by}
                    {r.state === 'pending' && ` · expires ${fmtDate(r.expires_at)}`}
                  </p>
                </div>
                {r.execution && (
                  <span className={`text-xs font-bold ${EXECUTION[r.execution.status]?.color || ''}`}>
                    {EXECUTION[r.execution.status]?.label || r.execution.status}
                  </span>
                )}
              </button>
              {open === r.id && <RequestDetail r={r} onDone={(done) => setDecided((d) => ({ ...d, [done.id]: done }))} />}
            </li>
          ))}
        </ul>
      )}

      {data && data.total > PAGE && (
        <div className="flex items-center justify-between text-xs text-muted">
          <span>{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
          <div className="flex gap-2">
            <button onClick={() => setOffset(Math.max(0, offset - PAGE))} disabled={offset === 0}
                    className="px-3 py-1.5 border border-border rounded-lg disabled:opacity-40">Previous</button>
            <button onClick={() => setOffset(offset + PAGE)} disabled={offset + PAGE >= data.total}
                    className="px-3 py-1.5 border border-border rounded-lg disabled:opacity-40">Next</button>
          </div>
        </div>
      )}
    </section>
  );
};

export default Inbox;
