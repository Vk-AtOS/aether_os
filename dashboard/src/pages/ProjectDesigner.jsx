import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate, useSearchParams, useParams } from 'react-router-dom';
import {
  Wand2, Upload, Link, ChevronDown, Check, Loader2, X,
  ExternalLink, ChevronRight, Database,
} from 'lucide-react';
import { api } from '../api';

// ── Static data ────────────────────────────────────────────────────────────────
const TEMPLATES = [
  { id: 'saas',        icon: '🏢', label: 'SaaS App',            domain: 'saas',        prompt: 'Build a multi-tenant SaaS application with user auth, organisation management, subscription billing, and an analytics dashboard.' },
  { id: 'ecommerce',   icon: '🛒', label: 'E-Commerce',          domain: 'ecommerce',   prompt: 'Build an e-commerce platform with product catalog, cart, checkout, order management, and payment processing.' },
  { id: 'dashboard',   icon: '📊', label: 'Analytics Dashboard', domain: 'analytics',   prompt: 'Build an analytics dashboard with real-time charts, KPI cards, data filters, and CSV export.' },
  { id: 'api',         icon: '⚡', label: 'REST API',            domain: 'api',         prompt: 'Build a production-ready REST API with JWT auth, rate limiting, Swagger docs, and PostgreSQL storage.' },
  { id: 'cms',         icon: '✍️', label: 'CMS / Blog',          domain: 'cms',         prompt: 'Build a content management system with rich text editor, media uploads, categories, and public blog.' },
  { id: 'social',      icon: '👥', label: 'Social Platform',     domain: 'social',      prompt: 'Build a social platform with user profiles, posts, follows, likes, comments, and notifications.' },
  { id: 'marketplace', icon: '🏪', label: 'Marketplace',         domain: 'marketplace', prompt: 'Build a two-sided marketplace with seller listings, buyer search, transactions, and reviews.' },
  { id: 'healthcare',  icon: '🏥', label: 'Healthcare',          domain: 'healthcare',  prompt: 'Build a healthcare app with patient records, appointment scheduling, and HIPAA-compliant data handling.' },
  { id: 'fintech',     icon: '💳', label: 'FinTech',             domain: 'fintech',     prompt: 'Build a fintech app with transaction history, wallet management, and financial reporting.' },
  { id: 'lms',         icon: '🎓', label: 'Learning Management', domain: 'education',   prompt: 'Build a learning management system with courses, lessons, quizzes, and student progress tracking.' },
  { id: 'iot',         icon: '📡', label: 'IoT Dashboard',       domain: 'iot',         prompt: 'Build an IoT dashboard with device management, telemetry streams, alerts, and historical charts.' },
  { id: 'custom',      icon: '🛠️', label: 'Custom',              domain: 'general',     prompt: '' },
];

const DOMAINS = TEMPLATES.map(t => ({ id: t.domain, label: t.label, icon: t.icon }));

const DEFAULT_MODELS = [
  { value: 'claude-sonnet-4-6',  label: 'Claude Sonnet 4.6 (Anthropic)' },
  { value: 'gemini-2.0-flash',   label: 'Gemini 2.0 Flash (Google)' },
  { value: 'qwen2.5-coder:7b',   label: 'Qwen 2.5 Coder 7B (Ollama)' },
];

const PRIORITIES = ['High', 'Normal', 'Low'];

const STACK = {
  frontend: {
    framework:        ['Next.js 14 App Router','Next.js 14 Pages Router','React + Vite','Vue 3 + Vite','Nuxt 3','SvelteKit','Astro','Angular 17','Vanilla JS'],
    styling:          ['Tailwind CSS','Tailwind + shadcn/ui','Tailwind + Radix UI','Material UI v5','Ant Design 5','Chakra UI','Styled Components','CSS Modules'],
    state_management: ['React Context','Zustand','Jotai','Redux Toolkit','Pinia (Vue)','None'],
    form_library:     ['React Hook Form + Zod','Formik','None'],
    data_fetching:    ['TanStack Query','SWR','Axios','Native Fetch'],
  },
  backend: {
    framework: ['FastAPI','Django REST Framework','Express.js','NestJS','Spring Boot','Ruby on Rails','Laravel','Go Fiber','Go + chi'],
    database:  ['PostgreSQL','MySQL 8','MongoDB 7','CockroachDB','SQLite','Supabase','PlanetScale'],
    orm:       ['SQLAlchemy','Prisma','TypeORM','Drizzle','Tortoise ORM','Mongoose','GORM'],
    auth:      ['JWT + refresh tokens','Session-based','OAuth2 social login','API Key','SAML SSO','Clerk','Auth0'],
    api_style: ['REST','GraphQL','REST + WebSocket','tRPC'],
  },
  infra: {
    deployment:   ['Docker + Compose','Kubernetes','Railway','Fly.io','Vercel + Railway','AWS ECS'],
    cache:        ['Redis','Memcached','None'],
    queue:        ['Celery + Redis','BullMQ','RabbitMQ','None'],
    file_storage: ['Local','AWS S3','Cloudflare R2','Cloudinary'],
    email:        ['Resend','SendGrid','SES','None'],
  },
};

const FONT_PAIRS = [
  'Inter + Inter (system)',
  'Geist + Geist Mono',
  'Plus Jakarta Sans + Fira Code',
  'DM Sans + JetBrains Mono',
  'Satoshi + IBM Plex Mono',
];

