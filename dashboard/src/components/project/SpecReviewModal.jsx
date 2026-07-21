import React from 'react';
import { CheckCircle2, X, Loader2, Play } from 'lucide-react';

const SpecReviewModal = ({ spec, onApprove, onCancel, approving }) => {
  const [remember, setRemember] = React.useState(false);
  if (!spec) return null;
  const entries = Object.entries(spec).filter(([k]) => !['run_id'].includes(k));
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-surface border border-accent/40 rounded-xl shadow-2xl w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col">
        <div className="flex items-center gap-3 px-6 py-4 border-b border-border">
          <CheckCircle2 className="w-5 h-5 text-accent shrink-0" />
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-bold text-bright">Spec Review</h2>
            <p className="text-xs text-muted">Review the parsed requirements before code generation starts.</p>
          </div>
          <button onClick={onCancel} className="text-muted hover:text-bright transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {entries.map(([key, value]) => (
            <div key={key} className="bg-surface/60 border border-border rounded-lg p-3">
              <div className="text-[10px] font-mono text-accent uppercase tracking-widest mb-1">{key.replace(/_/g, ' ')}</div>
              <div className="text-sm text-bright whitespace-pre-wrap break-words">
                {typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '')}
              </div>
            </div>
          ))}
          {entries.length === 0 && (
            <p className="text-sm text-muted text-center py-8">No spec data available yet.</p>
          )}
        </div>
        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-border">
          <label className="flex items-center gap-2 cursor-pointer select-none group">
            <div
              onClick={() => setRemember(v => !v)}
              className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors ${remember ? 'bg-accent' : 'bg-border'}`}
            >
              <span className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${remember ? 'translate-x-[14px]' : 'translate-x-0.5'}`} />
            </div>
            <span className="text-xs text-muted group-hover:text-bright transition-colors">
              {remember ? 'Autonomous mode ON — future builds skip this review' : 'Enable autonomous mode after approving'}
            </span>
          </label>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={onCancel}
              disabled={approving}
              className="px-4 py-2 text-xs rounded-lg border border-border text-muted hover:text-bright hover:border-bright transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={() => onApprove(remember)}
              disabled={approving}
              className="px-5 py-2 text-xs rounded-lg bg-accent text-black font-semibold hover:bg-accent/80 transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {approving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
              {approving ? 'Approving…' : remember ? 'Approve & Run Autonomously' : 'Approve & Start Build'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SpecReviewModal;
