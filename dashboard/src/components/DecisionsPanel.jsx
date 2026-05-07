import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { Loader2, CheckCircle, AlertTriangle, Clock, AlertCircle } from 'lucide-react';

const DecisionsPanel = ({ runId }) => {
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchDecisions = async () => {
    try {
      const res = await api.get(`/factory/runs/${runId}/decisions`);
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
      await api.post(`/factory/runs/${runId}/decisions/${id}/approve`, { decision });
      fetchDecisions();
    } catch (e) {
      console.error("Failed to approve decision", e);
    }
  };

  if (loading) return <div className="p-4"><Loader2 className="animate-spin" /></div>;

  return (
    <div className="space-y-4">
      {decisions.map(d => (
        <div key={d.id} className="border p-4 rounded-lg shadow-sm">
          <div className="flex justify-between items-center mb-2">
            <h3 className="font-bold">{d.title}</h3>
            <span className={`px-2 py-1 rounded text-xs ${
              d.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
              d.status === 'approved' ? 'bg-green-100 text-green-800' :
              d.status === 'modified' ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800'
            }`}>
              {d.status}
            </span>
          </div>
          <p className="text-sm mb-2 text-slate-600">What: {d.what}</p>
          <p className="text-sm mb-4 text-slate-500">Why: {d.why}</p>
          {d.status === 'pending' && (
            <div className="flex gap-2">
              {d.alternatives ? d.alternatives.map(alt => (
                <button key={alt} onClick={() => approveDecision(d.id, alt)} className="px-3 py-1 bg-blue-500 text-white rounded text-sm hover:bg-blue-600">
                  Approve {alt}
                </button>
              )) : (
                <button onClick={() => approveDecision(d.id, 'approve')} className="px-3 py-1 bg-green-500 text-white rounded text-sm hover:bg-green-600">
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