const LAYOUTS = [
  {
    id: 'sidebar-topbar', label: 'Sidebar Left + Top Bar',
    svg: (<svg viewBox="0 0 80 52" className="w-full h-full"><rect x="0" y="0" width="80" height="52" rx="3" fill="#1e293b"/><rect x="0" y="0" width="18" height="52" rx="2" fill="#334155"/><rect x="18" y="0" width="62" height="10" fill="#475569"/><rect x="22" y="14" width="30" height="4" rx="1" fill="#64748b"/><rect x="22" y="22" width="50" height="3" rx="1" fill="#475569"/><rect x="22" y="29" width="42" height="3" rx="1" fill="#475569"/><rect x="22" y="36" width="48" height="3" rx="1" fill="#475569"/></svg>),
  },
  {
    id: 'topbar-only', label: 'Top Bar only',
    svg: (<svg viewBox="0 0 80 52" className="w-full h-full"><rect x="0" y="0" width="80" height="52" rx="3" fill="#1e293b"/><rect x="0" y="0" width="80" height="12" rx="2" fill="#475569"/><rect x="8" y="16" width="30" height="4" rx="1" fill="#64748b"/><rect x="8" y="24" width="64" height="3" rx="1" fill="#475569"/><rect x="8" y="31" width="56" height="3" rx="1" fill="#475569"/><rect x="8" y="38" width="60" height="3" rx="1" fill="#475569"/></svg>),
  },
  {
    id: 'sidebar-wide', label: 'Sidebar Left (wide)',
    svg: (<svg viewBox="0 0 80 52" className="w-full h-full"><rect x="0" y="0" width="80" height="52" rx="3" fill="#1e293b"/><rect x="0" y="0" width="28" height="52" rx="2" fill="#334155"/><rect x="32" y="8" width="24" height="4" rx="1" fill="#64748b"/><rect x="32" y="16" width="44" height="3" rx="1" fill="#475569"/><rect x="32" y="23" width="38" height="3" rx="1" fill="#475569"/><rect x="32" y="30" width="42" height="3" rx="1" fill="#475569"/></svg>),
  },
  {
    id: 'split-panel', label: 'Split Panel',
    svg: (<svg viewBox="0 0 80 52" className="w-full h-full"><rect x="0" y="0" width="80" height="52" rx="3" fill="#1e293b"/><rect x="0" y="0" width="80" height="10" rx="2" fill="#475569"/><rect x="0" y="10" width="38" height="42" fill="#334155"/><rect x="42" y="14" width="32" height="3" rx="1" fill="#64748b"/><rect x="42" y="21" width="28" height="3" rx="1" fill="#475569"/><rect x="4" y="14" width="30" height="3" rx="1" fill="#64748b"/><rect x="4" y="21" width="26" height="3" rx="1" fill="#475569"/></svg>),
  },
  {
    id: 'minimal', label: 'Minimal (no sidebar)',
    svg: (<svg viewBox="0 0 80 52" className="w-full h-full"><rect x="0" y="0" width="80" height="52" rx="3" fill="#1e293b"/><rect x="16" y="8" width="48" height="5" rx="1" fill="#64748b"/><rect x="10" y="18" width="60" height="3" rx="1" fill="#475569"/><rect x="10" y="25" width="54" height="3" rx="1" fill="#475569"/><rect x="10" y="32" width="58" height="3" rx="1" fill="#475569"/><rect x="28" y="40" width="24" height="6" rx="3" fill="#6366f1"/></svg>),
  },
];

// ── Color helpers ──────────────────────────────────────────────────────────────
function hslToHex(h, s, l) {
  s /= 100; l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = n => Math.round(255 * (l - a * Math.max(-1, Math.min(((n + h / 30) % 12) - 3, Math.min(9 - ((n + h / 30) % 12), 1)))));
  return '#' + [f(0), f(8), f(4)].map(v => v.toString(16).padStart(2, '0')).join('');
}
function hexToHsl(hex) {
  const r = parseInt(hex.slice(1,3),16)/255, g = parseInt(hex.slice(3,5),16)/255, b = parseInt(hex.slice(5,7),16)/255;
  const max = Math.max(r,g,b), min = Math.min(r,g,b);
  let h = 0, s = 0, l = (max+min)/2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d/(2-max-min) : d/(max+min);
    switch(max) {
      case r: h = ((g-b)/d + (g<b?6:0))/6; break;
      case g: h = ((b-r)/d + 2)/6; break;
      case b: h = ((r-g)/d + 4)/6; break;
    }
  }
  return [Math.round(h*360), Math.round(s*100), Math.round(l*100)];
}
const isValidHex = h => /^#[0-9a-fA-F]{6}$/.test(h);

// ── Complexity calculator ──────────────────────────────────────────────────────
function calcComplexity(spec) {
  let score = 0;
  const fe = spec.frontend || {}, be = spec.backend || {}, inf = spec.infra || {}, ft = spec.features || {};
  if (['Next.js 14 App Router','NestJS','Angular 17'].includes(fe.framework)) score += 2;
  if (fe.state_management === 'Redux Toolkit') score += 1;
  if (['GraphQL','REST + WebSocket','tRPC'].includes(be.api_style)) score += 2;
  if (['Kubernetes','AWS ECS'].includes(inf.deployment)) score += 3;
  if (inf.queue && inf.queue !== 'None') score += 2;
  if (ft.multi_tenancy) score += 3;
  if (ft.realtime && ft.realtime !== 'None') score += 2;
  if (ft.payments && ft.payments !== 'None') score += 2;
  if (ft.internationalization) score += 1;
  if (['SAML SSO','Clerk','Auth0'].includes(be.auth)) score += 2;
  if (score <= 3) return { label: 'Simple',     color: 'text-emerald-400', bgColor: 'bg-emerald-400', bar: 1 };
  if (score <= 7) return { label: 'Moderate',   color: 'text-yellow-400',  bgColor: 'bg-yellow-400',  bar: 2 };
  if (score <= 12) return { label: 'Complex',   color: 'text-orange-400',  bgColor: 'bg-orange-400',  bar: 3 };
  return             { label: 'Enterprise',      color: 'text-red-400',     bgColor: 'bg-red-400',     bar: 4 };
}

// ── Default spec ───────────────────────────────────────────────────────────────
const DEFAULT_SPEC = {
  frontend: { framework: 'React + Vite', styling: 'Tailwind + shadcn/ui', state_management: 'Zustand', form_library: 'React Hook Form + Zod', data_fetching: 'TanStack Query' },
  backend:  { framework: 'FastAPI', database: 'PostgreSQL', orm: 'SQLAlchemy', auth: 'JWT + refresh tokens', api_style: 'REST' },
  infra:    { deployment: 'Docker + Compose', cache: 'Redis', queue: 'None', file_storage: 'Local', email: 'Resend' },
  features: { multi_tenancy: false, audit_log: false, rate_limiting: true, webhooks_out: false, realtime: 'None', payments: 'None', internationalization: false },
  design:   { primary: '#6366f1', secondary: '#8b5cf6', background: '#0f172a', surface: '#1e293b', font_pairing: 'Inter + Inter (system)', font_scale: 'Normal', border_radius: 'Rounded (8px)', layout: 'sidebar-topbar', density: 'Normal', card_style: 'Subtle Shadow' },
};

