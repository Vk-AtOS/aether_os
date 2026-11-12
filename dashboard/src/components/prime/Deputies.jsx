import React, { useState } from 'react';
import { Users } from 'lucide-react';
import { api } from '../../api';
import EmptyState from '../EmptyState';
import { confirmAction } from '../confirmAction';
import { primeApi, errText, useLoad } from './primeApi';
import { Spinner, ErrorBox, Pill } from './parts';
import { AUTONOMY, STATE_STYLE, fmtDate, money } from './labels';

const describe = (e) => {
  const p = e.payload;
  const what = e.action.replace('prime.', '');
  const detail = [p.type, p.status, p.execution, p.outcome].filter(Boolean).join(' · ');
  return detail ? `${what} · ${detail}` : what;
};

const DelegationCard = ({ d, who, onRevoke }) => (
  <li className="bg-panel border border-border rounded-xl">
    <div className="px-5 py-4 flex flex-wrap items-center gap-x-4 gap-y-2">
      <Pill className={STATE_STYLE[d.state]}>{d.state}</Pill>
      <div className="flex-1 min-w-[14rem]">
        <p className="text-sm text-bright font-mono">{d.scope.join(', ')}</p>
        <p className="text-xs text-muted mt-0.5 break-all">
          {who} · {AUTONOMY[d.autonomy]?.label} · until {fmtDate(d.valid_until)}
          {d.max_amount && ` · up to ${money(d.max_amount, d.currency)}`}
        </p>
      </div>
      {onRevoke && (d.state === 'active' || d.state === 'scheduled') && (
        <button onClick={() => onRevoke(d)}
                className="px-3 py-1.5 text-xs font-bold text-danger border border-danger/40 hover:bg-danger/10 rounded-lg">
          Revoke
        </button>
      )}
    </div>
    <div className="border-t border-border px-5 py-3">
      {d.activity.length === 0 ? (
        <p className="text-xs text-muted">Nothing has been done under this delegation.</p>
      ) : (
        <ul className="space-y-1.5">
          {d.activity.map((e) => (
            <li key={e.seq} className="flex items-baseline gap-3 text-xs">
              <span className="font-mono text-muted tabular-nums shrink-0">#{e.seq}</span>
              <span className="text-bright flex-1 min-w-0 break-all">
                <span className="font-mono">{e.actor}</span> <span className="text-muted">{describe(e)}</span>
              </span>
              <time className="text-[10px] text-muted shrink-0">{fmtDate(e.timestamp)}</time>
            </li>
          ))}
        </ul>
      )}
    </div>
  </li>
);

const Deputies = () => {
  const { data, error, loading, reload } = useLoad(primeApi.deputies, 'Could not load delegations.');
  const [actionError, setActionError] = useState('');

  const revoke = async (d) => {
    const ok = await confirmAction(
      `Prime and ${d.deputy} stop acting under it immediately. This cannot be undone.`,
      'Revoke this delegation?',
    );
    if (!ok) return;
    setActionError('');
    try {
      await api.revokeDelegation(d.id);
      reload();
    } catch (e) {
      setActionError(errText(e, 'Could not revoke the delegation.'));
    }
  };

  if (loading && !data) return <Spinner />;
  if (!data) return <ErrorBox>{error}</ErrorBox>;

  const empty = (title, description) => (
    <div className="bg-panel border border-border rounded-xl">
      <EmptyState icon={Users} title={title} description={description} />
    </div>
  );

  return (
    <div className="space-y-8">
      {(error || actionError) && <ErrorBox>{actionError || error}</ErrorBox>}
      <section className="space-y-3" aria-labelledby="given-h">
        <h2 id="given-h" className="text-sm font-bold text-bright">You delegated</h2>
        {data.given.length === 0
          ? empty('You have not delegated anything', 'Grant a delegation on the Delegations tab before you are away.')
          : <ul className="space-y-2">{data.given.map((d) => (
              <DelegationCard key={d.id} d={d} who={`deputy ${d.deputy}`} onRevoke={revoke} />))}</ul>}
      </section>
      <section className="space-y-3" aria-labelledby="received-h">
        <h2 id="received-h" className="text-sm font-bold text-bright">Delegated to you as deputy</h2>
        {data.received.length === 0
          ? empty('Nobody has named you as deputy', 'When a colleague does, their requests appear in your inbox while the delegation is active.')
          : <ul className="space-y-2">{data.received.map((d) => (
              <DelegationCard key={d.id} d={d} who={`from ${d.grantor}`} />))}</ul>}
      </section>
    </div>
  );
};

export default Deputies;
