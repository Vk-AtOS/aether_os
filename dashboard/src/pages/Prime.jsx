import React from 'react';
import { NavLink, Navigate, useParams } from 'react-router-dom';
import { BrainCircuit, ShieldCheck, ShieldAlert } from 'lucide-react';
import { api } from '../api';
import { useRole } from '../hooks/useRole';
import DelegationsPanel from '../components/prime/DelegationsPanel';
import Inbox from '../components/prime/Inbox';
import Deputies from '../components/prime/Deputies';
import LimitsSettings from '../components/prime/LimitsSettings';
import LedgerBrowser from '../components/prime/LedgerBrowser';
import { primeApi, useLoad } from '../components/prime/primeApi';

const TABS = [
  { key: 'delegations', label: 'Delegations', path: '/prime', Panel: DelegationsPanel },
  { key: 'inbox',       label: 'Inbox',       path: '/prime/inbox', Panel: Inbox },
  { key: 'deputies',    label: 'Deputies',    path: '/prime/deputies', Panel: Deputies },
  { key: 'limits',      label: 'Limits',      path: '/prime/limits', Panel: LimitsSettings, adminOnly: true },
  { key: 'ledger',      label: 'Ledger',      path: '/prime/ledger', Panel: LedgerBrowser },
];

const Prime = () => {
  const { tab = 'delegations' } = useParams();
  const { isAdmin } = useRole();
  const { data: ledger } = useLoad(api.verifyLedger);
  const { data: counts } = useLoad(primeApi.inboxCount);   // badge: what this person may decide now

  const tabs = TABS.filter((t) => !t.adminOnly || isAdmin);
  const current = tabs.find((t) => t.key === tab);
  if (!current) return <Navigate to="/prime" replace />;
  const { Panel } = current;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
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

      <nav className="flex gap-1 border-b border-border" aria-label="Prime sections">
        {tabs.map((t) => (
          <NavLink
            key={t.key} to={t.path} end
            className={({ isActive }) => `px-4 py-2 text-xs font-bold border-b-2 -mb-px ${
              isActive ? 'border-accent text-bright' : 'border-transparent text-muted hover:text-bright'}`}
          >
            {t.label}
            {t.key === 'inbox' && counts?.pending > 0 && (
              <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] ${counts.urgent > 0 ? 'bg-yellow-400/20 text-yellow-400' : 'bg-accent/20 text-bright'}`}
                    aria-label={`${counts.pending} waiting${counts.urgent ? `, ${counts.urgent} urgent` : ''}`}>
                {counts.pending}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      <Panel />
    </div>
  );
};

export default Prime;