const TABS = ['Understand', 'Tech Stack', 'Design', 'Preview', 'Output'];
const COLOR_SLOTS = ['primary', 'secondary', 'background', 'surface'];

// ── Sub-components ─────────────────────────────────────────────────────────────
const SearchableSelect = ({ value, options, onChange, placeholder }) => {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const ref = useRef(null);
  useEffect(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  const filtered = options.filter(o => o.toLowerCase().includes(q.toLowerCase()));
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(p => !p)}
        className="w-full flex items-center justify-between px-3 py-2 bg-surface border border-border rounded-lg text-sm text-bright hover:border-accent/50 transition-colors">
        <span className={value ? 'text-bright' : 'text-muted'}>{value || placeholder || 'Select…'}</span>
        <ChevronDown className="w-3.5 h-3.5 text-muted shrink-0" />
      </button>
      {open && (
        <div className="absolute z-50 w-full mt-1 bg-panel border border-border rounded-lg shadow-xl max-h-48 overflow-hidden flex flex-col">
          <div className="p-1.5 border-b border-border">
            <input autoFocus className="w-full bg-surface border border-border text-sm text-bright rounded px-2 py-1 outline-none" placeholder="Search…" value={q} onChange={e => setQ(e.target.value)} />
          </div>
          <div className="overflow-y-auto">
            {filtered.map(opt => (
              <button key={opt} type="button" onClick={() => { onChange(opt); setOpen(false); setQ(''); }}
                className="w-full flex items-center justify-between px-3 py-2 text-sm text-left hover:bg-border/30 text-bright transition-colors">
                {opt}{value === opt && <Check className="w-3.5 h-3.5 text-accent" />}
              </button>
            ))}
            {filtered.length === 0 && <p className="px-3 py-2 text-xs text-muted">No results</p>}
          </div>
        </div>
      )}
    </div>
  );
};

const StackGroup = ({ title, fields, values, onChange }) => (
  <div>
    <h3 className="text-xs font-bold text-muted uppercase tracking-widest mb-3">{title}</h3>
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {fields.map(({ key, label, options }) => (
        <div key={key}>
          <label className="block text-xs text-muted mb-1">{label}</label>
          <SearchableSelect value={values[key]} options={options} onChange={v => onChange(key, v)} />
        </div>
      ))}
    </div>
  </div>
);

const HslPicker = ({ hex, onChange }) => {
  const [h, s, l] = isValidHex(hex) ? hexToHsl(hex) : [220, 70, 50];
  const [localHex, setLocalHex] = useState(hex);
  const squareRef = useRef(null);
  const hueRef = useRef(null);
  const dragging = useRef(null);
  useEffect(() => setLocalHex(hex), [hex]);

  const fromSquare = useCallback((e, ref) => {
    const r = ref.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    const y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
    const v = hslToHex(h, Math.round(x*100), Math.round((1-y)*100));
    onChange(v); setLocalHex(v);
  }, [h, onChange]);

  const fromHue = useCallback((e, ref) => {
    const r = ref.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    const v = hslToHex(Math.round(x*360), s, l);
    onChange(v); setLocalHex(v);
  }, [s, l, onChange]);

  useEffect(() => {
    const move = e => { if (dragging.current === 'sq') fromSquare(e, squareRef); else if (dragging.current === 'hue') fromHue(e, hueRef); };
    const up = () => { dragging.current = null; };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); };
  }, [fromSquare, fromHue]);

  return (
    <div className="space-y-3 select-none">
      <div ref={squareRef} className="relative w-full h-32 rounded-lg cursor-crosshair"
        style={{ background: `hsl(${h},100%,50%)` }}
        onMouseDown={e => { e.preventDefault(); dragging.current = 'sq'; fromSquare(e, squareRef); }}>
        <div className="absolute inset-0 rounded-lg" style={{ background: 'linear-gradient(to right,white,transparent)' }} />
        <div className="absolute inset-0 rounded-lg" style={{ background: 'linear-gradient(to top,black,transparent)' }} />
        <div className="absolute w-4 h-4 rounded-full border-2 border-white shadow-md -translate-x-1/2 -translate-y-1/2 pointer-events-none"
          style={{ left: `${s}%`, top: `${100-l}%`, background: hex }} />
      </div>
      <div ref={hueRef} className="relative w-full h-4 rounded-full cursor-pointer"
        style={{ background: 'linear-gradient(to right,hsl(0,100%,50%),hsl(60,100%,50%),hsl(120,100%,50%),hsl(180,100%,50%),hsl(240,100%,50%),hsl(300,100%,50%),hsl(360,100%,50%))' }}
        onMouseDown={e => { e.preventDefault(); dragging.current = 'hue'; fromHue(e, hueRef); }}>
        <div className="absolute top-1/2 w-5 h-5 rounded-full border-2 border-white shadow-md -translate-x-1/2 -translate-y-1/2 pointer-events-none"
          style={{ left: `${(h/360)*100}%`, background: `hsl(${h},100%,50%)` }} />
      </div>
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 rounded border border-border shrink-0" style={{ background: hex }} />
        <input className="flex-1 bg-surface border border-border text-bright text-xs rounded px-2 py-1 font-mono uppercase"
          value={localHex} maxLength={7} placeholder="#6366f1"
          onChange={e => { setLocalHex(e.target.value); if (isValidHex(e.target.value)) onChange(e.target.value); }} />
      </div>
    </div>
  );
};

