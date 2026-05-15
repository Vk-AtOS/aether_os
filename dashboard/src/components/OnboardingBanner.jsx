import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { X, CheckCircle2, Circle, Key, Rocket, Settings } from 'lucide-react';
import { api } from '../api';

const STORAGE_KEY = 'aether_onboarding_dismissed';

const Step = ({ done, icon: Icon, title, desc, action, actionLabel }) => (
  <div className={`flex items-start gap-4 p-4 rounded-lg border transition-colors ${done ? 'border-success/30 bg-success/5' : 'border-border bg-surface/50'}`}>
    <div className={`mt-0.5 ${done ? 'text-success' : 'text-muted'}`}>
      {done ? <CheckCircle2 className="w-5 h-5" /> : <Circle className="w-5 h-5" />}
    </div>
    <div className="flex-1 min-w-0">
      <div className={`text-sm font-semibold ${done ? 'text-success line-through opacity-60' : 'text-bright'}`}>{title}</div>
      {!done && <div className="text-xs text-muted mt-0.5">{desc}</div>}
    </div>
    {!done && action && (
      <button
        onClick={action}
        className="shrink-0 text-[10px] font-bold text-accent border border-accent/40 hover:bg-accent/10 px-3 py-1.5 rounded transition-colors uppercase tracking-wider"
      >
        {actionLabel}
      </button>
    )}
  </div>
);

const OnboardingBanner = ({ hasRuns, hasApiKey }) => {
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(STORAGE_KEY) === '1');
  const navigate = useNavigate();

  const allDone = hasRuns && hasApiKey;

  useEffect(() => {
    if (allDone) {
      localStorage.setItem(STORAGE_KEY, '1');
      setDismissed(true);
    }
  }, [allDone]);

  if (dismissed) return null;

  const steps = [
    {
      done: hasApiKey,
      icon: Key,
      title: 'Add an LLM API key',
      desc: 'Connect Anthropic, Gemini, or configure a local Ollama instance.',
      action: () => navigate('/settings'),
      actionLabel: 'Go to Settings',
    },
    {
      done: hasRuns,
      icon: Rocket,
      title: 'Run your first pipeline',
      desc: 'Describe your project and AetherOS will generate production-ready code.',
      action: () => navigate('/new-project'),
      actionLabel: 'Start Project',
    },
  ];

  const done = steps.filter(s => s.done).length;

  return (
    <div className="panel p-6 border-accent/20 bg-gradient-to-br from-accent/5 to-transparent">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-base font-bold text-bright">Welcome to AetherOS Factory</h2>
          <p className="text-xs text-muted mt-0.5">{done}/{steps.length} steps complete</p>
        </div>
        <button
          onClick={() => { setDismissed(true); localStorage.setItem(STORAGE_KEY, '1'); }}
          className="text-muted hover:text-bright transition-colors p-1"
          aria-label="Dismiss onboarding"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Progress bar */}
      <div className="w-full h-1.5 bg-border/50 rounded-full mb-4 overflow-hidden">
        <div
          className="h-full bg-accent transition-all duration-500 rounded-full"
          style={{ width: `${(done / steps.length) * 100}%` }}
        />
      </div>

      <div className="space-y-2">
        {steps.map((step, i) => <Step key={i} {...step} />)}
      </div>
    </div>
  );
};

export default OnboardingBanner;
