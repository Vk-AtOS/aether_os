// Static data and helpers extracted from ProjectDesigner.jsx (600-line limit)

// ── Static data ────────────────────────────────────────────────────────────────
export const TEMPLATES = [
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

export const DOMAINS = TEMPLATES.map(t => ({ id: t.domain, label: t.label, icon: t.icon }));

export const DEFAULT_MODELS = [
  { value: 'claude-sonnet-4-6',  label: 'Claude Sonnet 4.6 (Anthropic)' },
  { value: 'gemini-2.0-flash',   label: 'Gemini 2.0 Flash (Google)' },
  { value: 'qwen2.5-coder:7b',   label: 'Qwen 2.5 Coder 7B (Ollama)' },
];

export const PRIORITIES = ['High', 'Normal', 'Low'];

export const STACK = {
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

export const FONT_PAIRS = [
  'Inter + Inter (system)',
  'Geist + Geist Mono',
  'Plus Jakarta Sans + Fira Code',
  'DM Sans + JetBrains Mono',
  'Satoshi + IBM Plex Mono',
];

export const LAYOUTS = [
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
export function hslToHex(h, s, l) {
  s /= 100; l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = n => Math.round(255 * (l - a * Math.max(-1, Math.min(((n + h / 30) % 12) - 3, Math.min(9 - ((n + h / 30) % 12), 1)))));
  return '#' + [f(0), f(8), f(4)].map(v => v.toString(16).padStart(2, '0')).join('');
}
export function hexToHsl(hex) {
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
export const isValidHex = h => /^#[0-9a-fA-F]{6}$/.test(h);

// ── Complexity calculator ──────────────────────────────────────────────────────
export function calcComplexity(spec) {
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

// ── UI/UX Design Themes ────────────────────────────────────────────────────────
export const UI_THEMES = [
  {
    id: 'default',
    label: 'Default Dark',
    description: 'Clean dark UI with subtle surfaces and indigo accents',
    preview: (
      <svg viewBox="0 0 120 80" className="w-full h-full">
        <rect width="120" height="80" fill="#0f172a"/>
        <rect x="0" y="0" width="24" height="80" fill="#1e293b"/>
        <rect x="28" y="8" width="50" height="6" rx="2" fill="#6366f1"/>
        <rect x="28" y="20" width="84" height="4" rx="1" fill="#334155"/>
        <rect x="28" y="28" width="70" height="4" rx="1" fill="#334155"/>
        <rect x="28" y="38" width="36" height="16" rx="3" fill="#1e293b" stroke="#334155" strokeWidth="0.5"/>
        <rect x="70" y="38" width="42" height="16" rx="3" fill="#1e293b" stroke="#334155" strokeWidth="0.5"/>
        <rect x="4" y="10" width="16" height="3" rx="1" fill="#475569"/>
        <rect x="4" y="18" width="14" height="3" rx="1" fill="#475569"/>
        <rect x="4" y="26" width="16" height="3" rx="1" fill="#475569"/>
      </svg>
    ),
  },
  {
    id: 'glassmorphism',
    label: 'Glassmorphism',
    description: 'Frosted glass cards, translucent surfaces, vibrant gradient backgrounds',
    preview: (
      <svg viewBox="0 0 120 80" className="w-full h-full">
        <defs>
          <linearGradient id="glBg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#4f46e5"/>
            <stop offset="50%" stopColor="#7c3aed"/>
            <stop offset="100%" stopColor="#db2777"/>
          </linearGradient>
        </defs>
        <rect width="120" height="80" fill="url(#glBg)"/>
        <circle cx="20" cy="20" r="30" fill="#818cf8" opacity="0.3"/>
        <circle cx="100" cy="60" r="25" fill="#f472b6" opacity="0.25"/>
        <rect x="10" y="20" width="45" height="40" rx="8" fill="white" fillOpacity="0.15" stroke="white" strokeOpacity="0.3" strokeWidth="0.5"/>
        <rect x="65" y="25" width="45" height="35" rx="8" fill="white" fillOpacity="0.12" stroke="white" strokeOpacity="0.25" strokeWidth="0.5"/>
        <rect x="16" y="28" width="30" height="3" rx="1" fill="white" fillOpacity="0.8"/>
        <rect x="16" y="35" width="22" height="2" rx="1" fill="white" fillOpacity="0.5"/>
        <rect x="16" y="42" width="26" height="2" rx="1" fill="white" fillOpacity="0.5"/>
        <rect x="71" y="33" width="28" height="3" rx="1" fill="white" fillOpacity="0.8"/>
        <rect x="71" y="40" width="20" height="2" rx="1" fill="white" fillOpacity="0.5"/>
      </svg>
    ),
  },
  {
    id: 'neomorphism',
    label: 'Neomorphism',
    description: 'Soft extruded surfaces with dual-shadow depth on a monochromatic base',
    preview: (
      <svg viewBox="0 0 120 80" className="w-full h-full">
        <rect width="120" height="80" fill="#e0e5ec"/>
        <rect x="10" y="12" width="45" height="56" rx="12" fill="#e0e5ec" filter="url(#neo-shadow)"/>
        <rect x="65" y="18" width="45" height="44" rx="10" fill="#e0e5ec" filter="url(#neo-shadow)"/>
        <defs>
          <filter id="neo-shadow">
            <feDropShadow dx="-3" dy="-3" stdDeviation="3" floodColor="#ffffff" floodOpacity="0.9"/>
            <feDropShadow dx="3" dy="3" stdDeviation="3" floodColor="#a3b1c6" floodOpacity="0.5"/>
          </filter>
        </defs>
        <rect x="20" y="24" width="25" height="3" rx="1.5" fill="#6b7280"/>
        <rect x="20" y="32" width="18" height="2" rx="1" fill="#9ca3af"/>
        <rect x="20" y="40" width="22" height="2" rx="1" fill="#9ca3af"/>
        <rect x="20" y="52" width="28" height="8" rx="4" fill="#e0e5ec" filter="url(#neo-shadow)"/>
        <rect x="72" y="28" width="28" height="3" rx="1.5" fill="#6b7280"/>
        <rect x="72" y="36" width="22" height="2" rx="1" fill="#9ca3af"/>
        <rect x="72" y="44" width="26" height="2" rx="1" fill="#9ca3af"/>
      </svg>
    ),
  },
  {
    id: 'material',
    label: 'Material Design 3',
    description: 'Google Material You — dynamic color, elevation shadows, filled/tonal buttons',
    preview: (
      <svg viewBox="0 0 120 80" className="w-full h-full">
        <rect width="120" height="80" fill="#fffbfe"/>
        <rect x="0" y="0" width="120" height="14" fill="#6750a4"/>
        <rect x="6" y="4" width="30" height="6" rx="1" fill="white" fillOpacity="0.9"/>
        <rect x="90" y="4" width="6" height="6" rx="3" fill="white" fillOpacity="0.7"/>
        <rect x="100" y="4" width="6" height="6" rx="3" fill="white" fillOpacity="0.7"/>
        <rect x="110" y="4" width="6" height="6" rx="3" fill="white" fillOpacity="0.7"/>
        <rect x="8" y="20" width="48" height="28" rx="4" fill="#f3edf7" stroke="#e8def8" strokeWidth="0.5"/>
        <rect x="64" y="20" width="48" height="28" rx="4" fill="#f3edf7" stroke="#e8def8" strokeWidth="0.5"/>
        <rect x="14" y="26" width="30" height="3" rx="1" fill="#21005d"/>
        <rect x="14" y="33" width="22" height="2" rx="1" fill="#49454f"/>
        <rect x="14" y="39" width="26" height="2" rx="1" fill="#49454f"/>
        <rect x="70" y="26" width="30" height="3" rx="1" fill="#21005d"/>
        <rect x="70" y="33" width="22" height="2" rx="1" fill="#49454f"/>
        <rect x="8" y="55" width="40" height="10" rx="5" fill="#6750a4"/>
        <rect x="52" y="55" width="40" height="10" rx="5" fill="#e8def8"/>
        <rect x="16" y="58" width="24" height="4" rx="1" fill="white"/>
        <rect x="60" y="58" width="24" height="4" rx="1" fill="#6750a4"/>
      </svg>
    ),
  },
  {
    id: 'flat',
    label: 'Flat / Minimal',
    description: 'Zero shadows, crisp lines, high contrast, whitespace-driven hierarchy',
    preview: (
      <svg viewBox="0 0 120 80" className="w-full h-full">
        <rect width="120" height="80" fill="#ffffff"/>
        <rect x="0" y="0" width="120" height="1" fill="#e5e7eb"/>
        <rect x="8" y="8" width="60" height="5" rx="0" fill="#111827"/>
        <rect x="8" y="18" width="104" height="1" fill="#e5e7eb"/>
        <rect x="8" y="24" width="50" height="3" rx="0" fill="#374151"/>
        <rect x="8" y="32" width="44" height="3" rx="0" fill="#6b7280"/>
        <rect x="8" y="40" width="48" height="3" rx="0" fill="#6b7280"/>
        <rect x="8" y="52" width="28" height="8" rx="0" fill="#111827"/>
        <rect x="42" y="52" width="28" height="8" rx="0" fill="white" stroke="#111827" strokeWidth="1"/>
        <rect x="72" y="24" width="40" height="28" rx="0" fill="#f9fafb" stroke="#e5e7eb" strokeWidth="1"/>
        <rect x="76" y="30" width="26" height="3" rx="0" fill="#374151"/>
        <rect x="76" y="38" width="18" height="2" rx="0" fill="#9ca3af"/>
        <rect x="76" y="44" width="22" height="2" rx="0" fill="#9ca3af"/>
      </svg>
    ),
  },
  {
    id: 'brutalist',
    label: 'Brutalist',
    description: 'Raw bold borders, stark contrast, offset shadows, unapologetically visible structure',
    preview: (
      <svg viewBox="0 0 120 80" className="w-full h-full">
        <rect width="120" height="80" fill="#ffffff"/>
        <rect x="8" y="8" width="60" height="8" rx="0" fill="#000000"/>
        <rect x="8" y="22" width="48" height="26" rx="0" fill="#ffffff" stroke="#000000" strokeWidth="2"/>
        <rect x="11" y="24" width="48" height="26" rx="0" fill="#000000" opacity="0.15"/>
        <rect x="64" y="22" width="48" height="26" rx="0" fill="#facc15" stroke="#000000" strokeWidth="2"/>
        <rect x="67" y="24" width="48" height="26" rx="0" fill="#000000" opacity="0.1"/>
        <rect x="12" y="28" width="30" height="4" rx="0" fill="#000000"/>
        <rect x="12" y="36" width="22" height="3" rx="0" fill="#374151"/>
        <rect x="68" y="28" width="30" height="4" rx="0" fill="#000000"/>
        <rect x="68" y="36" width="22" height="3" rx="0" fill="#374151"/>
        <rect x="8" y="56" width="36" height="12" rx="0" fill="#000000" stroke="#000000" strokeWidth="2"/>
        <rect x="10" y="58" width="36" height="12" rx="0" fill="#f97316"/>
        <rect x="16" y="61" width="22" height="4" rx="0" fill="#000000"/>
      </svg>
    ),
  },
  {
    id: 'neon_cyberpunk',
    label: 'Neon / Cyberpunk',
    description: 'Near-black background, electric neon glow accents, grid lines, futuristic feel',
    preview: (
      <svg viewBox="0 0 120 80" className="w-full h-full">
        <defs>
          <filter id="neon-glow">
            <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
            <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>
        <rect width="120" height="80" fill="#050810"/>
        {[0,10,20,30,40,50,60,70,80].map(y => <line key={y} x1="0" y1={y} x2="120" y2={y} stroke="#0ff" strokeOpacity="0.05" strokeWidth="0.5"/>)}
        {[0,15,30,45,60,75,90,105,120].map(x => <line key={x} x1={x} y1="0" x2={x} y2="80" stroke="#0ff" strokeOpacity="0.05" strokeWidth="0.5"/>)}
        <rect x="8" y="10" width="48" height="30" rx="2" fill="#050810" stroke="#00ffff" strokeWidth="1" filter="url(#neon-glow)"/>
        <rect x="64" y="10" width="48" height="30" rx="2" fill="#050810" stroke="#ff00ff" strokeWidth="1" filter="url(#neon-glow)"/>
        <rect x="12" y="16" width="28" height="3" rx="0" fill="#00ffff" opacity="0.9" filter="url(#neon-glow)"/>
        <rect x="12" y="24" width="20" height="2" rx="0" fill="#00ffff" opacity="0.4"/>
        <rect x="12" y="30" width="24" height="2" rx="0" fill="#00ffff" opacity="0.4"/>
        <rect x="68" y="16" width="28" height="3" rx="0" fill="#ff00ff" opacity="0.9" filter="url(#neon-glow)"/>
        <rect x="68" y="24" width="20" height="2" rx="0" fill="#ff00ff" opacity="0.4"/>
        <rect x="8" y="52" width="36" height="12" rx="2" fill="#050810" stroke="#00ffff" strokeWidth="1" filter="url(#neon-glow)"/>
        <rect x="14" y="56" width="24" height="4" rx="0" fill="#00ffff" opacity="0.8"/>
      </svg>
    ),
  },
  {
    id: 'soft_pastel',
    label: 'Soft Pastel',
    description: 'Light airy backgrounds, pastel color palette, rounded corners, gentle shadows',
    preview: (
      <svg viewBox="0 0 120 80" className="w-full h-full">
        <rect width="120" height="80" fill="#fdf4ff"/>
        <rect x="0" y="0" width="120" height="14" fill="#f0abfc" opacity="0.4"/>
        <rect x="6" y="4" width="30" height="6" rx="3" fill="#a855f7" opacity="0.7"/>
        <rect x="8" y="20" width="48" height="30" rx="10" fill="#fce7f3" stroke="#fbcfe8" strokeWidth="0.5"/>
        <rect x="64" y="20" width="48" height="30" rx="10" fill="#e0f2fe" stroke="#bae6fd" strokeWidth="0.5"/>
        <rect x="14" y="27" width="28" height="3" rx="1.5" fill="#a855f7" opacity="0.7"/>
        <rect x="14" y="34" width="22" height="2" rx="1" fill="#c084fc" opacity="0.6"/>
        <rect x="14" y="40" width="26" height="2" rx="1" fill="#c084fc" opacity="0.6"/>
        <rect x="70" y="27" width="28" height="3" rx="1.5" fill="#0ea5e9" opacity="0.7"/>
        <rect x="70" y="34" width="22" height="2" rx="1" fill="#38bdf8" opacity="0.6"/>
        <rect x="8" y="58" width="36" height="10" rx="5" fill="#a855f7" opacity="0.7"/>
        <rect x="50" y="58" width="36" height="10" rx="5" fill="#fce7f3" stroke="#f9a8d4" strokeWidth="0.5"/>
        <rect x="14" y="61" width="24" height="4" rx="2" fill="white" opacity="0.8"/>
        <rect x="56" y="61" width="24" height="4" rx="2" fill="#a855f7" opacity="0.6"/>
      </svg>
    ),
  },
];

// ── Country / compliance data ──────────────────────────────────────────────────
export const COUNTRIES = [
  // EU/EEA — GDPR triggers
  { code:'AT', label:'Austria',        region:'EU',    flag:'🇦🇹' },
  { code:'BE', label:'Belgium',        region:'EU',    flag:'🇧🇪' },
  { code:'CZ', label:'Czechia',        region:'EU',    flag:'🇨🇿' },
  { code:'DE', label:'Germany',        region:'EU',    flag:'🇩🇪' },
  { code:'DK', label:'Denmark',        region:'EU',    flag:'🇩🇰' },
  { code:'ES', label:'Spain',          region:'EU',    flag:'🇪🇸' },
  { code:'FI', label:'Finland',        region:'EU',    flag:'🇫🇮' },
  { code:'FR', label:'France',         region:'EU',    flag:'🇫🇷' },
  { code:'GR', label:'Greece',         region:'EU',    flag:'🇬🇷' },
  { code:'HR', label:'Croatia',        region:'EU',    flag:'🇭🇷' },
  { code:'HU', label:'Hungary',        region:'EU',    flag:'🇭🇺' },
  { code:'IE', label:'Ireland',        region:'EU',    flag:'🇮🇪' },
  { code:'IT', label:'Italy',          region:'EU',    flag:'🇮🇹' },
  { code:'NL', label:'Netherlands',    region:'EU',    flag:'🇳🇱' },
  { code:'PL', label:'Poland',         region:'EU',    flag:'🇵🇱' },
  { code:'PT', label:'Portugal',       region:'EU',    flag:'🇵🇹' },
  { code:'RO', label:'Romania',        region:'EU',    flag:'🇷🇴' },
  { code:'SE', label:'Sweden',         region:'EU',    flag:'🇸🇪' },
  { code:'SK', label:'Slovakia',       region:'EU',    flag:'🇸🇰' },
  { code:'CH', label:'Switzerland',    region:'EU',    flag:'🇨🇭' },
  { code:'NO', label:'Norway',         region:'EU',    flag:'🇳🇴' },
  { code:'GB', label:'United Kingdom', region:'UK',    flag:'🇬🇧' },
  // Americas
  { code:'US', label:'United States',  region:'US',    flag:'🇺🇸' },
  { code:'CA', label:'Canada',         region:'CANADA',flag:'🇨🇦' },
  { code:'BR', label:'Brazil',         region:'LATAM', flag:'🇧🇷' },
  { code:'MX', label:'Mexico',         region:'LATAM', flag:'🇲🇽' },
  { code:'AR', label:'Argentina',      region:'LATAM', flag:'🇦🇷' },
  { code:'CL', label:'Chile',          region:'LATAM', flag:'🇨🇱' },
  { code:'CO', label:'Colombia',       region:'LATAM', flag:'🇨🇴' },
  // APAC
  { code:'AU', label:'Australia',      region:'APAC',  flag:'🇦🇺' },
  { code:'NZ', label:'New Zealand',    region:'APAC',  flag:'🇳🇿' },
  { code:'IN', label:'India',          region:'APAC',  flag:'🇮🇳' },
  { code:'SG', label:'Singapore',      region:'APAC',  flag:'🇸🇬' },
  { code:'JP', label:'Japan',          region:'APAC',  flag:'🇯🇵' },
  { code:'KR', label:'South Korea',    region:'APAC',  flag:'🇰🇷' },
  { code:'TH', label:'Thailand',       region:'APAC',  flag:'🇹🇭' },
  { code:'PH', label:'Philippines',    region:'APAC',  flag:'🇵🇭' },
  { code:'ID', label:'Indonesia',      region:'APAC',  flag:'🇮🇩' },
  { code:'MY', label:'Malaysia',       region:'APAC',  flag:'🇲🇾' },
  { code:'VN', label:'Vietnam',        region:'APAC',  flag:'🇻🇳' },
  { code:'HK', label:'Hong Kong',      region:'APAC',  flag:'🇭🇰' },
  { code:'TW', label:'Taiwan',         region:'APAC',  flag:'🇹🇼' },
  // MENA
  { code:'AE', label:'UAE',            region:'MENA',  flag:'🇦🇪' },
  { code:'SA', label:'Saudi Arabia',   region:'MENA',  flag:'🇸🇦' },
  { code:'IL', label:'Israel',         region:'MENA',  flag:'🇮🇱' },
  { code:'EG', label:'Egypt',          region:'MENA',  flag:'🇪🇬' },
  { code:'NG', label:'Nigeria',        region:'AFRICA',flag:'🇳🇬' },
  { code:'ZA', label:'South Africa',   region:'AFRICA',flag:'🇿🇦' },
  // China (special — PIPL)
  { code:'CN', label:'China',          region:'CHINA', flag:'🇨🇳' },
  // Embargoed jurisdictions: selectable so the "pipeline will be blocked" warning can show (the server refuses them)
  { code:'CU', label:'Cuba',           region:'global', flag:'🇨🇺' },
  { code:'IR', label:'Iran',           region:'global', flag:'🇮🇷' },
  { code:'KP', label:'North Korea',    region:'global', flag:'🇰🇵' },
  { code:'RU', label:'Russia',         region:'global', flag:'🇷🇺' },
  { code:'SY', label:'Syria',          region:'global', flag:'🇸🇾' },
];

export const REGION_COMPLIANCE = {
  EU:     ['GDPR','Data Residency Rules','AI Act (high-risk use cases)'],
  UK:     ['UK GDPR','ICO Requirements'],
  US:     ['State Privacy Laws (CCPA/CPRA)','HIPAA (if healthcare)','PCI-DSS (if payments)','SOC 2 (recommended)'],
  CANADA: ['PIPEDA / Québec Law 25','CASL'],
  LATAM:  ['LGPD (Brazil)','Local data localisation laws'],
  APAC:   ['Country-specific data protection act','Data localisation requirements'],
  MENA:   ['Local data protection regulations','Data residency requirements'],
  AFRICA: ['POPIA (South Africa)','NDPR (Nigeria)','Local regulations'],
  CHINA:  ['PIPL','Cybersecurity Law','Data Localisation Mandate','MLPS Certification'],
  global: ['General best practices apply'],
};

// Must equal ComplianceEngine.EMBARGOED_COUNTRIES (core/policy/compliance.py); tests/test_dashboard_embargo_list.py checks it.
export const EMBARGOED = new Set(['CU','IR','KP','RU','SY']);

export const DEFAULT_SPEC = {
  frontend: { framework: 'React + Vite', styling: 'Tailwind + shadcn/ui', state_management: 'Zustand', form_library: 'React Hook Form + Zod', data_fetching: 'TanStack Query' },
  backend:  { framework: 'FastAPI', database: 'PostgreSQL', orm: 'SQLAlchemy', auth: 'JWT + refresh tokens', api_style: 'REST' },
  infra:    { deployment: 'Docker + Compose', cache: 'Redis', queue: 'None', file_storage: 'Local', email: 'Resend' },
  features: { multi_tenancy: false, audit_log: false, rate_limiting: true, webhooks_out: false, realtime: 'None', payments: 'None', internationalization: false },
  design:   { primary: '#6366f1', secondary: '#8b5cf6', background: '#0f172a', surface: '#1e293b', font_pairing: 'Inter + Inter (system)', font_scale: 'Normal', border_radius: 'Rounded (8px)', layout: 'sidebar-topbar', density: 'Normal', card_style: 'Subtle Shadow', ui_theme: 'default', page_transition: 'fade', micro_interactions: true, animation_speed: 'normal', scroll_reveal: true, loading_style: 'shimmer', hover_lift: true },
  compliance: { production_country: '', data_sensitivity: 'moderate', handles_personal_data: true, handles_biometric_data: false, handles_children_data: false, requires_data_residency: false, deployment_type: 'saas' },
};

export const TABS = ['Understand', 'Tech Stack', 'Design', 'Compliance', 'Preview', 'Output'];
export const COLOR_SLOTS = ['primary', 'secondary', 'background', 'surface'];