const RunOutput = ({ runId }) => {
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await api.getRun(runId);
        if (!cancelled) {
          setRun(res.data); setLoading(false);
          if (!['completed','failed','cancelled','rejected'].includes(res.data?.status)) setTimeout(poll, 3000);
        }
      } catch { if (!cancelled) setLoading(false); }
    };
    poll();
    return () => { cancelled = true; };
  }, [runId]);

  if (loading) return <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 text-accent animate-spin" /><span className="ml-3 text-muted">Loading run…</span></div>;
  if (!run) return <p className="text-muted py-10 text-center">Run not found.</p>;

  const phases = run.phases || [];
  const sc = { completed:'text-emerald-400', failed:'text-red-400', running:'text-accent', queued:'text-yellow-400' };
  const bc = { completed:'bg-emerald-400', failed:'bg-red-400', running:'bg-accent animate-pulse', queued:'bg-border' };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h3 className="text-lg font-bold text-bright">{run.project_name || 'Factory Run'}</h3>
          <span className={`text-sm font-semibold ${sc[run.status] || 'text-muted'}`}>{run.status}</span>
        </div>
        <button onClick={() => navigate(`/project/${runId}`)}
          className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-semibold rounded-lg transition-colors">
          <ExternalLink className="w-4 h-4" /> Full View
        </button>
      </div>
      {phases.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-bold text-muted uppercase tracking-widest">Phases</h4>
          {phases.map((ph, i) => (
            <div key={i} className="flex items-center gap-3 p-3 bg-surface rounded-lg border border-border">
              <div className={`w-2 h-2 rounded-full shrink-0 ${bc[ph.status] || 'bg-border'}`} />
              <span className="text-sm text-bright flex-1">{ph.name || ph.phase}</span>
              <span className={`text-xs ${sc[ph.status] || 'text-muted'}`}>{ph.status}</span>
            </div>
          ))}
        </div>
      )}
      {run.status === 'completed' && (
        <div className="flex flex-wrap gap-3">
          {run.artifact_url && (
            <a href={run.artifact_url} className="flex items-center gap-2 px-4 py-2 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-sm font-semibold rounded-lg hover:bg-emerald-500/20 transition-colors">
              <ExternalLink className="w-4 h-4" /> Download Artifact
            </a>
          )}
          <button onClick={() => navigate(`/project/${runId}`)}
            className="flex items-center gap-2 px-4 py-2 bg-accent/10 border border-accent/30 text-accent text-sm font-semibold rounded-lg hover:bg-accent/20 transition-colors">
            <ExternalLink className="w-4 h-4" /> View Project
          </button>
        </div>
      )}
    </div>
  );
};

