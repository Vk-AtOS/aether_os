import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api';
import { PHASES, PHASE_NAMES } from '../components/project/projectConstants';
import { 
  CheckCircle2, 
  MessageSquare, 
  ChevronRight, 
  ShieldCheck, 
  Loader2,
  Lock
} from 'lucide-react';

const ClientPortal = () => {
  const { id } = useParams();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [feedback, setFeedback] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [feedbackSent, setFeedbackSent] = useState(false);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await api.getPortalStatus(id);
        setStatus(res.data);
      } catch (err) {
        // FIXED: was silently injecting mock data, hiding real errors from the client.
        // Now show the actual error so the client knows the project ID is wrong or the server is down.
        if (import.meta.env.DEV) console.error('Failed to load portal status', err);
        const detail = err.response?.data?.detail || err.message || 'Unknown error';
        setStatus({ _error: true, _detail: detail });
      } finally {
        setLoading(false);
      }
    };
    fetchStatus();
  }, [id]);

  // The stepper shows the 12 pipeline stages; an unknown or missing stage falls back to the first.
  const currentStageIndex = Math.max(0, PHASES.indexOf(status?.current_phase));

  const handleApprove = async () => {
    setActionError(null);
    try {
      await api.approvePortalPhase(id, true, 'Approved via portal');
      setSubmitted(true);
    } catch {
      setActionError('Failed to submit approval. Please try again.');
    }
  };

  const handleFeedback = async () => {
    setActionError(null);
    setFeedbackSent(false);
    try {
      await api.sendPortalFeedback(id, feedback, status.current_phase);
      setFeedback('');
      setFeedbackSent(true);
    } catch {
      setActionError('Failed to send feedback. Please try again.');
    }
  };

  if (loading) return <div className="min-h-screen bg-surface flex items-center justify-center text-muted">Loading portal…</div>;

  if (status?._error) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center p-6">
        <div className="max-w-md w-full bg-red-50 border border-red-200 rounded-xl p-8 text-center shadow">
          <h2 className="text-xl font-bold text-red-700 mb-3">Project Not Found</h2>
          <p className="text-red-600 text-sm">Could not load the project portal: {status._detail}</p>
          <p className="text-gray-400 text-xs mt-3">If you received a link, please check it is correct and try again.</p>
        </div>
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center p-6">
        <div className="max-w-md w-full panel p-12 text-center shadow-2xl">
          <div className="w-20 h-20 bg-success/10 rounded-full flex items-center justify-center mx-auto mb-8">
            <CheckCircle2 className="w-10 h-10 text-success" />
          </div>
          <h1 className="text-2xl font-bold mb-4">Approval Received</h1>
          <p className="text-muted leading-relaxed">Thank you. The next phase of development will begin automatically. You can close this window or return later to track progress.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface text-bright p-6">
      <div className="max-w-4xl mx-auto space-y-8">
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center space-x-2 text-xs font-bold text-accent uppercase tracking-widest mb-2">
               <ShieldCheck className="w-4 h-4" /> Secure Client Portal
            </div>
            <h1 className="text-3xl font-bold">Project Review: {status.project_name}</h1>
          </div>
          <div className="flex items-center space-x-2 text-[10px] text-muted font-bold uppercase tracking-tighter bg-panel px-3 py-1.5 rounded-full border border-border">
            <Lock className="w-3 h-3 mr-1" /> End-to-End Encrypted
          </div>
        </header>

        {/* Stage Stepper */}
        <div className="panel p-8 overflow-x-auto">
          <div className="relative flex justify-between items-start">
            <div className="absolute left-0 top-4 -translate-y-1/2 w-full h-1 bg-border -z-10"></div>
            {PHASES.map((stage, i) => (
              <div key={stage} className="flex flex-col items-center bg-panel px-1">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-xs border-2 transition-all ${
                  i < currentStageIndex ? 'bg-success border-success text-white' :
                  i === currentStageIndex ? 'bg-accent border-accent text-white scale-125' :
                  'bg-surface border-border text-muted'
                }`}>
                  {i < currentStageIndex ? <CheckCircle2 className="w-4 h-4" /> : i + 1}
                </div>
                <span className={`text-[10px] font-bold uppercase tracking-wider text-center leading-tight mt-3 ${i === currentStageIndex ? 'text-accent' : 'text-muted'}`}>
                  {PHASE_NAMES[stage]}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="grid md:grid-cols-3 gap-8">
          <div className="md:col-span-2 space-y-8">
            <section className="panel overflow-hidden">
               <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center justify-between">
                  <h2 className="text-sm font-bold uppercase tracking-widest">Current Specifications</h2>
                  <span className="text-[10px] font-mono text-muted">STAGE: {(PHASE_NAMES[status.current_phase] || status.current_phase)?.toUpperCase()}</span>
               </div>
               <div className="p-8 prose prose-invert max-w-none">
                  <h3 className="text-accent text-lg font-bold mb-4">Core Requirements</h3>
                  {(() => {
                    const reqs = status.requirements || status.metadata?.requirements || [];
                    const spec = status.specification || status.metadata?.specification;
                    const desc = status.description || status.metadata?.description;
                    return (
                      <>
                        {spec && <p className="text-sm text-muted leading-relaxed mb-6 whitespace-pre-wrap">{spec}</p>}
                        {Array.isArray(reqs) && reqs.length > 0 ? (
                          <ul className="space-y-3 list-none p-0">
                            {reqs.map((req, i) => (
                              <li key={i} className="flex items-start">
                                <ChevronRight className="w-4 h-4 text-accent mr-3 mt-1 shrink-0" />
                                <span>{req}</span>
                              </li>
                            ))}
                          </ul>
                        ) : !spec && (
                          <p className="text-muted text-sm italic">No requirements have been captured yet for this project.</p>
                        )}
                        {desc && (
                          <div className="mt-6 text-sm text-muted leading-relaxed">
                            <strong className="text-bright">Project Description:</strong> {desc}
                          </div>
                        )}
                      </>
                    );
                  })()}

                  <div className="mt-10 p-4 rounded-lg bg-accent/5 border border-accent/20 text-sm italic text-muted leading-relaxed">
                    This specification was autonomously generated based on your initial prompt and cross-referenced with enterprise patterns.
                  </div>
               </div>
            </section>
          </div>

          <div className="space-y-6">
            <section className="panel p-6 shadow-xl border-accent/30 bg-accent/5">
              <h3 className="text-sm font-bold uppercase tracking-wider mb-4 flex items-center">
                <CheckCircle2 className="w-4 h-4 mr-2 text-success" /> Review Action
              </h3>
              <p className="text-xs text-muted leading-relaxed mb-6">
                Please review the current specifications. If they align with your vision, approve to proceed to the Architecture phase.
              </p>
              {actionError && (
                <div className="mb-3 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-danger text-xs">{actionError}</div>
              )}
              <button
                onClick={handleApprove}
                aria-label="Approve project and continue to next phase"
                className="w-full bg-accent hover:bg-accent/90 text-white font-bold py-3 rounded-lg transition-all shadow-lg shadow-accent/20"
              >
                APPROVE AND CONTINUE
              </button>
            </section>

            <section className="panel p-6">
              <h3 className="text-sm font-bold uppercase tracking-wider mb-4 flex items-center">
                <MessageSquare className="w-4 h-4 mr-2 text-warning" /> Request Changes
              </h3>
              <textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                rows="4"
                className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent transition-colors custom-scrollbar mb-4"
                placeholder="Describe any changes or additions..."
                aria-label="Change request feedback"
              ></textarea>
              {feedbackSent && (
                <div className="mb-3 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs">Feedback sent successfully.</div>
              )}
              <button
                onClick={handleFeedback}
                disabled={!feedback.trim()}
                aria-label="Submit change request feedback"
                className="w-full bg-border/50 hover:bg-border disabled:opacity-50 text-bright text-xs font-bold py-2.5 rounded-lg transition-colors border border-border"
              >
                SUBMIT FEEDBACK
              </button>
            </section>
          </div>
        </div>
        
        <footer className="py-12 border-t border-border flex flex-col items-center">
           <div className="text-[10px] font-bold text-muted uppercase tracking-[0.3em] mb-4">Powered by AetherOS Factory</div>
           <div className="flex items-center space-x-6">
              <a href="/api/legal/privacy" target="_blank" rel="noopener noreferrer" className="text-[10px] text-muted font-medium hover:text-bright transition-colors">PRIVACY POLICY</a>
              <a href="/api/legal/tos" target="_blank" rel="noopener noreferrer" className="text-[10px] text-muted font-medium hover:text-bright transition-colors">TERMS OF SERVICE</a>
              <a href="/api/legal/dpa" target="_blank" rel="noopener noreferrer" className="text-[10px] text-muted font-medium hover:text-bright transition-colors">DPA</a>
           </div>
        </footer>
      </div>
    </div>
  );
};

export default ClientPortal;
