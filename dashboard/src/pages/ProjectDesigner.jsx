import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate, useSearchParams, useParams } from 'react-router-dom';
import { Wand2, Upload, Link, ChevronDown, Check, Loader2, X, ExternalLink } from 'lucide-react';
import { api } from '../api';

// ── Domains ────────────────────────────────────────────────────────────────────
const DOMAINS = [
  { id: 'saas', label: 'SaaS App', icon: '🏢' },
  { id: 'ecommerce', label: 'E-Commerce', icon: '🛒' },
  { id: 'analytics', label: 'Analytics Dashboard', icon: '📊' },
  { id: 'api', label: 'REST API', icon: '⚡' },
  { id: 'cms', label: 'CMS / Blog', icon: '✍️' },
  { id: 'social', label: 'Social Platform', icon: '👥' },
  { id: 'marketplace', label: 'Marketplace', icon: '🏪' },
  { id: 'healthcare', label: 'Healthcare', icon: '🏥' },
  { id: 'fintech', label: 'FinTech', icon: '💳' },
  { id: 'education', label: 'Learning Management', icon: '🎓' },
  { id: 'iot', label: 'IoT Dashboard', icon: '📡' },
  { id: 'general', label: 'Custom / General', icon: '🛠️' },
];

// ── Tech Stack Options ─────────────────────────────────────────────────────────
const STACK = {
  frontend: {
    framework: ['Next.js 14 App Router','Next.js 14 Pages Router','React + Vite','Vue 3 + Vite','Nuxt 3','SvelteKit','Astro','Angular 17','Vanilla JS'],
    styling: ['Tailwind CSS','Tailwind + shadcn/ui','Tailwind + Radix UI','Material UI v5','Ant Design 5','Chakra UI','Styled Components','CSS Modules'],
    state_management: ['React Context','Zustand','Jotai','Redux Toolkit','Pinia (Vue)','None'],
    form_library: ['React Hook Form + Zod','Formik','None'],
    data_fetching: ['TanStack Query','SWR','Axios','Native Fetch'],
  },
  backend: {
    framework: ['FastAPI','Django REST Framework','Express.js','NestJS','Spring Boot','Ruby on Rails','Laravel','Go Fiber','Go + chi'],
    database: ['PostgreSQL','MySQL 8','MongoDB 7','CockroachDB','SQLite','Supabase','PlanetScale'],
    orm: ['SQLAlchemy','Prisma','TypeORM','Drizzle','Tortoise ORM','Mongoose','GORM'],
    auth: ['JWT + refresh tokens','Session-based','OAuth2 social login','API Key','SAML SSO','Clerk','Auth0'],
    api_style: ['REST','GraphQL','REST + WebSocket','tRPC'],
  },
  infra: {
    deployment: ['Docker + Compose','Kubernetes','Railway','Fly.io','Vercel + Railway','AWS ECS'],
    cache: ['Redis','Memcached','None'],
    queue: ['Celery + Redis','BullMQ','RabbitMQ','None'],
    file_storage: ['Local','AWS S3','Cloudflare R2','Cloudinary'],
    email: ['Resend','SendGrid','SES','None'],
  },
};

const FONT_PAIRS = [
  { label: 'Inter + Inter (system)', heading: 'Inter', body: 'Inter' },
  { label: 'Geist + Geist Mono', heading: 'Geist', body: 'Geist Mono' },
  { label: 'Plus Jakarta Sans + Fira Code', heading: 'Plus Jakarta Sans', body: 'Fira Code' },
  { label: 'DM Sans + JetBrains Mono', heading: 'DM Sans', body: 'JetBrains Mono' },
  { label: 'Satoshi + IBM Plex Mono', heading: 'Satoshi', body: 'IBM Plex Mono' },
];