// ── Main Component ─────────────────────────────────────────────────────────────
const ProjectDesigner = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { id: urlRunId } = useParams();

  const [activeTab, setActiveTab] = useState(0);
  const [spec, setSpec] = useState(JSON.parse(JSON.stringify(DEFAULT_SPEC)));

  // ── Understand tab state ───────────────────────────────────────────────────
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [projectName, setProjectName] = useState(searchParams.get('name') || '');
  const [requirement, setRequirement] = useState('');
  const [domain, setDomain] = useState(searchParams.get('template') || 'general');
  const [projectMode, setProjectMode] = useState('new'); // 'new' | 'existing'

  // File upload
  const [uploadFilename, setUploadFilename] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const fileInputRef = useRef(null);

  // Repo
  const [repoType, setRepoType] = useState('github');
  const [repoUrl, setRepoUrl] = useState('');
  const [repoToken, setRepoToken] = useState('');
  const [repoSshKey, setRepoSshKey] = useState('');
  const [gitlabUrl, setGitlabUrl] = useState('https://gitlab.com');
  const [fetchingRepo, setFetchingRepo] = useState(false);
  const [repoContext, setRepoContext] = useState('');
  const [repoFetched, setRepoFetched] = useState('');

  // Schema import
  const [schemaOpen, setSchemaOpen] = useState(false);
  const [schemaConnStr, setSchemaConnStr] = useState('');
  const [importingSchema, setImportingSchema] = useState(false);
  const [importedSchema, setImportedSchema] = useState(null);
  const [schemaError, setSchemaError] = useState('');

  // ── Preview tab state ──────────────────────────────────────────────────────
  const [models, setModels] = useState(DEFAULT_MODELS);
  const [model, setModel] = useState(DEFAULT_MODELS[0].value);
  const [priority, setPriority] = useState('Normal');
  const [estimate, setEstimate] = useState(null);

  // ── Design tab state ───────────────────────────────────────────────────────
  const [activeColorSlot, setActiveColorSlot] = useState('primary');

  // ── Launch state ──────────────────────────────────────────────────────────
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState('');
  const [runId, setRunId] = useState(urlRunId || null);

  // ── Init from URL params ───────────────────────────────────────────────────
  useEffect(() => {
    if (urlRunId) { setRunId(urlRunId); setActiveTab(4); }
  }, [urlRunId]);

  useEffect(() => {
    const tpl = searchParams.get('template');
    if (tpl) {
      const match = TEMPLATES.find(t => t.id === tpl || t.domain === tpl);
      if (match) applyTemplate(match);
    }
  }, []); // eslint-disable-line

  // ── Fetch LLM models ───────────────────────────────────────────────────────
  useEffect(() => {
    api.getLlmConfig().then(res => {
      const d = res.data || {};
      const extra = [];
      if (d.openrouter_heavy_model) extra.push({ value: d.openrouter_heavy_model, label: `${d.openrouter_heavy_model} (OpenRouter)` });
      if (d.ollama_model) extra.push({ value: d.ollama_model, label: `${d.ollama_model} (Ollama)` });
      const all = extra.length ? [...DEFAULT_MODELS, ...extra] : DEFAULT_MODELS;
      setModels(all);
      const primary = d.primary_llm || 'anthropic';
      let def = DEFAULT_MODELS[0].value;
      if (primary === 'openrouter' && d.openrouter_heavy_model) def = d.openrouter_heavy_model;
      else if (primary === 'ollama' && d.ollama_model) def = d.ollama_model;
      setModel(all.some(m => m.value === def) ? def : all[0].value);
    }).catch(() => {});
  }, []);

  // ── Fetch cost estimate when entering Preview ──────────────────────────────
  useEffect(() => {
    if (activeTab === 3) {
      api.estimateCost({ domain, backend: spec.backend.framework, database: spec.backend.database, scale: 'small' })
        .then(res => setEstimate(res.data))
        .catch(() => {});
    }
  }, [activeTab, domain, spec.backend.framework, spec.backend.database]);

  // ── Helpers ────────────────────────────────────────────────────────────────
  const updateSpec = (section, key, value) =>
    setSpec(prev => ({ ...prev, [section]: { ...prev[section], [key]: value } }));

  const applyTemplate = (tpl) => {
    setSelectedTemplate(tpl.id);
    if (!projectName) setProjectName(tpl.label !== 'Custom' ? tpl.label : '');
    if (tpl.id !== 'custom') setRequirement(tpl.prompt || '');
    setDomain(tpl.domain || 'general');
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true); setUploadError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await api.uploadRequirementFile(fd);
      if (res.data?.error) { setUploadError(res.data.error); return; }
      const text = res.data?.text || '';
      setUploadFilename(file.name);
      if (text) setRequirement(prev => prev ? prev + '\n\n' + text : text);
    } catch (e) {
      setUploadError('Upload failed: ' + (e.message || 'unknown'));
    } finally {
      setUploading(false);
    }
  };

  const handleFetchRepo = async () => {
    if (!repoUrl.trim()) return;
    setFetchingRepo(true); setRepoContext(''); setUploadError('');
    try {
      const payload = { type: repoType, url: repoUrl.trim() };
      if (repoToken.trim()) payload.token = repoToken.trim();
      if (repoSshKey.trim()) payload.ssh_key = repoSshKey.trim();
      if (repoType === 'gitlab' && gitlabUrl.trim()) payload.gitlab_url = gitlabUrl.trim();
      const res = await api.client.post('/factory/fetch-repo', payload);
      setRepoContext(res.data?.context || '');
      setRepoFetched(res.data?.url || repoUrl);
    } catch (e) {
      setUploadError('Repo fetch failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setFetchingRepo(false);
    }
  };

  const handleImportSchema = async () => {
    if (!schemaConnStr.trim()) return;
    setImportingSchema(true); setSchemaError(''); setImportedSchema(null);
    try {
      const res = await api.client.post('/factory/import-schema', { connection_string: schemaConnStr.trim() });
      if (res.data?.error) setSchemaError(res.data.error);
      else setImportedSchema(res.data);
    } catch (e) {
      setSchemaError('Import failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setImportingSchema(false);
    }
  };

  const handleLaunch = async () => {
    if (!requirement.trim()) { setLaunchError('Project requirement is required.'); return; }
    setLaunching(true); setLaunchError('');
    try {
      const designerSpec = {
        frontend: spec.frontend,
        backend: spec.backend,
        infra: spec.infra,
        features: spec.features,
        design: {
          primary_hex: spec.design.primary,
          secondary_hex: spec.design.secondary,
          background_hex: spec.design.background,
          surface_hex: spec.design.surface,
          font_pairing: spec.design.font_pairing,
          border_radius: spec.design.border_radius,
          layout: spec.design.layout,
          density: spec.design.density,
        },
      };
      const rawInput = requirement.trim() + (repoContext ? `\n\nExisting codebase context:\n${repoContext.slice(0, 3000)}` : '');
      const payload = {
        raw_input: rawInput,
        project_name: projectName.trim() || undefined,
        domain,
        model_preference: model,
        priority: priority.toLowerCase(),
        client_id: (projectName.trim() || 'project').toLowerCase().replace(/\s+/g, '-'),
        codebase_mode: projectMode,
        designer_spec: designerSpec,
        ...(importedSchema ? { existing_schema: importedSchema } : {}),
      };
      const res = await api.startPipeline(payload);
      const newRunId = res.data?.run_id;
      if (newRunId) {
        setRunId(newRunId);
        setActiveTab(4);
        navigate(`/designer/${newRunId}`, { replace: true });
      }
    } catch (err) {
      setLaunchError(err.response?.data?.detail || err.message || 'Failed to launch build.');
    } finally {
      setLaunching(false);
    }
  };

  const complexity = calcComplexity(spec);

  // ── Tab 1: Understand ──────────────────────────────────────────────────────
  const renderUnderstand = () => (
    <div className="space-y-7">
      {/* Template grid */}
      <div>
        <p className="text-xs font-bold text-muted uppercase tracking-widest mb-3">Quick Start — pick a template</p>
        <div className="grid grid-cols-4 sm:grid-cols-6 gap-2">
          {TEMPLATES.map(tpl => (
            <button key={tpl.id} type="button" onClick={() => applyTemplate(tpl)}
              className={`flex flex-col items-center gap-1 p-3 rounded-xl border text-xs font-semibold transition-all ${
                selectedTemplate === tpl.id ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-accent/40 hover:text-bright'
              }`}>
              <span className="text-xl">{tpl.icon}</span>
              <span className="leading-tight text-center">{tpl.label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="h-px bg-border" />

      {/* Mode toggle */}
      <div>
        <p className="text-xs font-bold text-muted uppercase tracking-widest mb-3">Build mode</p>
        <div className="flex gap-3">
          {[['new','✨','Start fresh'],['existing','🔗','Improve existing codebase']].map(([mode,icon,label]) => (
            <button key={mode} type="button" onClick={() => setProjectMode(mode)}
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border text-sm font-semibold transition-all ${
                projectMode === mode ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-accent/40'
              }`}>
              <span>{icon}</span><span>{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Name + requirement */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="sm:col-span-1">
          <label className="block text-xs font-bold text-muted uppercase tracking-widest mb-1.5">Project Name</label>
          <input className="w-full bg-surface border border-border text-bright rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-accent transition-colors"
            placeholder="My Awesome App" value={projectName} onChange={e => setProjectName(e.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <label className="block text-xs font-bold text-muted uppercase tracking-widest mb-1.5">Domain</label>
          <select value={domain} onChange={e => setDomain(e.target.value)}
            className="w-full bg-surface border border-border text-bright rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-accent transition-colors">
            {TEMPLATES.map(t => <option key={t.domain} value={t.domain}>{t.icon} {t.label}</option>)}
          </select>
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs font-bold text-muted uppercase tracking-widest">
            Requirement <span className="text-red-400">*</span>
          </label>
          <div className="flex items-center gap-2">
            {uploadFilename && <span className="text-[10px] text-emerald-400">📎 {uploadFilename}</span>}
            <button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploading}
              className="text-[10px] px-2.5 py-1 bg-surface hover:bg-border border border-border text-muted hover:text-bright rounded-md transition-colors disabled:opacity-50">
              {uploading ? <Loader2 className="w-3 h-3 animate-spin inline" /> : <Upload className="w-3 h-3 inline mr-1" />}
              {uploading ? 'Reading…' : 'Import file'}
            </button>
            <input ref={fileInputRef} type="file" accept=".txt,.md,.pdf,.docx,.rst" className="hidden" onChange={handleFileUpload} />
          </div>
        </div>
        <textarea value={requirement} onChange={e => setRequirement(e.target.value)} rows={7}
          placeholder="Describe what you want to build in detail. Include user stories, key features, integrations, and any constraints…"
          className="w-full bg-surface border border-border text-bright rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-accent transition-colors resize-none" />
        {uploadError && <p className="text-xs text-red-400 mt-1">{uploadError}</p>}
        <p className="text-xs text-muted mt-1">{requirement.length} characters</p>
      </div>

      {/* Existing codebase section */}
      {projectMode === 'existing' && (
        <div className="space-y-3 bg-surface border border-border rounded-xl p-4">
          <p className="text-xs font-bold text-muted uppercase tracking-widest">Connect Existing Codebase</p>
          <div className="flex gap-2">
            {[['github','GitHub'],['gitlab','GitLab'],['ssh','SSH']].map(([t,label]) => (
              <button key={t} type="button" onClick={() => setRepoType(t)}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-colors ${repoType === t ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>
                {label}
              </button>
            ))}
          </div>
          {repoType === 'gitlab' && (
            <input type="url" value={gitlabUrl} onChange={e => setGitlabUrl(e.target.value)}
              placeholder="https://gitlab.com (or self-hosted)"
              className="w-full bg-panel border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
          )}
          <input type={repoType === 'ssh' ? 'text' : 'url'} value={repoUrl} onChange={e => setRepoUrl(e.target.value)}
            placeholder={repoType === 'ssh' ? 'git@github.com:owner/repo.git' : `https://${repoType === 'gitlab' ? 'gitlab.com' : 'github.com'}/owner/repo`}
            className="w-full bg-panel border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
          {repoType !== 'ssh' ? (
            <input type="password" value={repoToken} onChange={e => setRepoToken(e.target.value)}
              placeholder={`${repoType === 'gitlab' ? 'GitLab' : 'GitHub'} Personal Access Token (private repos)`}
              className="w-full bg-panel border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
          ) : (
            <textarea value={repoSshKey} onChange={e => setRepoSshKey(e.target.value)} rows={4}
              placeholder="Paste PEM private SSH key (-----BEGIN OPENSSH PRIVATE KEY-----)"
              className="w-full bg-panel border border-border rounded-lg px-3 py-2 text-xs text-bright font-mono focus:outline-none focus:border-accent resize-none" />
          )}
          <div className="flex items-center gap-3">
            <button type="button" onClick={handleFetchRepo} disabled={fetchingRepo || !repoUrl.trim()}
              className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors">
              {fetchingRepo ? 'Fetching…' : 'Fetch Repo Context'}
            </button>
            {repoFetched && <p className="text-xs text-emerald-400">✅ Loaded from {repoFetched}</p>}
          </div>
        </div>
      )}

      {/* Schema import */}
      <div className="border border-border rounded-xl overflow-hidden">
        <button type="button" onClick={() => setSchemaOpen(o => !o)}
          className="w-full flex items-center justify-between px-4 py-3 bg-surface hover:bg-surface/80 transition-colors text-left">
          <span className="flex items-center gap-2 text-xs font-bold text-muted uppercase tracking-widest">
            <Database className="w-3.5 h-3.5" />
            Import existing schema
            {importedSchema && <span className="normal-case text-emerald-400 font-normal">— {importedSchema.tables?.length} tables imported</span>}
          </span>
          {schemaOpen ? <ChevronDown className="w-4 h-4 text-muted" /> : <ChevronRight className="w-4 h-4 text-muted" />}
        </button>
        {schemaOpen && (
          <div className="px-4 pb-4 pt-3 space-y-3 border-t border-border bg-panel">
            <p className="text-xs text-muted">Connect a PostgreSQL, MySQL, or SQLite database — AetherOS reads the schema and feeds it into the architecture phase.</p>
            <input type="password" value={schemaConnStr} onChange={e => setSchemaConnStr(e.target.value)}
              placeholder="postgresql://user:pass@host:5432/dbname"
              className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright font-mono focus:outline-none focus:border-accent" />
            <div className="flex items-center gap-3">
              <button type="button" onClick={handleImportSchema} disabled={importingSchema || !schemaConnStr.trim()}
                className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors">
                {importingSchema ? 'Connecting…' : 'Test & Import'}
              </button>
              {importedSchema && !schemaError && (
                <span className="text-xs text-emerald-400">✅ {importedSchema.tables?.length} tables ready</span>
              )}
              {schemaError && <span className="text-xs text-red-400">{schemaError}</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );

  // ── Tab 2: Tech Stack ──────────────────────────────────────────────────────
  const renderTechStack = () => (
    <div className="space-y-8">
      <StackGroup title="Frontend" values={spec.frontend} onChange={(k,v) => updateSpec('frontend',k,v)} fields={[
        { key:'framework',        label:'Framework',        options:STACK.frontend.framework },
        { key:'styling',          label:'Styling',          options:STACK.frontend.styling },
        { key:'state_management', label:'State Management', options:STACK.frontend.state_management },
        { key:'form_library',     label:'Form Library',     options:STACK.frontend.form_library },
        { key:'data_fetching',    label:'Data Fetching',    options:STACK.frontend.data_fetching },
      ]} />
      <div className="h-px bg-border" />
      <StackGroup title="Backend" values={spec.backend} onChange={(k,v) => updateSpec('backend',k,v)} fields={[
        { key:'framework', label:'Framework',     options:STACK.backend.framework },
        { key:'database',  label:'Database',      options:STACK.backend.database },
        { key:'orm',       label:'ORM',           options:STACK.backend.orm },
        { key:'auth',      label:'Auth Strategy', options:STACK.backend.auth },
        { key:'api_style', label:'API Style',     options:STACK.backend.api_style },
      ]} />
      <div className="h-px bg-border" />
      <StackGroup title="Infrastructure" values={spec.infra} onChange={(k,v) => updateSpec('infra',k,v)} fields={[
        { key:'deployment',   label:'Deployment Target', options:STACK.infra.deployment },
        { key:'cache',        label:'Cache',             options:STACK.infra.cache },
        { key:'queue',        label:'Queue',             options:STACK.infra.queue },
        { key:'file_storage', label:'File Storage',      options:STACK.infra.file_storage },
        { key:'email',        label:'Email',             options:STACK.infra.email },
      ]} />
      <div className="h-px bg-border" />
      <div>
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest mb-3">Features</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {[
            {key:'multi_tenancy',     label:'Multi-tenancy'},
            {key:'audit_log',         label:'Audit Log'},
            {key:'rate_limiting',     label:'Rate Limiting'},
            {key:'webhooks_out',      label:'Webhooks Out'},
            {key:'internationalization',label:'Internationalization'},
          ].map(f => (
            <div key={f.key}>
              <label className="block text-xs text-muted mb-1">{f.label}</label>
              <button type="button" onClick={() => updateSpec('features', f.key, !spec.features[f.key])}
                className={`w-full px-3 py-2 rounded-lg text-sm font-semibold border transition-all ${spec.features[f.key] ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-border/80'}`}>
                {spec.features[f.key] ? 'Yes' : 'No'}
              </button>
            </div>
          ))}
          <div>
            <label className="block text-xs text-muted mb-1">Real-time</label>
            <SearchableSelect value={spec.features.realtime} options={['WebSocket','SSE','None']} onChange={v => updateSpec('features','realtime',v)} />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Payments</label>
            <SearchableSelect value={spec.features.payments} options={['Stripe','Razorpay','Paddle','None']} onChange={v => updateSpec('features','payments',v)} />
          </div>
        </div>
      </div>
    </div>
  );

  // ── Tab 3: Design ──────────────────────────────────────────────────────────
  const renderDesign = () => (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Colors */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Colors</h3>
        <div className="flex gap-1">
          {COLOR_SLOTS.map(slot => (
            <button key={slot} type="button" onClick={() => setActiveColorSlot(slot)}
              className={`flex-1 py-1.5 text-xs font-semibold rounded capitalize transition-all ${activeColorSlot === slot ? 'bg-accent text-white' : 'bg-surface border border-border text-muted hover:text-bright'}`}>
              {slot}
            </button>
          ))}
        </div>
        <HslPicker hex={spec.design[activeColorSlot]} onChange={v => updateSpec('design', activeColorSlot, v)} />
        <div className="flex gap-2">
          {COLOR_SLOTS.map(slot => (
            <div key={slot} className="flex-1 flex flex-col items-center gap-1">
              <div onClick={() => setActiveColorSlot(slot)}
                className={`w-full h-8 rounded-lg cursor-pointer border-2 transition-all ${activeColorSlot === slot ? 'border-white' : 'border-transparent'}`}
                style={{ background: spec.design[slot] }} />
              <span className="text-[9px] text-muted capitalize">{slot}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Typography */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Typography</h3>
        <div>
          <label className="block text-xs text-muted mb-2">Font Pairing</label>
          {FONT_PAIRS.map(fp => (
            <button key={fp} type="button" onClick={() => updateSpec('design','font_pairing',fp)}
              className={`w-full flex items-center justify-between px-3 py-2.5 mb-1.5 rounded-lg border text-xs transition-all ${spec.design.font_pairing === fp ? 'border-accent bg-accent/10 text-accent' : 'border-border text-bright hover:border-accent/40'}`}>
              {fp}{spec.design.font_pairing === fp && <Check className="w-3.5 h-3.5" />}
            </button>
          ))}
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Font Size Scale</label>
          <div className="grid grid-cols-3 gap-1.5">
            {['Compact','Normal','Comfortable'].map(s => (
              <button key={s} type="button" onClick={() => updateSpec('design','font_scale',s)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${spec.design.font_scale === s ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{s}</button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Border Radius</label>
          <div className="grid grid-cols-2 gap-1.5">
            {['Sharp (0px)','Subtle (4px)','Rounded (8px)','Pill (16px)'].map(r => (
              <button key={r} type="button" onClick={() => updateSpec('design','border_radius',r)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${spec.design.border_radius === r ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{r}</button>
            ))}
          </div>
        </div>
      </div>

      {/* Layout */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Layout</h3>
        <div className="space-y-2">
          {LAYOUTS.map(lay => (
            <button key={lay.id} type="button" onClick={() => updateSpec('design','layout',lay.id)}
              className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all ${spec.design.layout === lay.id ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/40'}`}>
              <div className="w-16 h-10 shrink-0 rounded overflow-hidden border border-border/50">{lay.svg}</div>
              <span className={`text-xs font-semibold flex-1 text-left ${spec.design.layout === lay.id ? 'text-accent' : 'text-bright'}`}>{lay.label}</span>
              {spec.design.layout === lay.id && <Check className="w-4 h-4 text-accent" />}
            </button>
          ))}
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Component Density</label>
          <div className="grid grid-cols-3 gap-1.5">
            {['Compact','Normal','Spacious'].map(d => (
              <button key={d} type="button" onClick={() => updateSpec('design','density',d)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${spec.design.density === d ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{d}</button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Card Style</label>
          <div className="grid grid-cols-2 gap-1.5">
            {['Flat','Subtle Shadow','Elevated','Glass'].map(cs => (
              <button key={cs} type="button" onClick={() => updateSpec('design','card_style',cs)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${spec.design.card_style === cs ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>{cs}</button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  // ── Tab 4: Preview ─────────────────────────────────────────────────────────
  const renderPreview = () => {
    const cx = complexity;
    return (
      <div className="space-y-6">
        {/* Spec card */}
        <div className="bg-surface border border-border rounded-2xl p-6 space-y-5">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="text-xl font-bold text-bright">{projectName || 'Untitled Project'}</h3>
              <p className="text-sm text-muted mt-0.5">{TEMPLATES.find(t => t.domain === domain)?.label || domain}</p>
            </div>
            <div className="flex gap-2">
              {COLOR_SLOTS.map(slot => (
                <div key={slot} className="w-5 h-5 rounded-full border border-white/10" style={{ background: spec.design[slot] }} title={slot} />
              ))}
            </div>
          </div>
          {requirement && (
            <div className="p-4 bg-panel rounded-xl border border-border">
              <p className="text-xs text-muted font-bold uppercase tracking-widest mb-1.5">Requirement</p>
              <p className="text-sm text-bright leading-relaxed line-clamp-4">{requirement}</p>
            </div>
          )}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {[
              ['Frontend', spec.frontend.framework],['Styling', spec.frontend.styling],['State', spec.frontend.state_management],
              ['Backend', spec.backend.framework],['Database', spec.backend.database],['Auth', spec.backend.auth],
              ['API', spec.backend.api_style],['Deploy', spec.infra.deployment],['Cache', spec.infra.cache],
            ].map(([label, value]) => (
              <div key={label}>
                <p className="text-[10px] font-bold text-muted uppercase tracking-widest">{label}</p>
                <p className="text-sm text-bright mt-0.5 truncate">{value}</p>
              </div>
            ))}
          </div>
          {/* Active features */}
          <div className="flex flex-wrap gap-2">
            {spec.features.multi_tenancy && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Multi-tenant</span>}
            {spec.features.audit_log && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Audit Log</span>}
            {spec.features.rate_limiting && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Rate Limiting</span>}
            {spec.features.webhooks_out && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Webhooks</span>}
            {spec.features.internationalization && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">i18n</span>}
            {spec.features.realtime !== 'None' && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Realtime ({spec.features.realtime})</span>}
            {spec.features.payments !== 'None' && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Payments ({spec.features.payments})</span>}
          </div>
          <div className="flex flex-wrap gap-4 text-sm border-t border-border pt-4">
            <span className="text-muted">Font: <span className="text-bright">{spec.design.font_pairing}</span></span>
            <span className="text-muted">Radius: <span className="text-bright">{spec.design.border_radius}</span></span>
            <span className="text-muted">Layout: <span className="text-bright">{LAYOUTS.find(l => l.id === spec.design.layout)?.label}</span></span>
          </div>
        </div>

        {/* Complexity + cost */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="flex items-center gap-4 p-4 bg-surface border border-border rounded-xl">
            <div>
              <p className="text-xs text-muted font-bold uppercase tracking-widest">Complexity</p>
              <p className={`text-2xl font-bold mt-0.5 ${cx.color}`}>{cx.label}</p>
            </div>
            <div className="flex gap-1.5 ml-2">
              {[1,2,3,4].map(n => (
                <div key={n} className={`h-8 w-4 rounded transition-colors ${n <= cx.bar ? cx.bgColor : 'bg-border'}`} />
              ))}
            </div>
          </div>
          {estimate && (
            <div className="p-4 bg-emerald-950/40 border border-emerald-800/40 rounded-xl">
              <p className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-1">Estimated Hosting</p>
              <p className="text-xl font-bold text-emerald-300">{estimate.range}</p>
              <p className="text-[10px] text-muted mt-1">{estimate.note}</p>
            </div>
          )}
        </div>

        {/* Model + Priority */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-5 bg-surface border border-border rounded-xl">
          <div>
            <label className="block text-xs font-bold text-muted uppercase tracking-widest mb-2">LLM Model</label>
            <select value={model} onChange={e => setModel(e.target.value)}
              className="w-full bg-panel border border-border text-bright rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-accent">
              {models.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-bold text-muted uppercase tracking-widest mb-2">Priority</label>
            <div className="flex gap-2">
              {PRIORITIES.map(p => (
                <button key={p} type="button" onClick={() => setPriority(p)}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-semibold transition-colors ${priority === p ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-accent/50'}`}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        </div>

        {launchError && (
          <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
            <X className="w-4 h-4 text-red-400 shrink-0" />
            <p className="text-sm text-red-400">{launchError}</p>
          </div>
        )}

        <div className="flex gap-3">
          <button type="button"
            onClick={() => {
              const blob = new Blob([JSON.stringify({ projectName, requirement, domain, ...spec }, null, 2)], { type: 'application/json' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a'); a.href = url; a.download = `${projectName || 'spec'}.json`; a.click();
              URL.revokeObjectURL(url);
            }}
            className="px-5 py-2.5 border border-border text-muted hover:text-bright hover:border-accent/50 text-sm font-semibold rounded-xl transition-colors">
            Save Spec
          </button>
          <button type="button" onClick={handleLaunch} disabled={launching || !requirement.trim()}
            className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-bold rounded-xl transition-colors">
            {launching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
            {launching ? 'Launching…' : '🚀 Launch Build'}
          </button>
        </div>
      </div>
    );
  };

  // ── Tab 5: Output ──────────────────────────────────────────────────────────
  const renderOutput = () => (
    <div>
      {runId ? <RunOutput runId={runId} /> : (
        <div className="py-20 text-center">
          <Wand2 className="w-12 h-12 text-muted/30 mx-auto mb-4" />
          <p className="text-muted text-sm">No build launched yet.</p>
          <p className="text-muted/60 text-xs mt-1">Complete the spec and click Launch Build on the Preview tab.</p>
          <button onClick={() => setActiveTab(3)}
            className="mt-4 px-5 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-semibold rounded-xl transition-colors">
            Go to Preview
          </button>
        </div>
      )}
    </div>
  );

  const tabContent = [renderUnderstand, renderTechStack, renderDesign, renderPreview, renderOutput];

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="max-w-5xl mx-auto py-6 px-4">
      <div className="mb-6 flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <Wand2 className="w-6 h-6 text-accent" />
            <h1 className="text-2xl font-bold text-bright">New Project</h1>
          </div>
          <p className="text-sm text-muted">Design your stack, configure your app, and launch the build pipeline.</p>
        </div>
        {requirement.trim() && (
          <button type="button" onClick={handleLaunch} disabled={launching}
            className="flex items-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-sm font-bold rounded-xl transition-colors">
            {launching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
            {launching ? 'Launching…' : 'Quick Launch'}
          </button>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-border mb-6 overflow-x-auto">
        {TABS.map((tab, i) => (
          <button key={tab} onClick={() => i < 4 || runId ? setActiveTab(i) : null}
            className={`px-5 py-3 text-sm font-semibold whitespace-nowrap border-b-2 transition-colors ${
              activeTab === i ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-bright'
            } ${i === 4 && !runId ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}>
            {tab}
            {i === 4 && runId && <span className="ml-1.5 w-2 h-2 rounded-full bg-emerald-400 inline-block align-middle" />}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="min-h-[400px]">
        {tabContent[activeTab]()}
      </div>

      {/* Bottom nav */}
      {activeTab < 4 && (
        <div className="flex justify-between mt-8 pt-4 border-t border-border">
          <button onClick={() => setActiveTab(p => Math.max(0, p - 1))} disabled={activeTab === 0}
            className="px-5 py-2.5 border border-border text-muted hover:text-bright disabled:opacity-30 text-sm font-semibold rounded-xl transition-colors">
            ← Back
          </button>
          {activeTab < 3 && (
            <button onClick={() => setActiveTab(p => p + 1)}
              className="px-5 py-2.5 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-xl transition-colors">
              Next →
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default ProjectDesigner;
