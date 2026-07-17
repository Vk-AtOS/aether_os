import React, { useState } from 'react';
import { GitPullRequest, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { api } from '../../api';

const DecisionsPanel = ({ runId }) => {
  const [decisions, setDecisions] = useState([]);
  const [decisionsLoading, setDecisionsLoading] = useState(false);
  const [decisionsError, setDecisionsError] = useState(null);
  const [decidingId, setDecidingId] = useState(null);

  const loadDecisions = async () => {
    setDecisionsLoading(true);
    setDecisionsError(null);
    try {
      const res = await api.listDecisions(runId);
      setDecisions(res.data ?? []);
    } catch (e) {
      setDecisionsError(e.response?.data?.detail || 'Failed to load decisions');
    } finally {
      setDecisionsLoading(false);
    }
  };

  const decide = async (decisionId, approve) => {
    setDecidingId(decisionId);
    try {
      await api.approveDecision(runId, decisionId, approve, '');
      setDecisions(prev =>
        prev.map(x => x.id === decisionId ? { ...x, status: approve ? 'approved' : 'rejected' } : x)
      );
    } catch (e) {
      setDecisionsError(e.response?.data?.detail || 'Decision failed');
    } finally {
      setDecidingId(null);
    }
  };

  return (
    <div className="flex flex-col" style={{ minHeight: '420px' }}>
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-border/10 shrink-0">
        <div className="flex items-center space-x-2">
          <GitPullRequest className="w-4 h-4 text-accent" />
          <span className="text-xs font-bold text-muted uppercase tracking-wider">Decisions</span>
        </div>
        <button
          onClick={loadDecisions}
          disabled={decisionsLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-[10px] font-bold uppercase tracking-wider rounded-lg transition-colors"
        >
          {decisionsLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
          Load Decisions
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {decisionsError && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">{decisionsError}</div>
        )}
        {!decisionsLoading && decisions.length === 0 && !decisionsError && (
          <div className="flex flex-col items-center justify-center h-48 text-muted">
            <GitPullRequest className="w-10 h-10 mb-3 opacity-20" />
            <p className="text-sm font-medium">No decisions yet</p>
            <p className="text-xs mt-1 opacity-60">Click Load Decisions to fetch pending approvals.</p>
          </div>
        )}
        {decisions.map(d => (
          <div key={d.id} className="p-4 bg-surface border border-border rounded-lg space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-bright">{d.title || d.decision_type || d.id}</span>
              <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                d.status === 'approved' ? 'bg-emerald-500/20 text-emerald-400' :
                d.status === 'rejected' ? 'bg-red-500/20 text-red-400' :
                'bg-amber-500/20 text-amber-400'
              }`}>{d.status}</span>
            </div>
            {d.description && <p className="text-xs text-muted">{d.description}</p>}
            {d.status === 'pending' && (
              <div className="flex items-center gap-2 pt-1">
                <button
                  onClick={() => decide(d.id, true)}
                  disabled={decidingId === d.id}
                  className="flex items-center gap-1 px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[10px] font-bold uppercase rounded-lg transition-colors disabled:opacity-50"
                >
                  <CheckCircle2 className="w-3 h-3" /> Approve
                </button>
                <button
                  onClick={() => decide(d.id, false)}
                  disabled={decidingId === d.id}
                  className="flex items-center gap-1 px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 text-[10px] font-bold uppercase rounded-lg transition-colors disabled:opacity-50"
                >
                  <XCircle className="w-3 h-3" /> Reject
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default DecisionsPanel;
