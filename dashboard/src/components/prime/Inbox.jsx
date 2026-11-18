import React, { useCallback, useState } from 'react';
import { Inbox as InboxIcon } from 'lucide-react';
import EmptyState from '../EmptyState';
import { primeApi, useLoad } from './primeApi';
import { Spinner, ErrorBox, Pill } from './parts';
import RequestDetail from './RequestDetail';
import { STATE_STYLE, URGENCY_STYLE, EXECUTION, fmtDate, money } from './labels';

const FILTERS = [['pending', 'Waiting'], ['decided', 'Decided'], ['expired', 'Expired'], ['all', 'All']];
const PAGE = 20;

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
                {r.urgency && r.urgency !== 'normal' && <Pill className={URGENCY_STYLE[r.urgency]}>{r.urgency}</Pill>}
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
