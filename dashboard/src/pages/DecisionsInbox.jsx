import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Inbox, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { api } from '../api';
import { apiError } from '../apiError';
import { useRole } from '../hooks/useRole';

const PAGE = 50;

// Pending pipeline decisions across every run of the organisation. Deciding calls the per-run route, which
// the server restricts to member and above; a viewer sees the list but no buttons.
const DecisionsInbox = () => {
  const { canWrite } = useRole();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [more, setMore] = useState(false);

  const load = useCallback((offset = 0) => api.listOrgDecisions({ status: 'pending', limit: PAGE, offset })
    .then((res) => {
      const rows = res.data?.decisions ?? [];
      setItems((prev) => (offset ? [...prev, ...rows] : rows));
      setMore(rows.length === PAGE);
      setError(null);
    })
    .catch((e) => setError(apiError(e) || 'Failed to load decisions.'))
    .finally(() => setLoading(false)), []);
  useEffect(() => { load(0); }, [load]);

  const decide = async (d, approve) => {
    setBusy(d.id);
    try {
      await api.approveDecision(d.run_id, d.id, approve, '');
      setItems((prev) => prev.filter((x) => x.id !== d.id));
    } catch (e) {
      setError(apiError(e) || 'Decision failed.');
      if (e?.response?.status === 409) setItems((prev) => prev.filter((x) => x.id !== d.id));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <header className="flex items-center gap-3">
        <Inbox className="w-6 h-6 text-accent" />
        <div>
          <h1 className="text-2xl font-bold text-bright">Pending decisions</h1>
          <p className="text-muted text-sm">Approvals waiting on a person, across all runs.</p>
        </div>
      </header>
      {error && <div role="alert" className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-danger text-xs">{error}</div>}
      {loading ? (
        <div className="p-10 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-accent" /></div>
      ) : items.length === 0 ? (
        <p className="panel p-8 text-center text-sm text-muted">Nothing is waiting for a decision.</p>
      ) : (
        <ul className="space-y-3">
          {items.map((d) => (
            <li key={d.id} className="panel p-4 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-bold text-bright">{d.title || d.decision_type}</span>
                <Link to={`/runs/${d.run_id}`} className="text-xs text-accent hover:underline">Open run</Link>
              </div>
              {d.what && <p className="text-xs text-muted">{d.what}</p>}
              {d.why && <p className="text-xs text-muted/80">Why: {d.why}</p>}
              {canWrite && (
                <div className="flex gap-2 pt-1">
                  <button disabled={busy === d.id} onClick={() => decide(d, true)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500/20 text-emerald-400 text-[11px] font-bold uppercase disabled:opacity-50">
                    <CheckCircle2 className="w-3 h-3" />Approve
                  </button>
                  <button disabled={busy === d.id} onClick={() => decide(d, false)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-500/20 text-red-400 text-[11px] font-bold uppercase disabled:opacity-50">
                    <XCircle className="w-3 h-3" />Reject
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {more && <button onClick={() => load(items.length)} className="text-xs text-accent hover:underline">Load more</button>}
    </div>
  );
};

export default DecisionsInbox;
