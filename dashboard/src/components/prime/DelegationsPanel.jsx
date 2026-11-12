import React, { useState } from 'react';
import { BrainCircuit, Ban } from 'lucide-react';
import { api } from '../../api';
import EmptyState from '../EmptyState';
import ConfirmDialog from '../ConfirmDialog';
import DelegationForm from './DelegationForm';
import ActionCheck from './ActionCheck';
import { errText, useLoad } from './primeApi';
import { Spinner, ErrorBox, Pill } from './parts';
import { AUTONOMY, OUTCOME, STATE_STYLE, fmtDate, money } from './labels';

const loadAll = () =>
  Promise.all([api.getPrimeMeta(), api.listDelegations(), api.getPrimeActivity()]).then(([m, d, a]) => ({
    data: { meta: m.data, delegations: d.data.delegations, activity: a.data.entries },
  }));

// The caller's own delegations: list, grant, test, and what Prime did for them.
const DelegationsPanel = () => {
  const { data, error, loading, reload } = useLoad(loadAll, 'Could not load Prime.');
  const [revoking, setRevoking] = useState(null);
  const [actionError, setActionError] = useState('');

  const revoke = async () => {
    const id = revoking;
    setRevoking(null);
    setActionError('');
    try {
      await api.revokeDelegation(id);
      reload();
    } catch (e) {
      setActionError(errText(e, 'Could not revoke the delegation.'));
    }
  };

  if (loading && !data) return <Spinner />;
  if (!data) return <ErrorBox>{error}</ErrorBox>;
  const { meta, delegations, activity } = data;

  return (
    <div className="space-y-8">
      {(error || actionError) && <ErrorBox>{actionError || error}</ErrorBox>}

      <section className="space-y-3" aria-labelledby="delegations-h">
        <h2 id="delegations-h" className="text-sm font-bold text-bright">Your delegations</h2>
        {delegations.length === 0 ? (
          <div className="bg-panel border border-border rounded-xl">
            <EmptyState
              icon={BrainCircuit}
              title="Prime cannot act for you yet"
              description="Without a delegation Prime refuses every action. Grant one below before you go on leave."
            />
          </div>
        ) : (
          <ul className="space-y-2">
            {delegations.map((d) => (
              <li key={d.id} className="bg-panel border border-border rounded-xl px-5 py-4 flex flex-wrap items-center gap-x-4 gap-y-2">
                <Pill className={STATE_STYLE[d.state]}>{d.state}</Pill>
                <div className="flex-1 min-w-[14rem]">
                  <p className="text-sm text-bright font-mono">{d.scope.join(', ')}</p>
                  <p className="text-xs text-muted mt-0.5">
                    {AUTONOMY[d.autonomy]?.label} · until {fmtDate(d.valid_until)} · deputy {d.deputy}
                    {d.max_amount && ` · up to ${money(d.max_amount, d.currency)}`}
                  </p>
                </div>
                {(d.state === 'active' || d.state === 'scheduled') && (
                  <button
                    onClick={() => setRevoking(d.id)}
                    className="px-3 py-1.5 text-xs font-bold text-danger border border-danger/40 hover:bg-danger/10 rounded-lg"
                  >
                    Revoke
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <DelegationForm meta={meta} onCreated={reload} />
      <ActionCheck meta={meta} onChecked={reload} />

      <section className="bg-panel border border-border rounded-xl px-5 py-4" aria-labelledby="never-h">
        <h2 id="never-h" className="text-sm font-bold text-bright flex items-center gap-2">
          <Ban className="w-4 h-4 text-danger" aria-hidden="true" /> Prime never does these, whatever you delegate
        </h2>
        <p className="text-xs font-mono text-muted mt-2 leading-relaxed">{meta.never.join(' · ')}</p>
        <p className="text-xs text-muted mt-2">
          Payments above {money(meta.payment_ceiling, meta.currency)} are also always refused.
        </p>
      </section>

      <section className="space-y-3" aria-labelledby="activity-h">
        <h2 id="activity-h" className="text-sm font-bold text-bright">Activity on your behalf</h2>
        {activity.length === 0 ? (
          <p className="text-sm text-muted">Nothing yet. Every request and decision will appear here.</p>
        ) : (
          <ul className="bg-panel border border-border rounded-xl divide-y divide-border">
            {activity.map((e) => {
              const outcome = OUTCOME[e.payload.outcome];
              return (
                <li key={e.seq} className="px-5 py-3 flex items-baseline gap-3">
                  <span className="text-[10px] font-mono text-muted tabular-nums shrink-0">#{e.seq}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-bright">
                      <span className="font-mono">{e.action.replace('prime.', '')}</span>
                      {e.payload.type && <span className="text-muted"> · {e.payload.type}</span>}
                      {outcome && <span className={`ml-2 font-bold ${outcome.color}`}>{outcome.label}</span>}
                    </p>
                    {e.payload.reason && <p className="text-xs text-muted mt-0.5 break-words">{e.payload.reason}</p>}
                  </div>
                  <time className="text-[10px] text-muted shrink-0">{fmtDate(e.timestamp)}</time>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={Boolean(revoking)}
        danger
        title="Revoke this delegation?"
        message="Prime stops acting under it immediately. This cannot be undone; grant a new one if you need it again."
        onConfirm={revoke}
        onCancel={() => setRevoking(null)}
      />
    </div>
  );
};

export default DelegationsPanel;
