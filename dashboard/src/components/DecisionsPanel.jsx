import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { Loader2, CheckCircle, AlertTriangle, Clock, AlertCircle } from 'lucide-react';

const DecisionsPanel = ({ runId }) => {
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchDecisions = async () => {
    try {
      const res = await api.client.get(`/factory/runs/${runId}/decisions`);
      setDecisions(res.data);
      setLoading(false);
    } catch (e) {
      console.error("Failed to fetch decisions", e);
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDecisions();
    const interval = setInterval(() => {
      if (decisions.some(d => d.status === 'pending')) {
        fetchDecisions();
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [runId, decisions]);

  const approveDecision = async (id, decision) => {
    try {
      await api.client.post(`/factory/runs/${runId}/decisions/${id}/approve`, { decision });
      fetchDecisions();
    } catch (e) {
      console.error("Failed to approve decision", e);
    }
  };

  if (loading) return <div className="p-4"><Loader2 className="animate-spin" /></div>;

  return (
    <div className="space-y-4">
      {decisions.map(d => (
        <div key={d.id} className="border border-border bg-panel p-4 rounded-lg">
          <div className="flex justify-between items-center mb-2">
            <h3 className="font-bold text-bright text-sm">{d.title}</h3>
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
              d.status === 'pending' ? 'bg-warning/20 text-warning border border-warning/30' :
              d.status === 'approved' ? 'bg-success/20 text-success border border-success/30' :
              d.status === 'modified' ? 'bg-accent/20 text-accent border border-accent/30' :
              'bg-border/50 text-muted border border-border'
            }`}>
              {d.status}
            </span>
          </div>
          <p className="text-xs mb-1 text-muted"><span className="font-semibold text-bright">What:</span> {d.what}</p>
          <p className="text-xs mb-4 text-muted"><span className="font-semibold text-bright">Why:</span> {d.why}</p>
          {d.status === 'pending' && (
            <div className="flex gap-2">
              {d.alternatives ? d.alternatives.map(alt => (
                <button key={alt} onClick={() => approveDecision(d.id, alt)} className="px-3 py-1 bg-accent text-white rounded text-xs font-bold hover:bg-accent/90">
                  {alt}
                </button>
              )) : (
                <button onClick={() => approveDecision(d.id, 'approve')} className="px-3 py-1 bg-success/20 text-success border border-success/30 rounded text-xs font-bold hover:bg-success/30">
                  Approve
                </button>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
};

export default DecisionsPanel;