const LAYOUTS = [
  {
    id: 'sidebar-topbar', label: 'Sidebar Left + Top Bar',
    svg: (
      <svg viewBox="0 0 80 52" className="w-full h-full">
        <rect x="0" y="0" width="80" height="52" rx="3" fill="#1e293b"/>
        <rect x="0" y="0" width="18" height="52" rx="2" fill="#334155"/>
        <rect x="18" y="0" width="62" height="10" fill="#475569"/>
        <rect x="22" y="14" width="30" height="4" rx="1" fill="#64748b"/>
        <rect x="22" y="22" width="50" height="3" rx="1" fill="#475569"/>
        <rect x="22" y="29" width="42" height="3" rx="1" fill="#475569"/>
        <rect x="22" y="36" width="48" height="3" rx="1" fill="#475569"/>
      </svg>
    ),
  },
  {
    id: 'topbar-only', label: 'Top Bar only',
    svg: (
      <svg viewBox="0 0 80 52" className="w-full h-full">
        <rect x="0" y="0" width="80" height="52" rx="3" fill="#1e293b"/>
        <rect x="0" y="0" width="80" height="12" rx="2" fill="#475569"/>
        <rect x="8" y="16" width="30" height="4" rx="1" fill="#64748b"/>
        <rect x="8" y="24" width="64" height="3" rx="1" fill="#475569"/>
        <rect x="8" y="31" width="56" height="3" rx="1" fill="#475569"/>
        <rect x="8" y="38" width="60" height="3" rx="1" fill="#475569"/>
      </svg>
    ),
  },
  {
    id: 'sidebar-wide', label: 'Sidebar Left (wide)',
    svg: (
      <svg viewBox="0 0 80 52" className="w-full h-full">
        <rect x="0" y="0" width="80" height="52" rx="3" fill="#1e293b"/>
        <rect x="0" y="0" width="28" height="52" rx="2" fill="#334155"/>
        <rect x="32" y="8" width="24" height="4" rx="1" fill="#64748b"/>
        <rect x="32" y="16" width="44" height="3" rx="1" fill="#475569"/>
        <rect x="32" y="23" width="38" height="3" rx="1" fill="#475569"/>
        <rect x="32" y="30" width="42" height="3" rx="1" fill="#475569"/>
      </svg>
    ),
  },
  {
    id: 'split-panel', label: 'Split Panel',
    svg: (
      <svg viewBox="0 0 80 52" className="w-full h-full">
        <rect x="0" y="0" width="80" height="52" rx="3" fill="#1e293b"/>
        <rect x="0" y="0" width="80" height="10" rx="2" fill="#475569"/>
        <rect x="0" y="10" width="38" height="42" fill="#334155"/>
        <rect x="38" y="10" width="42" height="42" fill="#1e293b"/>
        <rect x="4" y="14" width="30" height="3" rx="1" fill="#64748b"/>
        <rect x="4" y="21" width="26" height="3" rx="1" fill="#475569"/>
        <rect x="42" y="14" width="32" height="3" rx="1" fill="#64748b"/>
        <rect x="42" y="21" width="28" height="3" rx="1" fill="#475569"/>
      </svg>
    ),
  },
  {
    id: 'minimal', label: 'Minimal (no sidebar)',
    svg: (
      <svg viewBox="0 0 80 52" className="w-full h-full">
        <rect x="0" y="0" width="80" height="52" rx="3" fill="#1e293b"/>
        <rect x="16" y="8" width="48" height="5" rx="1" fill="#64748b"/>
        <rect x="10" y="18" width="60" height="3" rx="1" fill="#475569"/>
        <rect x="10" y="25" width="54" height="3" rx="1" fill="#475569"/>
        <rect x="10" y="32" width="58" height="3" rx="1" fill="#475569"/>
        <rect x="28" y="40" width="24" height="6" rx="3" fill="#6366f1"/>
      </svg>
    ),
  },
];

// ── Helpers ────────────────────────────────────────────────────────────────────
function hslToHex(h, s, l) {
  s /= 100; l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => {
    const k = (n + h / 30) % 12;
    return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)))));
  };
  return '#' + [f(0), f(8), f(4)].map(v => v.toString(16).padStart(2, '0')).join('');
}

