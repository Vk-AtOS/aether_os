import React, { useState, useEffect } from 'react';
import { useParams, useLocation } from 'react-router-dom';
import { api, setPortalToken } from '../api';
import { PHASES, PHASE_NAMES, stageOfDir } from '../components/project/projectConstants';
import { CheckCircle2, MessageSquare, ChevronRight, ShieldCheck, Loader2, XCircle } from 'lucide-react';
import { apiError } from '../apiError';

const fmtWhen = (ts) => {
  if (!ts) return '';
  const d = new Date(ts > 1e12 ? ts : ts * 1000);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString();
};

const Notice = ({ title, children, tone = 'red' }) => (
  <div className="min-h-screen bg-surface flex items-center justify-center p-6">
    <div className={`max-w-md w-full panel p-8 text-center shadow ${tone === 'red' ? 'border-danger/40' : ''}`}>
      <h2 className={`text-xl font-bold mb-3 ${tone === 'red' ? 'text-danger' : 'text-bright'}`}>{title}</h2>
      <div className="text-sm text-muted space-y-2">{children}</div>
    </div>
  </div>
);

const ClientPortal = () => {
  const { id } = useParams();
  const { hash } = useLocation();
  const [load, setLoad] = useState({ loading: true, status: null, error: '', unauthorised: false });
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(null); // 'approve' | 'reject'
  const [actionError, setActionError] = useState('');
  const [recorded, setRecorded] = useState(null);

  useEffect(() => {
    // The token travels in the fragment (#t=...), which browsers never send to the server.
    setPortalToken(new URLSearchParams(hash.replace(/^#/, '')).get('t'));
    let alive = true;
    api.getPortalStatus(id)
      .then((res) => { if (alive) setLoad({ loading: false, status: res.data, error: '', unauthorised: false }); })
      .catch((err) => {
        if (!alive) return;
        const code = err.response?.status;
        setLoad({
          loading: false, status: null, unauthorised: code === 401,
          error: code === 404 ? 'This project could not be found.' : (apiError(err) || err.message || 'The portal could not be loaded.'),
        });
      });
    return () => { alive = false; setPortalToken(null); };
  }, [id, hash]);

  const decide = async (approved) => {
    setActionError('');
    setBusy(approved ? 'approve' : 'reject');
    try {
      const res = await api.approvePortal(id, approved, comment.trim() || null);
      setRecorded(res.data);
      setComment('');
    } catch (err) {
      setActionError(err.response?.status === 401
        ? 'This link has expired or been revoked, so your decision was not recorded. Ask the team for a new link.'
        : (apiError(err) || 'Your decision could not be recorded. Please try again.'));
    } finally {
      setBusy(null);
    }
  };

  if (load.loading) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center text-muted gap-2">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading portal…
      </div>
    );
  }
  if (load.unauthorised) {
    return (
      <Notice title="This link is not valid">
        <p>The access link is missing, has expired or was revoked.</p>
        <p>Ask the team that sent it for a new link. Links look like <span className="font-mono">…/portal/&lt;id&gt;#t=…</span></p>
      </Notice>
    );
  }
  if (load.error) {
    return <Notice title="Portal unavailable"><p>{load.error}</p></Notice>;
  }

  const status = load.status;
  const currentStage = stageOfDir(status.current_phase);
  const currentStageIndex = Math.max(0, PHASES.indexOf(currentStage));
  const reqs = status.requirements || [];
  const spec = status.specification;

  return (
    <div className="min-h-screen bg-surface text-bright p-6">
      <div className="max-w-4xl mx-auto space-y-8">
        <header>
          <div className="flex items-center gap-2 text-xs font-bold text-accent uppercase tracking-widest mb-2">
            <ShieldCheck className="w-4 h-4" /> Client Portal
          </div>
          <h1 className="text-3xl font-bold">Project Review: {status.project_name}</h1>
          <p className="text-xs text-muted mt-1">Build status: {status.status || 'unknown'}</p>
        </header>

        <div className="panel p-8 overflow-x-auto">
          <ol className="relative flex justify-between items-start" aria-label="Build stages">
            <div className="absolute left-0 top-4 -translate-y-1/2 w-full h-1 bg-border -z-10" />
            {PHASES.map((stage, i) => (
              <li key={stage} className="flex flex-col items-center bg-panel px-1" aria-current={i === currentStageIndex ? 'step' : undefined}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-xs border-2 ${
                  i < currentStageIndex ? 'bg-success border-success text-white'
                    : i === currentStageIndex ? 'bg-accent border-accent text-white scale-125'
                      : 'bg-surface border-border text-muted'}`}>
                  {i < currentStageIndex ? <CheckCircle2 className="w-4 h-4" /> : i + 1}
                </div>
                <span className={`text-[10px] font-bold uppercase tracking-wider text-center leading-tight mt-3 ${i === currentStageIndex ? 'text-accent' : 'text-muted'}`}>
                  {PHASE_NAMES[stage]}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div className="grid md:grid-cols-3 gap-8">
          <section className="md:col-span-2 panel overflow-hidden">
            <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center justify-between">
              <h2 className="text-sm font-bold uppercase tracking-widest">Requirements</h2>
              <span className="text-[10px] font-mono text-muted">STAGE: {(PHASE_NAMES[currentStage] || 'not started').toUpperCase()}</span>
            </div>
            <div className="p-8">
              {spec && <p className="text-sm text-muted leading-relaxed mb-6 whitespace-pre-wrap">{spec}</p>}
              {!spec && reqs.length > 0 && (
                <ul className="space-y-3">
                  {reqs.map((req, i) => (
                    <li key={i} className="flex items-start"><ChevronRight className="w-4 h-4 text-accent mr-3 mt-1 shrink-0" /><span>{req}</span></li>
                  ))}
                </ul>
              )}
              {!spec && reqs.length === 0 && (
                <p className="text-muted text-sm italic">No requirements have been captured yet for this project.</p>
              )}
            </div>
          </section>

          <section className="panel p-6 space-y-4 border-accent/30" aria-labelledby="decide-h">
            <h3 id="decide-h" className="text-sm font-bold uppercase tracking-wider flex items-center">
              <MessageSquare className="w-4 h-4 mr-2 text-accent" /> Your decision
            </h3>
            <p className="text-xs text-muted leading-relaxed">
              Approve the build as it stands, or request changes. A comment is optional for an approval and helps with a change request.
            </p>
            <label htmlFor="portal-comment" className="sr-only">Comment</label>
            <textarea
              id="portal-comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              maxLength={2000}
              rows={4}
              className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
              placeholder="Comment (optional)"
            />
            {actionError && <div role="alert" className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-danger text-xs">{actionError}</div>}
            <div className="flex gap-2">
              <button onClick={() => decide(true)} disabled={Boolean(busy)}
                className="flex-1 flex items-center justify-center gap-1.5 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold py-2.5 rounded-lg">
                {busy === 'approve' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />} Approve
              </button>
              <button onClick={() => decide(false)} disabled={Boolean(busy)}
                className="flex-1 flex items-center justify-center gap-1.5 bg-border/50 hover:bg-border disabled:opacity-50 text-bright text-xs font-bold py-2.5 rounded-lg border border-border">
                {busy === 'reject' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />} Request changes
              </button>
            </div>
            {recorded && (
              <div role="status" className={`p-3 rounded-lg text-xs space-y-1 border ${recorded.approved ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-yellow-500/10 border-yellow-500/30 text-yellow-300'}`}>
                <p className="font-bold">{recorded.message}</p>
                <p>{recorded.approved ? 'Approved' : 'Changes requested'}{recorded.recorded_by ? ` by ${recorded.recorded_by}` : ''}{recorded.recorded_at ? ` on ${fmtWhen(recorded.recorded_at)}` : ''}.</p>
                {recorded.duplicate && <p>This repeats your previous decision; nothing new was recorded.</p>}
              </div>
            )}
          </section>
        </div>

        <footer className="py-12 border-t border-border flex flex-col items-center">
          <div className="text-[10px] font-bold text-muted uppercase tracking-[0.3em] mb-4">Powered by AetherOS Factory</div>
          <div className="flex items-center space-x-6">
            <a href="/api/legal/privacy" target="_blank" rel="noopener noreferrer" className="text-[10px] text-muted font-medium hover:text-bright">PRIVACY POLICY</a>
            <a href="/api/legal/tos" target="_blank" rel="noopener noreferrer" className="text-[10px] text-muted font-medium hover:text-bright">TERMS OF SERVICE</a>
            <a href="/api/legal/dpa" target="_blank" rel="noopener noreferrer" className="text-[10px] text-muted font-medium hover:text-bright">DPA</a>
          </div>
        </footer>
      </div>
    </div>
  );
};

export default ClientPortal;
