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
