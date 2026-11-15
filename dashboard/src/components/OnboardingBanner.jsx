import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { X, CheckCircle2, Circle } from 'lucide-react';
import { api } from '../api';
import { apiError } from '../apiError';
import { useRole } from '../hooks/useRole';

const Step = ({ done, title, optional, onGo }) => (
  <div className={`flex items-center gap-4 p-3 rounded-lg border ${done ? 'border-success/30 bg-success/5' : 'border-border bg-surface/50'}`}>
    <span className={done ? 'text-success' : 'text-muted'}>{done ? <CheckCircle2 className="w-5 h-5" /> : <Circle className="w-5 h-5" />}</span>
    <div className={`flex-1 text-sm font-semibold ${done ? 'text-success line-through opacity-60' : 'text-bright'}`}>
      {title}{optional && !done && <span className="ml-2 text-[10px] font-normal text-muted">optional</span>}
    </div>
    {!done && <button onClick={onGo} className="shrink-0 text-[10px] font-bold text-accent border border-accent/40 hover:bg-accent/10 px-3 py-1.5 rounded uppercase tracking-wider">Go</button>}
  </div>
);

// Progress comes from the server (GET /onboarding): steps are derived from what exists in the organisation, so the
// same banner shows on every browser and for every admin, and hiding it hides it for the organisation.
const OnboardingBanner = () => {
  const { isAdmin } = useRole();
  const navigate = useNavigate();
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    api.getOnboarding().then((res) => live && setState(res.data)).catch(() => { /* optional banner: stay hidden */ });
    return () => { live = false; };
  }, []);

  if (!Array.isArray(state?.steps) || state.dismissed || state.complete) return null;
  const done = state.steps.filter((s) => s.done).length;

  const dismiss = async () => {
    try { await api.dismissOnboarding(); setState({ ...state, dismissed: true }); }
    catch (e) { setError(apiError(e) || 'Could not hide this.'); }
  };

  return (
    <div className="panel p-6 border-accent/20 bg-gradient-to-br from-accent/5 to-transparent">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-base font-bold text-bright">Welcome to AetherOS Factory</h2>
          <p className="text-xs text-muted mt-0.5">{done}/{state.steps.length} steps complete</p>
        </div>
        {isAdmin && <button onClick={dismiss} className="text-muted hover:text-bright p-1" aria-label="Dismiss onboarding"><X className="w-4 h-4" /></button>}
      </div>
      {error && <p role="alert" className="text-xs text-danger mb-2">{error}</p>}
      <div className="w-full h-1.5 bg-border/50 rounded-full mb-4 overflow-hidden">
        <div className="h-full bg-accent rounded-full" style={{ width: `${(done / state.steps.length) * 100}%` }} />
      </div>
      <div className="space-y-2">
        {state.steps.map((s) => <Step key={s.id} done={s.done} title={s.title} optional={!s.required} onGo={() => navigate(s.link)} />)}
      </div>
    </div>
  );
};

export default OnboardingBanner;
