import React from 'react';

// ── Static data ────────────────────────────────────────────────────────────────
export const DEFAULT_TEMPLATES = [
  { id: 'saas', icon: '🏢', label: 'SaaS App', domain: 'saas', prompt: 'Build a multi-tenant SaaS application with user auth, organisation management, subscription billing, and an analytics dashboard.' },
  { id: 'ecommerce', icon: '🛒', label: 'E-Commerce', domain: 'ecommerce', prompt: 'Build an e-commerce platform with product catalog, cart, checkout, order management, and payment processing.' },
  { id: 'dashboard', icon: '📊', label: 'Analytics Dashboard', domain: 'analytics', prompt: 'Build an analytics dashboard with real-time charts, KPI cards, data filters, and CSV export.' },
  { id: 'api', icon: '⚡', label: 'REST API', domain: 'api', prompt: 'Build a production-ready REST API with JWT auth, rate limiting, Swagger docs, and PostgreSQL storage.' },
  { id: 'cms', icon: '✍️', label: 'CMS / Blog', domain: 'cms', prompt: 'Build a content management system with rich text editor, media uploads, categories, and public blog.' },
  { id: 'social', icon: '👥', label: 'Social Platform', domain: 'social', prompt: 'Build a social platform with user profiles, posts, follows, likes, comments, and notifications.' },
  { id: 'marketplace', icon: '🏪', label: 'Marketplace', domain: 'marketplace', prompt: 'Build a two-sided marketplace with seller listings, buyer search, transactions, and reviews.' },
  { id: 'healthcare', icon: '🏥', label: 'Healthcare', domain: 'healthcare', prompt: 'Build a healthcare app with patient records, appointment scheduling, and HIPAA-compliant data handling.' },
  { id: 'fintech', icon: '💳', label: 'FinTech', domain: 'fintech', prompt: 'Build a fintech app with transaction history, wallet management, and financial reporting.' },
  { id: 'lms', icon: '🎓', label: 'Learning Management', domain: 'education', prompt: 'Build a learning management system with courses, lessons, quizzes, and student progress tracking.' },
  { id: 'iot', icon: '📡', label: 'IoT Dashboard', domain: 'iot', prompt: 'Build an IoT dashboard with device management, telemetry streams, alerts, and historical charts.' },
  { id: 'custom', icon: '🛠️', label: 'Custom', domain: 'general', prompt: '' },
];

export const PRIORITIES = ['High', 'Normal', 'Low'];
export const BACKEND_OPTIONS = ['FastAPI', 'Django', 'Express', 'Flask'];
export const FRONTEND_OPTIONS = ['React', 'Vue', 'Vanilla JS', 'None'];
export const DB_OPTIONS = ['PostgreSQL', 'MongoDB', 'SQLite', 'MySQL'];
// Fallback models shown only when the /settings/active-provider API is unreachable.
export const DEFAULT_MODELS = [
  { value: 'claude-sonnet', label: 'Claude Sonnet (Anthropic)' },
  { value: 'gemini-flash', label: 'Gemini Flash (Google)' },
  { value: 'qwen-coder', label: 'Qwen Coder (Local/Ollama)' },
];

export const TEMPLATE_COLORS = {
  saas: 'from-violet-500 to-purple-600',
  ecommerce: 'from-amber-500 to-orange-600',
  dashboard: 'from-blue-500 to-indigo-600',
  api: 'from-cyan-500 to-sky-600',
  cms: 'from-emerald-500 to-teal-600',
  social: 'from-pink-500 to-rose-600',
  marketplace: 'from-orange-500 to-red-500',
  healthcare: 'from-green-500 to-emerald-600',
  fintech: 'from-violet-500 to-indigo-600',
  lms: 'from-yellow-500 to-amber-600',
  iot: 'from-slate-500 to-zinc-600',
  custom: 'from-slate-500 to-slate-600',
};

// ── Sub-components ─────────────────────────────────────────────────────────────
export const StepIndicator = ({ step }) => {
  const steps = ['Type', 'Describe', 'Configure', 'Launch'];
  return (
    <div className="flex items-center justify-center mb-10">
      {steps.map((label, i) => {
        const idx = i + 1;
        const active = idx === step;
        const done = idx < step;
        return (
          <React.Fragment key={idx}>
            <div className={`flex items-center gap-2 px-3 py-2 rounded-full text-sm font-medium transition-all ${
              done ? 'text-violet-400' : active ? 'text-white bg-violet-600/20 border border-violet-500/30' : 'text-slate-600'
            }`}>
              <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                done ? 'bg-violet-600 text-white' : active ? 'bg-violet-600/30 border border-violet-500 text-violet-300' : 'bg-white/[0.04] border border-white/[0.08] text-slate-600'
              }`}>{done ? '✓' : idx}</span>
              {label}
            </div>
            {i < steps.length - 1 && (
              <div className={`w-10 h-px mx-1 transition-colors ${done ? 'bg-violet-600' : 'bg-white/[0.08]'}`} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};

export const TemplateCard = ({ tpl, selected, onClick }) => {
  const color = TEMPLATE_COLORS[tpl.id] || 'from-violet-500 to-indigo-600';
  return (
    <button onClick={onClick} className={`group p-4 rounded-2xl border text-left transition-all duration-200 hover:-translate-y-1 ${
      selected
        ? 'border-violet-500/60 bg-violet-500/10 shadow-lg shadow-violet-500/10'
        : 'border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12] hover:bg-white/[0.04]'
    }`}>
      <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${color} flex items-center justify-center text-xl mb-3 group-hover:scale-110 transition-transform duration-300`}>
        {tpl.icon}
      </div>
      <div className="text-sm font-semibold text-white">{tpl.label}</div>
      {selected && <div className="mt-2 text-violet-400 text-xs font-medium">✓ Selected</div>}
    </button>
  );
};

export const PillGroup = ({ options, value, onChange }) => (
  <div className="flex gap-2 flex-wrap">
    {options.map(([val, label]) => {
      const active = Array.isArray(value) ? value.includes(val) : value === val;
      return (
        <button key={String(val)} type="button" onClick={() => onChange(val)}
          className={`px-4 py-2 rounded-lg border text-sm font-medium transition-all ${
            active ? 'border-accent bg-accent/15 text-accent' : 'border-border text-muted hover:border-accent/40 hover:text-bright'
          }`}>
          {label}
        </button>
      );
    })}
  </div>
);
