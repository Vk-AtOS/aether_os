import React, { useState, useEffect, useCallback } from 'react';
import { BrainCircuit, ShieldCheck, ShieldAlert, Loader2, Ban } from 'lucide-react';
import { api } from '../api';
import EmptyState from '../components/EmptyState';
import ConfirmDialog from '../components/ConfirmDialog';
import DelegationForm from '../components/prime/DelegationForm';
import ActionCheck from '../components/prime/ActionCheck';
import { AUTONOMY, OUTCOME, fmtDate } from '../components/prime/labels';

const STATE_STYLE = {
  active:    'text-emerald-400 bg-emerald-400/10',
  scheduled: 'text-sky-400 bg-sky-400/10',
  expired:   'text-muted bg-border/20',
  revoked:   'text-danger bg-danger/10',
};

const errText = (e, fallback) => {
  const d = e.response?.data?.detail;
  return typeof d === 'string' ? d : fallback;
};

const Prime = () => {
  const [meta, setMeta] = useState(null);
  const [delegations, setDelegations] = useState([]);
  const [activity, setActivity] = useState([]);
  const [ledger, setLedger] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revoking, setRevoking] = useState(null);

  const load = useCallback(async () => {
    try {
      const [m, d, a, l] = await Promise.all([
        api.getPrimeMeta(), api.listDelegations(), api.getPrimeActivity(), api.verifyLedger(),
      ]);
      setMeta(m.data);
      setDelegations(d.data.delegations);
      setActivity(a.data.entries);
      setLedger(l.data);
      setError('');
    } catch (e) {
      setError(errText(e, 'Could not load Prime.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const revoke = async () => {
    const id = revoking;
    setRevoking(null);
    try {
      await api.revokeDelegation(id);
      await load();
    } catch (e) {
      setError(errText(e, 'Could not revoke the delegation.'));
    }
  };

  if (loading) {
    return <div className="flex justify-center py-24"><Loader2 className="w-6 h-6 animate-spin text-muted" /></div>;
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
            <BrainCircuit className="w-6 h-6 text-accent" aria-hidden="true" /> Prime
          </h1>
          <p className="text-sm text-muted mt-1 max-w-xl">
            Prime acts for you only inside a delegation you grant here. Each one is time-limited,
            names a deputy for everything outside it, and can be revoked at any moment.
          </p>
        </div>
        {ledger && (
          <div
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-bold shrink-0 ${
              ledger.ok ? 'border-emerald-400/30 text-emerald-400' : 'border-danger/40 text-danger'
            }`}
            title={ledger.ok ? 'Every ledger entry matches its hash' : ledger.reason}
          >
            {ledger.ok ? <ShieldCheck className="w-4 h-4" /> : <ShieldAlert className="w-4 h-4" />}
            {ledger.ok
              ? `Ledger intact · ${ledger.entries_checked} entries`
              : `Ledger broken at entry ${ledger.broken_seq}`}
          </div>
        )}
      </header>

      {error && (
        <div role="alert" className="bg-panel border border-danger/40 rounded-xl px-5 py-4 text-sm text-danger">{error}</div>
      )}

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
                <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded ${STATE_STYLE[d.state]}`}>
                  {d.state}
                </span>
                <div className="flex-1 min-w-[14rem]">
                  <p className="text-sm text-bright font-mono">{d.scope.join(', ')}</p>
                  <p className="text-xs text-muted mt-0.5">
                    {AUTONOMY[d.autonomy]?.label} · until {fmtDate(d.valid_until)} · deputy {d.deputy}
                    {d.max_amount && ` · up to ${d.currency} ${Number(d.max_amount).toLocaleString('en-IN')}`}
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

      {meta && <DelegationForm meta={meta} onCreated={load} />}
      {meta && <ActionCheck meta={meta} onChecked={load} />}

      {meta && (
        <section className="bg-panel border border-border rounded-xl px-5 py-4" aria-labelledby="never-h">
          <h2 id="never-h" className="text-sm font-bold text-bright flex items-center gap-2">
            <Ban className="w-4 h-4 text-danger" aria-hidden="true" /> Prime never does these, whatever you delegate
          </h2>
          <p className="text-xs font-mono text-muted mt-2 leading-relaxed">{meta.never.join(' · ')}</p>
          <p className="text-xs text-muted mt-2">
            Payments above {meta.currency} {Number(meta.payment_ceiling).toLocaleString('en-IN')} are also always refused.
          </p>
        </section>
      )}

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

export default Prime;
