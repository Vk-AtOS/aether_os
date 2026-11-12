import React, { useCallback, useState } from 'react';
import { ScrollText, ShieldCheck, ShieldAlert } from 'lucide-react';
import { api } from '../../api';
import EmptyState from '../EmptyState';
import { primeApi, useLoad } from './primeApi';
import { Spinner, ErrorBox, Facts, Json, inputClass, labelClass } from './parts';
import { fmtDate } from './labels';
import LedgerAdmin from './LedgerAdmin';

const PAGE = 50;
const EMPTY = { actor: '', event: '', since: '', until: '' };

// One entry with its link to the entry before it.
const EntryDetail = ({ seq }) => {
  const fetcher = useCallback(() => primeApi.ledgerEntry(seq), [seq]);
  const { data, error, loading } = useLoad(fetcher, 'Could not load this entry.');
  if (loading && !data) return <div className="border-t border-border"><Spinner /></div>;
  if (!data) return <div className="border-t border-border p-4"><ErrorBox>{error}</ErrorBox></div>;
  const ok = data.link_ok && data.hash_ok;
  return (
    <div className="border-t border-border px-5 py-4 space-y-4">
      <p className={`text-xs font-bold flex items-center gap-2 ${ok ? 'text-emerald-400' : 'text-danger'}`}>
        {ok ? <ShieldCheck className="w-4 h-4" aria-hidden="true" /> : <ShieldAlert className="w-4 h-4" aria-hidden="true" />}
        {ok ? 'Linked to the entry before it, and unchanged'
          : !data.hash_ok ? 'This entry does not match its own hash: it was changed after it was written'
          : 'This entry does not link to the entry before it'}
      </p>
      <Facts rows={[
        ['Entry', `#${data.seq}`],
        ['Written', new Date(data.timestamp * 1000).toISOString()],
        ['Actor', data.actor],
        ['Event', data.action],
        ['This entry’s hash', data.entry_hash],
        ['Previous hash stored', data.prev_hash],
        [data.previous.seq ? `Hash of entry #${data.previous.seq}` : 'Start of the ledger', data.previous.entry_hash],
      ]} />
      <div>
        <p className={labelClass}>Recorded content</p>
        <Json value={data.payload} />
      </div>
    </div>
  );
};

const LedgerBrowser = () => {
  const [draft, setDraft] = useState(EMPTY);
  const [filters, setFilters] = useState(EMPTY);
  const [before, setBefore] = useState(null);
  const [open, setOpen] = useState(null);

  const fetcher = useCallback(() => primeApi.ledgerEntries({
    limit: PAGE,
    actor: filters.actor || undefined,
    event: filters.event || undefined,
    since: filters.since ? new Date(filters.since).toISOString() : undefined,
    until: filters.until ? new Date(filters.until).toISOString() : undefined,
    before: before || undefined,
  }), [filters, before]);
  const { data, error, loading } = useLoad(fetcher, 'Could not load the ledger.');
  const { data: verify, error: verifyError } = useLoad(api.verifyLedger, 'The ledger check could not be run.');

  const apply = (e) => { e.preventDefault(); setBefore(null); setOpen(null); setFilters(draft); };
  const field = (key) => ({ value: draft[key], onChange: (e) => setDraft({ ...draft, [key]: e.target.value }) });
  const entries = data?.entries || [];

  return (
    <section className="space-y-4" aria-labelledby="ledger-h">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="ledger-h" className="text-sm font-bold text-bright">Ledger</h2>
          <p className="text-xs text-muted mt-1">
            Read-only. {data && !data.whole_org
              ? 'You see the entries you made yourself; organisation admins see the whole organisation.'
              : 'Every recorded action of this organisation, newest first.'}
          </p>
        </div>
        {verify && (
          <p className={`flex items-center gap-2 text-xs font-bold ${verify.ok ? 'text-emerald-400' : 'text-danger'}`}>
            {verify.ok ? <ShieldCheck className="w-4 h-4" aria-hidden="true" /> : <ShieldAlert className="w-4 h-4" aria-hidden="true" />}
            {verify.ok ? `Your organisation’s ledger intact · ${verify.entries_checked} entries` : `Ledger broken at entry ${verify.broken_seq}: ${verify.reason}`}
          </p>
        )}
        {verifyError && <p className="text-xs text-danger">{verifyError}</p>}
      </div>

      <LedgerAdmin isAdmin={Boolean(data?.whole_org)} />

      <form onSubmit={apply} className="bg-panel border border-border rounded-xl px-5 py-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_1fr_auto] gap-3 items-end">
        <div>
          <label htmlFor="ledger-actor" className={labelClass}>Actor</label>
          <input id="ledger-actor" placeholder="user id or prime" className={inputClass} {...field('actor')} />
        </div>
        <div>
          <label htmlFor="ledger-event" className={labelClass}>Event type</label>
          <input id="ledger-event" placeholder="prime.approval" className={inputClass} {...field('event')} />
        </div>
        <div>
          <label htmlFor="ledger-since" className={labelClass}>From</label>
          <input id="ledger-since" type="datetime-local" className={inputClass} {...field('since')} />
        </div>
        <div>
          <label htmlFor="ledger-until" className={labelClass}>To</label>
          <input id="ledger-until" type="datetime-local" className={inputClass} {...field('until')} />
        </div>
        <button type="submit" className="px-4 py-2 border border-border hover:border-accent text-bright text-xs font-bold rounded-lg">Apply</button>
      </form>

      {error && <ErrorBox>{error}</ErrorBox>}
      {loading && !data ? <Spinner /> : entries.length === 0 && !error ? (
        <div className="bg-panel border border-border rounded-xl">
          <EmptyState icon={ScrollText} title="No entries match"
                      description="Change the filters, or go back to the newest entries." />
        </div>
      ) : (
        <ul className="bg-panel border border-border rounded-xl divide-y divide-border">
          {entries.map((e) => (
            <li key={e.seq}>
              <button onClick={() => setOpen(open === e.seq ? null : e.seq)} aria-expanded={open === e.seq}
                      className="w-full text-left px-5 py-3 flex items-baseline gap-3 hover:bg-surface/50">
                <span className="text-[10px] font-mono text-muted tabular-nums shrink-0 w-12">#{e.seq}</span>
                <span className="text-xs text-bright font-mono flex-1 min-w-0 break-all">{e.action}</span>
                <span className="text-xs text-muted font-mono truncate max-w-[14rem]">{e.actor}</span>
                <time className="text-[10px] text-muted shrink-0">{fmtDate(e.timestamp)}</time>
              </button>
              {open === e.seq && <EntryDetail seq={e.seq} />}
            </li>
          ))}
        </ul>
      )}

      <div className="flex justify-end gap-2 text-xs text-muted">
        <button onClick={() => { setBefore(null); setOpen(null); }} disabled={!before}
                className="px-3 py-1.5 border border-border rounded-lg disabled:opacity-40">Newest</button>
        <button onClick={() => { setBefore(data.next_before); setOpen(null); }} disabled={!data?.next_before}
                className="px-3 py-1.5 border border-border rounded-lg disabled:opacity-40">Older</button>
      </div>
    </section>
  );
};

export default LedgerBrowser;