function hexToHsl(hex) {
  const r = parseInt(hex.slice(1,3),16)/255, g = parseInt(hex.slice(3,5),16)/255, b = parseInt(hex.slice(5,7),16)/255;
  const max = Math.max(r,g,b), min = Math.min(r,g,b);
  let h=0, s=0, l=(max+min)/2;
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

function isValidHex(h) { return /^#[0-9a-fA-F]{6}$/.test(h); }

// ── HSL Color Picker Component ─────────────────────────────────────────────────
const HslPicker = ({ hex, onChange }) => {
  const [h, s, l] = isValidHex(hex) ? hexToHsl(hex) : [220, 70, 50];
  const [localHex, setLocalHex] = useState(hex);
  const squareRef = useRef(null);
  const hueRef = useRef(null);
  const dragging = useRef(null);

  useEffect(() => { setLocalHex(hex); }, [hex]);

  const updateFromSquare = useCallback((e, ref) => {
    const rect = ref.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    const newS = Math.round(x * 100);
    const newL = Math.round((1 - y) * 100);
    const newHex = hslToHex(h, newS, newL);
    onChange(newHex);
    setLocalHex(newHex);
  }, [h, onChange]);

  const updateFromHue = useCallback((e, ref) => {
    const rect = ref.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const newH = Math.round(x * 360);
    const newHex = hslToHex(newH, s, l);
    onChange(newHex);
    setLocalHex(newHex);
  }, [s, l, onChange]);

  const onMouseDown = (type) => (e) => {
    e.preventDefault();
    dragging.current = type;
    if (type === 'square') updateFromSquare(e, squareRef);
    else updateFromHue(e, hueRef);
  };

  useEffect(() => {
    const onMove = (e) => {
      if (!dragging.current) return;
      if (dragging.current === 'square') updateFromSquare(e, squareRef);
      else updateFromHue(e, hueRef);
    };
    const onUp = () => { dragging.current = null; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [updateFromSquare, updateFromHue]);

  const handleHexInput = (v) => {
    setLocalHex(v);
    if (isValidHex(v)) onChange(v);
  };

  const slX = s; const slY = 100 - l;

  return (
    <div className="space-y-3 select-none">
      {/* SL square */}
      <div
        ref={squareRef}
        className="relative w-full h-36 rounded-lg cursor-crosshair"
        style={{ background: `hsl(${h},100%,50%)` }}
        onMouseDown={onMouseDown('square')}
      >
        <div className="absolute inset-0 rounded-lg" style={{ background: 'linear-gradient(to right, white, transparent)' }} />
        <div className="absolute inset-0 rounded-lg" style={{ background: 'linear-gradient(to top, black, transparent)' }} />
        <div
          className="absolute w-4 h-4 rounded-full border-2 border-white shadow-md -translate-x-1/2 -translate-y-1/2 pointer-events-none"
          style={{ left: `${slX}%`, top: `${slY}%`, background: hex }}
        />
      </div>
      {/* Hue bar */}
      <div
        ref={hueRef}
        className="relative w-full h-4 rounded-full cursor-pointer"
        style={{ background: 'linear-gradient(to right,hsl(0,100%,50%),hsl(30,100%,50%),hsl(60,100%,50%),hsl(90,100%,50%),hsl(120,100%,50%),hsl(150,100%,50%),hsl(180,100%,50%),hsl(210,100%,50%),hsl(240,100%,50%),hsl(270,100%,50%),hsl(300,100%,50%),hsl(330,100%,50%),hsl(360,100%,50%))' }}
        onMouseDown={onMouseDown('hue')}
      >
        <div
          className="absolute top-1/2 w-5 h-5 rounded-full border-2 border-white shadow-md -translate-x-1/2 -translate-y-1/2 pointer-events-none"
          style={{ left: `${(h/360)*100}%`, background: `hsl(${h},100%,50%)` }}
        />
      </div>
      {/* Hex input */}
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 rounded border border-border shrink-0" style={{ background: hex }} />
        <input
          className="flex-1 bg-surface border border-border text-bright text-xs rounded px-2 py-1 font-mono uppercase"
          value={localHex}
          onChange={e => handleHexInput(e.target.value)}
          maxLength={7}
          placeholder="#6366f1"
        />
      </div>
    </div>
  );
};

// ── SearchableSelect ───────────────────────────────────────────────────────────
const SearchableSelect = ({ value, options, onChange, placeholder }) => {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const filtered = options.filter(o => o.toLowerCase().includes(q.toLowerCase()));

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(p => !p)}
        className="w-full flex items-center justify-between px-3 py-2 bg-surface border border-border rounded-lg text-sm text-bright hover:border-accent/50 transition-colors"
      >
        <span className={value ? 'text-bright' : 'text-muted'}>{value || placeholder || 'Select...'}</span>
        <ChevronDown className="w-3.5 h-3.5 text-muted shrink-0" />
      </button>
      {open && (
        <div className="absolute z-50 w-full mt-1 bg-panel border border-border rounded-lg shadow-xl max-h-48 overflow-hidden flex flex-col">
          <div className="p-1.5 border-b border-border">
            <input
              autoFocus
              className="w-full bg-surface border border-border text-sm text-bright rounded px-2 py-1 outline-none"
              placeholder="Search..."
              value={q}
              onChange={e => setQ(e.target.value)}
            />
          </div>
          <div className="overflow-y-auto">
            {filtered.map(opt => (
              <button
                key={opt}
                type="button"
                onClick={() => { onChange(opt); setOpen(false); setQ(''); }}
                className="w-full flex items-center justify-between px-3 py-2 text-sm text-left hover:bg-border/30 text-bright transition-colors"
              >
                {opt}
                {value === opt && <Check className="w-3.5 h-3.5 text-accent" />}
              </button>
            ))}
            {filtered.length === 0 && <p className="px-3 py-2 text-xs text-muted">No results</p>}
          </div>
        </div>
      )}
    </div>
  );
};

// ── StackSection ───────────────────────────────────────────────────────────────
const StackSection = ({ title, fields, values, onChange }) => (
  <div>
    <h3 className="text-xs font-bold text-muted uppercase tracking-widest mb-3">{title}</h3>
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {fields.map(({ key, label, options, type }) => (
        <div key={key}>
          <label className="block text-xs text-muted mb-1">{label}</label>
          {type === 'toggle' ? (
            <button
              type="button"
              onClick={() => onChange(key, !values[key])}
              className={`px-3 py-2 rounded-lg text-sm font-semibold border transition-all w-full text-left ${
                values[key] ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted'
              }`}
            >
              {values[key] ? 'Yes' : 'No'}
            </button>
          ) : type === 'select-small' ? (
            <SearchableSelect value={values[key]} options={options} onChange={v => onChange(key, v)} />
          ) : (
            <SearchableSelect value={values[key]} options={options} onChange={v => onChange(key, v)} />
          )}
        </div>
      ))}
    </div>
  </div>
);

// ── Complexity calculator ──────────────────────────────────────────────────────
function calcComplexity(spec) {
  let score = 0;
  const fe = spec.frontend || {};
  const be = spec.backend || {};
  const inf = spec.infra || {};
  const ft = spec.features || {};

  if (['Next.js 14 App Router','NestJS','Angular 17'].includes(fe.framework)) score += 2;
  if (['Redux Toolkit'].includes(fe.state_management)) score += 1;
  if (['GraphQL','REST + WebSocket','tRPC'].includes(be.api_style)) score += 2;
  if (['Kubernetes','AWS ECS'].includes(inf.deployment)) score += 3;
  if (['Celery + Redis','BullMQ','RabbitMQ'].includes(inf.queue) && inf.queue !== 'None') score += 2;
  if (ft.multi_tenancy) score += 3;
  if (ft.realtime && ft.realtime !== 'None') score += 2;
  if (ft.payments && ft.payments !== 'None') score += 2;
  if (ft.internationalization) score += 1;
  if (ft.audit_log) score += 1;
  if (['SAML SSO','Clerk','Auth0'].includes(be.auth)) score += 2;

  if (score <= 3) return { label: 'Simple', color: 'text-emerald-400', bar: 1 };
  if (score <= 7) return { label: 'Moderate', color: 'text-yellow-400', bar: 2 };
  if (score <= 12) return { label: 'Complex', color: 'text-orange-400', bar: 3 };
  return { label: 'Enterprise', color: 'text-red-400', bar: 4 };
}

// ── Default spec ───────────────────────────────────────────────────────────────
const DEFAULT_SPEC = {
  frontend: {
    framework: 'React + Vite',
    styling: 'Tailwind + shadcn/ui',
    state_management: 'Zustand',
    form_library: 'React Hook Form + Zod',
    data_fetching: 'TanStack Query',
  },
  backend: {
    framework: 'FastAPI',
    database: 'PostgreSQL',
    orm: 'SQLAlchemy',
    auth: 'JWT + refresh tokens',
    api_style: 'REST',
  },
  infra: {
    deployment: 'Docker + Compose',
    cache: 'Redis',
    queue: 'None',
    file_storage: 'Local',
    email: 'Resend',
  },
  features: {
    multi_tenancy: false,
    audit_log: false,
    rate_limiting: true,
    webhooks_out: false,
    realtime: 'None',
    payments: 'None',
    internationalization: false,
  },
  design: {
    primary: '#6366f1',
    secondary: '#8b5cf6',
    background: '#0f172a',
    surface: '#1e293b',
    font_pairing: 'Inter + Inter (system)',
    font_scale: 'Normal',
    border_radius: 'Rounded (8px)',
    layout: 'sidebar-topbar',
    density: 'Normal',
    card_style: 'Subtle Shadow',
  },
};

// ── Tab bar ────────────────────────────────────────────────────────────────────
const TABS = ['Understand','Tech Stack','Design','Preview','Output'];

// ── RunOutput embedded component ───────────────────────────────────────────────
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
          setRun(res.data);
          setLoading(false);
          if (!['completed','failed','cancelled','rejected'].includes(res.data?.status)) {
            setTimeout(poll, 3000);
          }
        }
      } catch { if (!cancelled) setLoading(false); }
    };
    poll();
    return () => { cancelled = true; };
  }, [runId]);

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="w-8 h-8 text-accent animate-spin" />
      <span className="ml-3 text-muted">Loading run…</span>
    </div>
  );
  if (!run) return <p className="text-muted py-10 text-center">Run not found.</p>;

  const phases = run.phases || [];
  const statusColor = { completed: 'text-emerald-400', failed: 'text-red-400', running: 'text-accent', queued: 'text-yellow-400' };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold text-bright">{run.project_name || 'Factory Run'}</h3>
          <span className={`text-sm font-semibold ${statusColor[run.status] || 'text-muted'}`}>{run.status}</span>
        </div>
        <button
          onClick={() => navigate(`/project/${runId}`)}
          className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-semibold rounded-lg transition-colors"
        >
          <ExternalLink className="w-4 h-4" />
          Full View
        </button>
      </div>

      {/* Phase progress */}
      {phases.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-bold text-muted uppercase tracking-widest">Phases</h4>
          {phases.map((ph, i) => (
            <div key={i} className="flex items-center gap-3 p-3 bg-surface rounded-lg border border-border">
              <div className={`w-2 h-2 rounded-full shrink-0 ${ph.status === 'completed' ? 'bg-emerald-400' : ph.status === 'failed' ? 'bg-red-400' : ph.status === 'running' ? 'bg-accent animate-pulse' : 'bg-border'}`} />
              <span className="text-sm text-bright flex-1">{ph.name || ph.phase}</span>
              <span className={`text-xs ${statusColor[ph.status] || 'text-muted'}`}>{ph.status}</span>
            </div>
          ))}
        </div>
      )}

      {/* Artifacts */}
      {run.status === 'completed' && (
        <div className="flex flex-wrap gap-3">
          {run.artifact_url && (
            <a href={run.artifact_url} className="flex items-center gap-2 px-4 py-2 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-sm font-semibold rounded-lg hover:bg-emerald-500/20 transition-colors">
              <ExternalLink className="w-4 h-4" /> Download Artifact
            </a>
          )}
          <button
            onClick={() => navigate(`/project/${runId}`)}
            className="flex items-center gap-2 px-4 py-2 bg-accent/10 border border-accent/30 text-accent text-sm font-semibold rounded-lg hover:bg-accent/20 transition-colors"
          >
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
  const [spec, setSpec] = useState(() => {
    const base = JSON.parse(JSON.stringify(DEFAULT_SPEC));
    const template = searchParams.get('template');
    const name = searchParams.get('name');
    if (name) base._name = name;
    if (template) {
      const match = DOMAINS.find(d => d.id === template);
      if (match) base._domain = match.id;
    }
    return base;
  });

  // Understand tab
  const [projectName, setProjectName] = useState(searchParams.get('name') || '');
  const [requirement, setRequirement] = useState('');
  const [domain, setDomain] = useState(searchParams.get('template') || 'general');
  const [uploadFilename, setUploadFilename] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [repoUrl, setRepoUrl] = useState('');
  const [repoToken, setRepoToken] = useState('');

  // Design tab — color slot
  const [activeColorSlot, setActiveColorSlot] = useState('primary');
  const colorSlots = ['primary', 'secondary', 'background', 'surface'];

  // Launch
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState('');
  const [runId, setRunId] = useState(urlRunId || null);

  const fileInputRef = useRef(null);

  // If URL has run ID, go to Output tab
  useEffect(() => {
    if (urlRunId) { setRunId(urlRunId); setActiveTab(4); }
  }, [urlRunId]);

  const updateSpec = (section, key, value) => {
    setSpec(prev => ({ ...prev, [section]: { ...prev[section], [key]: value } }));
  };

  const updateDesign = (key, value) => updateSpec('design', key, value);

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError('');
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

  const handleLaunch = async () => {
    if (!requirement.trim()) { setLaunchError('Project requirement is required.'); return; }
    setLaunching(true);
    setLaunchError('');
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

      const payload = {
        raw_input: requirement.trim(),
        project_name: projectName.trim() || undefined,
        domain,
        client_id: (projectName.trim() || 'project').toLowerCase().replace(/\s+/g, '-'),
        designer_spec: designerSpec,
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

  // ── Tab renderers ──────────────────────────────────────────────────────────
  const renderUnderstand = () => (
    <div className="space-y-6">
      <div>
        <label className="block text-sm font-semibold text-bright mb-1.5">Project Name</label>
        <input
          className="w-full bg-surface border border-border text-bright rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-accent transition-colors"
          placeholder="My Awesome App"
          value={projectName}
          onChange={e => setProjectName(e.target.value)}
        />
      </div>

      <div>
        <label className="block text-sm font-semibold text-bright mb-1.5">
          Project Requirement <span className="text-red-400">*</span>
        </label>
        <textarea
          className="w-full bg-surface border border-border text-bright rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-accent transition-colors resize-none"
          rows={8}
          placeholder="Describe what you want to build in as much detail as possible. Include user stories, key features, integrations, and any constraints..."
          value={requirement}
          onChange={e => setRequirement(e.target.value)}
        />
        <p className="text-xs text-muted mt-1">{requirement.length} characters</p>
      </div>

      <div>
        <label className="block text-sm font-semibold text-bright mb-1.5">Upload Spec Document</label>
        <div
          onClick={() => fileInputRef.current?.click()}
          className="border-2 border-dashed border-border hover:border-accent/50 rounded-lg p-6 text-center cursor-pointer transition-colors"
        >
          <input ref={fileInputRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden" onChange={handleFileUpload} />
          {uploading ? (
            <div className="flex items-center justify-center gap-2 text-muted">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="text-sm">Extracting text…</span>
            </div>
          ) : uploadFilename ? (
            <div className="flex items-center justify-center gap-2 text-emerald-400">
              <Check className="w-4 h-4" />
              <span className="text-sm font-semibold">{uploadFilename}</span>
            </div>
          ) : (
            <div>
              <Upload className="w-6 h-6 text-muted mx-auto mb-2" />
              <p className="text-sm text-muted">Click to upload PDF, DOCX, or TXT</p>
            </div>
          )}
        </div>
        {uploadError && <p className="text-xs text-red-400 mt-1">{uploadError}</p>}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-semibold text-bright mb-1.5">GitHub / GitLab URL</label>
          <div className="flex gap-2">
            <Link className="w-4 h-4 text-muted mt-3 shrink-0" />
            <input
              className="flex-1 bg-surface border border-border text-bright rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-accent transition-colors"
              placeholder="https://github.com/org/repo"
              value={repoUrl}
              onChange={e => setRepoUrl(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label className="block text-sm font-semibold text-bright mb-1.5">Access Token (optional)</label>
          <input
            className="w-full bg-surface border border-border text-bright rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-accent transition-colors font-mono"
            placeholder="ghp_..."
            type="password"
            value={repoToken}
            onChange={e => setRepoToken(e.target.value)}
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-semibold text-bright mb-2">Domain</label>
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
          {DOMAINS.map(d => (
            <button
              key={d.id}
              type="button"
              onClick={() => setDomain(d.id)}
              className={`flex flex-col items-center gap-1 p-3 rounded-xl border text-xs font-semibold transition-all ${
                domain === d.id ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-accent/40 hover:text-bright'
              }`}
            >
              <span className="text-lg">{d.icon}</span>
              <span className="leading-tight text-center">{d.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  const renderTechStack = () => (
    <div className="space-y-8">
      <StackSection
        title="Frontend"
        values={spec.frontend}
        onChange={(k, v) => updateSpec('frontend', k, v)}
        fields={[
          { key: 'framework', label: 'Framework', options: STACK.frontend.framework },
          { key: 'styling', label: 'Styling', options: STACK.frontend.styling },
          { key: 'state_management', label: 'State Management', options: STACK.frontend.state_management },
          { key: 'form_library', label: 'Form Library', options: STACK.frontend.form_library },
          { key: 'data_fetching', label: 'Data Fetching', options: STACK.frontend.data_fetching },
        ]}
      />
      <div className="h-px bg-border" />
      <StackSection
        title="Backend"
        values={spec.backend}
        onChange={(k, v) => updateSpec('backend', k, v)}
        fields={[
          { key: 'framework', label: 'Framework', options: STACK.backend.framework },
          { key: 'database', label: 'Database', options: STACK.backend.database },
          { key: 'orm', label: 'ORM', options: STACK.backend.orm },
          { key: 'auth', label: 'Auth Strategy', options: STACK.backend.auth },
          { key: 'api_style', label: 'API Style', options: STACK.backend.api_style },
        ]}
      />
      <div className="h-px bg-border" />
      <StackSection
        title="Infrastructure"
        values={spec.infra}
        onChange={(k, v) => updateSpec('infra', k, v)}
        fields={[
          { key: 'deployment', label: 'Deployment Target', options: STACK.infra.deployment },
          { key: 'cache', label: 'Cache', options: STACK.infra.cache },
          { key: 'queue', label: 'Queue', options: STACK.infra.queue },
          { key: 'file_storage', label: 'File Storage', options: STACK.infra.file_storage },
          { key: 'email', label: 'Email', options: STACK.infra.email },
        ]}
      />
      <div className="h-px bg-border" />
      <div>
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest mb-3">Features</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {[
            { key: 'multi_tenancy', label: 'Multi-tenancy', type: 'toggle' },
            { key: 'audit_log', label: 'Audit Log', type: 'toggle' },
            { key: 'rate_limiting', label: 'Rate Limiting', type: 'toggle' },
            { key: 'webhooks_out', label: 'Webhooks Out', type: 'toggle' },
            { key: 'internationalization', label: 'Internationalization', type: 'toggle' },
          ].map(f => (
            <div key={f.key}>
              <label className="block text-xs text-muted mb-1">{f.label}</label>
              <button
                type="button"
                onClick={() => updateSpec('features', f.key, !spec.features[f.key])}
                className={`w-full px-3 py-2 rounded-lg text-sm font-semibold border transition-all ${
                  spec.features[f.key] ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-border/80'
                }`}
              >
                {spec.features[f.key] ? 'Yes' : 'No'}
              </button>
            </div>
          ))}
          <div>
            <label className="block text-xs text-muted mb-1">Real-time</label>
            <SearchableSelect
              value={spec.features.realtime}
              options={['WebSocket','SSE','None']}
              onChange={v => updateSpec('features', 'realtime', v)}
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Payments</label>
            <SearchableSelect
              value={spec.features.payments}
              options={['Stripe','Razorpay','Paddle','None']}
              onChange={v => updateSpec('features', 'payments', v)}
            />
          </div>
        </div>
      </div>
    </div>
  );

  const renderDesign = () => (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Panel 1 — Color */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Colors</h3>
        {/* Color slot tabs */}
        <div className="flex gap-1">
          {colorSlots.map(slot => (
            <button
              key={slot}
              type="button"
              onClick={() => setActiveColorSlot(slot)}
              className={`flex-1 py-1.5 text-xs font-semibold rounded capitalize transition-all ${
                activeColorSlot === slot ? 'bg-accent text-white' : 'bg-surface border border-border text-muted hover:text-bright'
              }`}
            >
              {slot}
            </button>
          ))}
        </div>
        <HslPicker
          hex={spec.design[activeColorSlot]}
          onChange={v => updateDesign(activeColorSlot, v)}
        />
        {/* Color preview row */}
        <div className="flex gap-2 mt-2">
          {colorSlots.map(slot => (
            <div key={slot} className="flex-1 flex flex-col items-center gap-1">
              <div
                onClick={() => setActiveColorSlot(slot)}
                className={`w-full h-8 rounded-lg cursor-pointer border-2 transition-all ${activeColorSlot === slot ? 'border-white' : 'border-transparent'}`}
                style={{ background: spec.design[slot] }}
              />
              <span className="text-[9px] text-muted capitalize">{slot}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Panel 2 — Typography */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Typography</h3>
        <div>
          <label className="block text-xs text-muted mb-1.5">Font Pairing</label>
          {FONT_PAIRS.map(fp => (
            <button
              key={fp.label}
              type="button"
              onClick={() => updateDesign('font_pairing', fp.label)}
              className={`w-full flex items-center justify-between px-3 py-2.5 mb-1.5 rounded-lg border text-sm transition-all ${
                spec.design.font_pairing === fp.label ? 'border-accent bg-accent/10 text-accent' : 'border-border text-bright hover:border-accent/40'
              }`}
            >
              <span className="text-xs">{fp.label}</span>
              {spec.design.font_pairing === fp.label && <Check className="w-3.5 h-3.5" />}
            </button>
          ))}
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Font Size Scale</label>
          <div className="grid grid-cols-3 gap-1.5">
            {['Compact','Normal','Comfortable'].map(s => (
              <button
                key={s}
                type="button"
                onClick={() => updateDesign('font_scale', s)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${
                  spec.design.font_scale === s ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Border Radius</label>
          <div className="grid grid-cols-2 gap-1.5">
            {['Sharp (0px)','Subtle (4px)','Rounded (8px)','Pill (16px)'].map(r => (
              <button
                key={r}
                type="button"
                onClick={() => updateDesign('border_radius', r)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${
                  spec.design.border_radius === r ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Panel 3 — Layout */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Layout</h3>
        <div className="space-y-2">
          {LAYOUTS.map(lay => (
            <button
              key={lay.id}
              type="button"
              onClick={() => updateDesign('layout', lay.id)}
              className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all ${
                spec.design.layout === lay.id ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/40'
              }`}
            >
              <div className="w-16 h-10 shrink-0 rounded overflow-hidden border border-border/50">
                {lay.svg}
              </div>
              <span className={`text-xs font-semibold ${spec.design.layout === lay.id ? 'text-accent' : 'text-bright'}`}>
                {lay.label}
              </span>
              {spec.design.layout === lay.id && <Check className="w-4 h-4 text-accent ml-auto" />}
            </button>
          ))}
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Component Density</label>
          <div className="grid grid-cols-3 gap-1.5">
            {['Compact','Normal','Spacious'].map(d => (
              <button
                key={d}
                type="button"
                onClick={() => updateDesign('density', d)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${
                  spec.design.density === d ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'
                }`}
              >
                {d}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1.5">Card Style</label>
          <div className="grid grid-cols-2 gap-1.5">
            {['Flat','Subtle Shadow','Elevated','Glass'].map(cs => (
              <button
                key={cs}
                type="button"
                onClick={() => updateDesign('card_style', cs)}
                className={`py-2 text-xs font-semibold rounded-lg border transition-all ${
                  spec.design.card_style === cs ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'
                }`}
              >
                {cs}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  const renderPreview = () => {
    const cx = complexity;
    return (
      <div className="space-y-6">
        <div className="bg-surface border border-border rounded-2xl p-6 space-y-6">
          {/* Header */}
          <div className="flex items-start justify-between">
            <div>
              <h3 className="text-xl font-bold text-bright">{projectName || 'Untitled Project'}</h3>
              <p className="text-sm text-muted mt-0.5">{DOMAINS.find(d => d.id === domain)?.label || 'General'}</p>
            </div>
            <div className="flex gap-2">
              {colorSlots.map(slot => (
                <div key={slot} className="w-5 h-5 rounded-full border border-white/10" style={{ background: spec.design[slot] }} title={slot} />
              ))}
            </div>
          </div>

          {requirement && (
            <div className="p-4 bg-panel rounded-xl border border-border">
              <p className="text-xs text-muted font-bold uppercase tracking-widest mb-2">Requirement</p>
              <p className="text-sm text-bright leading-relaxed line-clamp-4">{requirement}</p>
            </div>
          )}

          {/* Stack summary */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {[
              { label: 'Frontend', value: spec.frontend.framework },
              { label: 'Styling', value: spec.frontend.styling },
              { label: 'State', value: spec.frontend.state_management },
              { label: 'Backend', value: spec.backend.framework },
              { label: 'Database', value: spec.backend.database },
              { label: 'ORM', value: spec.backend.orm },
              { label: 'Auth', value: spec.backend.auth },
              { label: 'API', value: spec.backend.api_style },
              { label: 'Deploy', value: spec.infra.deployment },
              { label: 'Cache', value: spec.infra.cache },
              { label: 'Queue', value: spec.infra.queue },
              { label: 'Email', value: spec.infra.email },
            ].map(({ label, value }) => (
              <div key={label}>
                <p className="text-[10px] font-bold text-muted uppercase tracking-widest">{label}</p>
                <p className="text-sm text-bright mt-0.5 truncate">{value}</p>
              </div>
            ))}
          </div>

          {/* Features */}
          <div>
            <p className="text-[10px] font-bold text-muted uppercase tracking-widest mb-2">Features</p>
            <div className="flex flex-wrap gap-2">
              {spec.features.multi_tenancy && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Multi-tenant</span>}
              {spec.features.audit_log && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Audit Log</span>}
              {spec.features.rate_limiting && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Rate Limiting</span>}
              {spec.features.webhooks_out && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Webhooks</span>}
              {spec.features.internationalization && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">i18n</span>}
              {spec.features.realtime !== 'None' && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Realtime ({spec.features.realtime})</span>}
              {spec.features.payments !== 'None' && <span className="px-2 py-0.5 bg-accent/10 border border-accent/20 text-accent rounded-full text-xs">Payments ({spec.features.payments})</span>}
            </div>
          </div>

          {/* Design tokens */}
          <div>
            <p className="text-[10px] font-bold text-muted uppercase tracking-widest mb-2">Design</p>
            <div className="flex flex-wrap gap-4 text-sm">
              <span className="text-muted">Font: <span className="text-bright">{spec.design.font_pairing}</span></span>
              <span className="text-muted">Radius: <span className="text-bright">{spec.design.border_radius}</span></span>
              <span className="text-muted">Layout: <span className="text-bright">{LAYOUTS.find(l => l.id === spec.design.layout)?.label}</span></span>
              <span className="text-muted">Density: <span className="text-bright">{spec.design.density}</span></span>
            </div>
          </div>
        </div>

        {/* Complexity indicator */}
        <div className="flex items-center gap-4 p-4 bg-surface border border-border rounded-xl">
          <div>
            <p className="text-xs text-muted font-bold uppercase tracking-widest">Estimated Complexity</p>
            <p className={`text-2xl font-bold mt-0.5 ${cx.color}`}>{cx.label}</p>
          </div>
          <div className="flex gap-1.5 ml-4">
            {[1,2,3,4].map(n => (
              <div
                key={n}
                className={`h-8 w-5 rounded transition-colors ${n <= cx.bar ? cx.color.replace('text-','bg-') : 'bg-border'}`}
              />
            ))}
          </div>
        </div>

        {/* Errors */}
        {launchError && (
          <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
            <X className="w-4 h-4 text-red-400 shrink-0" />
            <p className="text-sm text-red-400">{launchError}</p>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => {
              const blob = new Blob([JSON.stringify({ projectName, requirement, domain, ...spec }, null, 2)], { type: 'application/json' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a'); a.href = url; a.download = `${projectName || 'spec'}.json`; a.click();
              URL.revokeObjectURL(url);
            }}
            className="px-5 py-2.5 border border-border text-muted hover:text-bright hover:border-accent/50 text-sm font-semibold rounded-xl transition-colors"
          >
            Save Spec
          </button>
          <button
            type="button"
            onClick={handleLaunch}
            disabled={launching || !requirement.trim()}
            className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-bold rounded-xl transition-colors"
          >
            {launching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
            {launching ? 'Launching…' : 'Launch Build'}
          </button>
        </div>
      </div>
    );
  };

  const renderOutput = () => (
    <div>
      {runId ? (
        <RunOutput runId={runId} />
      ) : (
        <div className="py-20 text-center">
          <Wand2 className="w-12 h-12 text-muted/30 mx-auto mb-4" />
          <p className="text-muted text-sm">No build launched yet.</p>
          <p className="text-muted/60 text-xs mt-1">Complete the spec and click Launch Build on the Preview tab.</p>
          <button
            onClick={() => setActiveTab(3)}
            className="mt-4 px-5 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-semibold rounded-xl transition-colors"
          >
            Go to Preview
          </button>
        </div>
      )}
    </div>
  );

  const tabContent = [renderUnderstand, renderTechStack, renderDesign, renderPreview, renderOutput];

  return (
    <div className="max-w-5xl mx-auto py-6 px-4">
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <Wand2 className="w-6 h-6 text-accent" />
          <h1 className="text-2xl font-bold text-bright">Project Designer</h1>
        </div>
        <p className="text-sm text-muted">Design your full-stack app and launch the build pipeline.</p>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-border mb-6 overflow-x-auto">
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i)}
            className={`px-5 py-3 text-sm font-semibold whitespace-nowrap border-b-2 transition-colors ${
              activeTab === i
                ? 'border-accent text-accent'
                : 'border-transparent text-muted hover:text-bright'
            } ${i === 4 && !runId ? 'opacity-40 cursor-not-allowed' : ''}`}
            disabled={i === 4 && !runId}
          >
            {tab}
            {i === 4 && runId && (
              <span className="ml-1.5 w-2 h-2 rounded-full bg-emerald-400 inline-block align-middle" />
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="min-h-[400px]">
        {tabContent[activeTab]()}
      </div>

      {/* Bottom nav */}
      {activeTab < 4 && (
        <div className="flex justify-between mt-8 pt-4 border-t border-border">
          <button
            onClick={() => setActiveTab(p => Math.max(0, p - 1))}
            disabled={activeTab === 0}
            className="px-5 py-2.5 border border-border text-muted hover:text-bright disabled:opacity-30 text-sm font-semibold rounded-xl transition-colors"
          >
            ← Back
          </button>
          {activeTab < 3 ? (
            <button
              onClick={() => setActiveTab(p => Math.min(3, p + 1))}
              className="px-5 py-2.5 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-xl transition-colors"
            >
              Next →
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
};

export default ProjectDesigner;
