import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

const DEFAULT_TEMPLATES = [
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

const PRIORITIES = ['High', 'Normal', 'Low'];
const BACKEND_OPTIONS = ['FastAPI', 'Django', 'Express', 'Flask'];
const FRONTEND_OPTIONS = ['React', 'Vue', 'Vanilla JS', 'None'];
const DB_OPTIONS = ['PostgreSQL', 'MongoDB', 'SQLite', 'MySQL'];
// Fallback models shown only when the /settings/active-provider API is unreachable.
// Values use stable aliases (no version pin) so the backend picks the latest available.
const DEFAULT_MODELS = [
  { value: 'claude-sonnet', label: 'Claude Sonnet (Anthropic)' },
  { value: 'gemini-flash', label: 'Gemini Flash (Google)' },
  { value: 'qwen-coder', label: 'Qwen Coder (Local/Ollama)' },
];

const StepIndicator = ({ step }) => {
  const steps = ['Template', 'Describe', 'Configure', 'Launch'];
  return (
    <div className="flex items-center justify-center mb-8 gap-0">
      {steps.map((label, i) => {
        const idx = i + 1;
        const active = idx === step;
        const done = idx < step;
        return (
          <React.Fragment key={idx}>
            <div className="flex flex-col items-center gap-1">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-colors ${
                done ? 'bg-emerald-500 text-white' : active ? 'bg-accent text-white' : 'bg-surface border border-border text-muted'
              }`}>
                {done ? '✓' : idx}
              </div>
              <span className={`text-[10px] uppercase tracking-wider font-semibold ${active ? 'text-accent' : 'text-muted'}`}>{label}</span>
            </div>
            {i < steps.length - 1 && <div className={`h-px w-16 mb-5 mx-1 transition-colors ${done ? 'bg-emerald-500' : 'bg-border'}`} />}
          </React.Fragment>
        );
      })}
    </div>
  );
};

const TemplateCard = ({ tpl, selected, onClick }) => (
  <button onClick={onClick} className={`p-4 rounded-xl border text-left transition-all ${
    selected ? 'border-accent bg-accent/10 shadow-lg shadow-accent/10' : 'border-border bg-surface hover:border-accent/50 hover:bg-surface/80'
  }`}>
    <div className="text-2xl mb-2">{tpl.icon}</div>
    <div className="text-sm font-semibold text-bright">{tpl.label}</div>
  </button>
);

const PillGroup = ({ options, value, onChange, multi = false }) => (
  <div className="flex gap-2 flex-wrap">
    {options.map(([val, label]) => {
      const active = multi ? value.includes(val) : value === val;
      return (
        <button key={String(val)} type="button"
          onClick={() => onChange(val)}
          className={`px-4 py-2 rounded-lg border text-sm font-medium transition-all ${
            active
              ? 'border-accent bg-accent/15 text-accent'
              : 'border-border text-muted hover:border-accent/40 hover:text-bright'
          }`}>
          {label}
        </button>
      );
    })}
  </div>
);

const NewProjectWizard = () => {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);

  const [step, setStep] = useState(1);

  const [templates, setTemplates] = useState(DEFAULT_TEMPLATES);
  const [selectedTpl, setSelectedTpl] = useState(null);

  const [projectMode, setProjectMode] = useState('new');

  // Step 2 — core fields
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [domain, setDomain] = useState('general');
  const [uploadedText, setUploadedText] = useState('');
  const [uploadFilename, setUploadFilename] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');

  // Step 2 — guided questionnaire
  const [wizardAnswers, setWizardAnswers] = useState({
    who: '', scale: '', money: null, industry: 'general', mobile: '', problem: '', features: '',
  });

  // Repo / existing codebase
  const [repoUrl, setRepoUrl] = useState('');
  const [repoType, setRepoType] = useState('github');
  const [repoToken, setRepoToken] = useState('');
  const [repoSshKey, setRepoSshKey] = useState('');
  const [gitlabUrl, setGitlabUrl] = useState('https://gitlab.com');
  const [fetchingRepo, setFetchingRepo] = useState(false);
  const [repoContext, setRepoContext] = useState('');
  const [repoFetched, setRepoFetched] = useState('');
  const githubUrl = repoUrl; const setGithubUrl = setRepoUrl;
  const githubToken = repoToken; const setGithubToken = setRepoToken;

  // Import existing schema
  const [schemaOpen, setSchemaOpen] = useState(false);
  const [schemaConnStr, setSchemaConnStr] = useState('');
  const [importingSchema, setImportingSchema] = useState(false);
  const [importedSchema, setImportedSchema] = useState(null);
  const [schemaError, setSchemaError] = useState('');

  // Step 3 — configure
  const [models, setModels] = useState(DEFAULT_MODELS);
  const [model, setModel] = useState(DEFAULT_MODELS[0].value);
  const [priority, setPriority] = useState('Normal');
  const [backendFw, setBackendFw] = useState('FastAPI');
  const [frontendFw, setFrontendFw] = useState('React');
  const [dbChoice, setDbChoice] = useState('PostgreSQL');

  // Step 4 — launch
  const [estimate, setEstimate] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getTemplates().then(res => {
      if (res.data?.templates?.length) {
        const mapped = res.data.templates.map(t => ({ ...t, label: t.name, prompt: t.description }));
        const hasCustom = mapped.some(t => t.id === 'custom');
        setTemplates(hasCustom ? mapped : [...mapped, { id: 'custom', icon: '🛠️', label: 'Custom', domain: 'general', prompt: '' }]);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    // Fetch LLM config and optionally active-provider for dynamic model label
    Promise.all([
      api.getLlmConfig().catch(() => ({ data: {} })),
      api.client.get('/settings/active-provider').catch(() => ({ data: null })),
    ]).then(([llmRes, providerRes]) => {
      const d = llmRes.data || {};
      const providerData = providerRes.data;

      const fetched = [];

      // If active-provider endpoint returned info, show it as the first/primary option
      if (providerData?.provider && providerData?.model) {
        const providerLabel = providerData.provider.charAt(0).toUpperCase() + providerData.provider.slice(1);
        fetched.push({ value: providerData.model, label: `${providerLabel} — ${providerData.model}` });
      } else if (d.openrouter_heavy_model) {
        // Fall back to constructing label from LLM config
        const parts = d.openrouter_heavy_model.split('/');
        const providerPart = parts.length > 1 ? parts[0].charAt(0).toUpperCase() + parts[0].slice(1) : 'OpenRouter';
        fetched.push({ value: d.openrouter_heavy_model, label: `${providerPart} — ${d.openrouter_heavy_model} (OpenRouter)` });
      }

      if (d.ollama_model) {
        fetched.push({ value: d.ollama_model, label: `Ollama — ${d.ollama_model}` });
      }

      // Deduplicate: remove DEFAULT_MODELS entries that are overridden by fetched
      const fetchedValues = new Set(fetched.map(f => f.value));
      const filteredDefaults = DEFAULT_MODELS.filter(m => !fetchedValues.has(m.value));
      const allModels = fetched.length ? [...fetched, ...filteredDefaults] : DEFAULT_MODELS;
      setModels(allModels);

      const primary = d.primary_llm || 'openrouter';
      let def = allModels[0].value;
      if (providerData?.model && allModels.some(m => m.value === providerData.model)) {
        def = providerData.model;
      } else if (primary === 'openrouter' && d.openrouter_heavy_model && allModels.some(m => m.value === d.openrouter_heavy_model)) {
        def = d.openrouter_heavy_model;
      } else if (primary === 'ollama' && d.ollama_model) {
        def = d.ollama_model;
      }
      setModel(allModels.some(m => m.value === def) ? def : allModels[0].value);
    });
  }, []);

  useEffect(() => {
    if (step === 4) {
      api.estimateCost({ domain, backend: backendFw, database: dbChoice, scale: 'small' })
        .then(res => setEstimate(res.data))
        .catch(() => {});
    }
  }, [step, domain, backendFw, dbChoice]);

  // Compile wizard answers → prompt + auto-detect domain
  useEffect(() => {
    const { who, scale, money, industry, mobile, problem, features } = wizardAnswers;
    if (!problem.trim()) return;
    const lines = [];
    const tpl = templates.find(t => t.id === selectedTpl);
    if (tpl && tpl.id !== 'custom') lines.push(`Build a ${tpl.label} application.`);
    lines.push(`Main goal: ${problem.trim()}`);
    const whoMap = { internal: 'Internal team only', customers: 'Customers / end-users', both: 'Both internal team and customers' };
    if (who) lines.push(`Users: ${whoMap[who]}`);
    const scaleMap = { small: 'Under 100 users (small team)', medium: '100–10,000 users', large: '10,000+ users (must scale to high traffic)' };
    if (scale) lines.push(`Scale: ${scaleMap[scale]}`);
    if (money === true) lines.push('Handles money: Yes — integrate payment processing with PCI security.');
    const industryMap = {
      healthcare: 'Healthcare — HIPAA compliance required',
      finance: 'Finance — SOC2/PCI-DSS compliance required',
      government: 'Government / public sector',
      education: 'Education',
    };
    if (industry && industry !== 'general') lines.push(`Industry: ${industryMap[industry]}`);
    const mobileMap = { desktop: 'Desktop web only', responsive: 'Responsive web (mobile-friendly)', mobile: 'Mobile-first (optimized for phones)' };
    if (mobile) lines.push(`Platform: ${mobileMap[mobile]}`);
    if (features.trim()) lines.push(`Must-have features: ${features.trim()}`);
    setPrompt(lines.join('\n'));
    const domainMap = { healthcare: 'healthcare', finance: 'fintech', education: 'education' };
    if (domainMap[industry]) setDomain(domainMap[industry]);
  }, [wizardAnswers, selectedTpl, templates]);

  const selectTemplate = (tpl) => {
    setSelectedTpl(tpl.id);
    setName(tpl.name || tpl.label || '');
    if (tpl.id !== 'custom') setPrompt(tpl.prompt || '');
    setDomain(tpl.domain || 'general');
  };

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
      setUploadedText(text);
      setUploadFilename(file.name);
      if (text) setWizardAnswers(a => ({ ...a, features: a.features ? a.features + '\n\n' + text : text }));
    } catch (e) {
      setUploadError('Upload failed: ' + (e.message || 'unknown'));
    } finally {
      setUploading(false);
    }
  };

  const handleFetchRepo = async () => {
    if (!repoUrl.trim()) return;
    setFetchingRepo(true);
    setRepoContext('');
    setUploadError('');
    try {
      const payload = { type: repoType, url: repoUrl.trim() };
      if (repoToken.trim())  payload.token     = repoToken.trim();
      if (repoSshKey.trim()) payload.ssh_key   = repoSshKey.trim();
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
    setImportingSchema(true);
    setSchemaError('');
    setImportedSchema(null);
    try {
      const res = await api.client.post('/factory/import-schema', { connection_string: schemaConnStr.trim() });
      if (res.data?.error) {
        setSchemaError(res.data.error);
      } else {
        setImportedSchema(res.data);
      }
    } catch (e) {
      setSchemaError('Import failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setImportingSchema(false);
    }
  };

  const canProceed = () => {
    if (step === 1) return selectedTpl !== null;
    if (step === 2) return prompt.trim().length > 0;
    return true;
  };

  const handleLaunch = async () => {
    if (!prompt.trim()) { setError('Requirement is required.'); return; }
    setLoading(true);
    setError(null);
    try {
      const designerSpec = {
        frontend: { framework: frontendFw === 'React' ? 'React + Vite' : frontendFw, styling: 'Tailwind CSS' },
        backend: { framework: backendFw, database: dbChoice },
        design: { ui_theme: 'default' },
      };
      const payload = {
        raw_input: prompt.trim() + (repoContext ? `\n\nExisting codebase context:\n${repoContext.slice(0, 3000)}` : ''),
        project_name: name.trim() || undefined,
        domain,
        model_preference: model,
        priority: priority.toLowerCase(),
        client_id: name.trim() ? name.trim().toLowerCase().replace(/\s+/g, '-') : 'client-001',
        tech_preferences: { backend: backendFw, frontend: frontendFw, database: dbChoice },
        codebase_mode: projectMode,
        designer_spec: designerSpec,
        ...(importedSchema ? { existing_schema: importedSchema } : {}),
      };
      const res = await api.startPipeline(payload);
      navigate(res.data?.run_id ? `/project/${res.data.run_id}` : '/projects');
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to start run.');
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-bright">New Factory Run</h1>
        <p className="text-sm text-muted mt-1">AetherOS will generate a complete working application from your requirements.</p>
      </div>

      <StepIndicator step={step} />

      {/* ── Step 1: Template + Mode ─── */}
      {step === 1 && (
        <div className="space-y-6">
          <div className="flex gap-3">
            {[['new', '✨', 'Start fresh'], ['existing', '🔗', 'Improve existing codebase']].map(([mode, icon, label]) => (
              <button key={mode} onClick={() => setProjectMode(mode)}
                className={`flex-1 flex items-center justify-center gap-2 py-3 rounded-xl border text-sm font-semibold transition-all ${
                  projectMode === mode ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-accent/40'
                }`}>
                <span>{icon}</span><span>{label}</span>
              </button>
            ))}
          </div>

          <div>
            <h2 className="text-base font-semibold text-bright mb-4">
              {projectMode === 'new' ? 'What do you want to build?' : 'Choose a starting template'}
            </h2>
            <div className="grid grid-cols-4 gap-3">
              {templates.map(tpl => (
                <TemplateCard key={tpl.id} tpl={tpl} selected={selectedTpl === tpl.id} onClick={() => selectTemplate(tpl)} />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Step 2: Guided questionnaire ─── */}
      {step === 2 && (
        <div className="space-y-6">
          <div>
            <h2 className="text-base font-semibold text-bright">Tell us about your project</h2>
            <p className="text-xs text-muted mt-1">Answer a few questions so AetherOS can build exactly what you need.</p>
          </div>

          {/* Project name */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">
              Project Name <span className="text-slate-500 font-normal normal-case">(optional)</span>
            </label>
            <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. TaskFlow"
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm text-bright placeholder:text-muted/50 focus:outline-none focus:border-accent" />
          </div>

          {/* Q1: Who uses it */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">1. Who uses this app?</label>
            <PillGroup
              options={[['internal', '👥 Internal team'], ['customers', '🌐 Our customers'], ['both', '🔀 Both']]}
              value={wizardAnswers.who}
              onChange={val => setWizardAnswers(a => ({ ...a, who: a.who === val ? '' : val }))}
            />
          </div>

          {/* Q2: Scale */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">2. Expected scale</label>
            <PillGroup
              options={[['small', '🏠 Under 100 users'], ['medium', '🏢 100–10,000 users'], ['large', '🏙️ 10,000+ users']]}
              value={wizardAnswers.scale}
              onChange={val => setWizardAnswers(a => ({ ...a, scale: a.scale === val ? '' : val }))}
            />
          </div>

          {/* Q3: Handles payments */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">3. Handles payments?</label>
            <PillGroup
              options={[[true, '💳 Yes'], [false, '✕ No']]}
              value={wizardAnswers.money}
              onChange={val => setWizardAnswers(a => ({ ...a, money: val }))}
            />
          </div>

          {/* Q4: Industry */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">4. Industry / Compliance</label>
            <PillGroup
              options={[
                ['general', '🌐 General'],
                ['healthcare', '🏥 Healthcare (HIPAA)'],
                ['finance', '💳 Finance (PCI/SOC2)'],
                ['government', '🏛️ Government'],
                ['education', '🎓 Education'],
              ]}
              value={wizardAnswers.industry}
              onChange={val => setWizardAnswers(a => ({ ...a, industry: val }))}
            />
          </div>

          {/* Q5: Platform */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">5. Platform / Device</label>
            <PillGroup
              options={[['desktop', '🖥️ Desktop only'], ['responsive', '📱 Responsive web'], ['mobile', '📲 Mobile-first']]}
              value={wizardAnswers.mobile}
              onChange={val => setWizardAnswers(a => ({ ...a, mobile: a.mobile === val ? '' : val }))}
            />
          </div>

          {/* Q6: Main problem (required) */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">
              6. What problem does this solve? <span className="text-danger">*</span>
            </label>
            <textarea
              value={wizardAnswers.problem}
              onChange={e => setWizardAnswers(a => ({ ...a, problem: e.target.value }))}
              rows={3}
              placeholder="e.g. Our sales team tracks leads in spreadsheets — we need a CRM to manage pipeline, contacts, and follow-ups."
              className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-sm text-bright placeholder:text-muted/50 focus:outline-none focus:border-accent resize-none"
            />
          </div>

          {/* Q7: Must-have features (optional) */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">
              7. Must-have features <span className="text-slate-500 font-normal normal-case">(optional)</span>
            </label>
            <textarea
              value={wizardAnswers.features}
              onChange={e => setWizardAnswers(a => ({ ...a, features: e.target.value }))}
              rows={2}
              placeholder="e.g. CSV import, email notifications, role-based access, PDF exports, mobile app…"
              className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-sm text-bright placeholder:text-muted/50 focus:outline-none focus:border-accent resize-none"
            />
          </div>

          {/* File import */}
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted">Have a requirements doc?</span>
            <button onClick={() => fileInputRef.current?.click()} disabled={uploading}
              className="text-xs px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-bright rounded-md transition-colors disabled:opacity-50">
              {uploading ? 'Reading…' : '📄 Import file'}
            </button>
            {uploadFilename && <span className="text-[10px] text-emerald-400">📎 {uploadFilename}</span>}
            <input ref={fileInputRef} type="file" accept=".txt,.md,.pdf,.docx,.rst" className="hidden" onChange={handleFileUpload} />
          </div>
          {uploadError && <p className="text-xs text-danger">{uploadError}</p>}

          {/* Existing codebase section */}
          {projectMode === 'existing' && (
            <div className="space-y-3 bg-surface border border-border rounded-xl p-4">
              <p className="text-xs font-semibold text-muted uppercase tracking-wider">Connect Existing Codebase</p>
              <div className="flex gap-2">
                {[['github','GitHub'],['gitlab','GitLab'],['ssh','SSH']].map(([t,label]) => (
                  <button key={t} onClick={() => setRepoType(t)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors border ${repoType === t ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:text-bright'}`}>
                    {label}
                  </button>
                ))}
              </div>
              {repoType === 'gitlab' && (
                <input type="url" value={gitlabUrl} onChange={e => setGitlabUrl(e.target.value)}
                  placeholder="https://gitlab.com (or self-hosted URL)"
                  className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
              )}
              <input type={repoType === 'ssh' ? 'text' : 'url'} value={repoUrl} onChange={e => setRepoUrl(e.target.value)}
                placeholder={repoType === 'ssh' ? 'git@github.com:owner/repo.git' : `https://${repoType === 'gitlab' ? 'gitlab.com' : 'github.com'}/owner/repo`}
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
              {repoType !== 'ssh' ? (
                <input type="password" value={repoToken} onChange={e => setRepoToken(e.target.value)}
                  placeholder={`${repoType === 'gitlab' ? 'GitLab' : 'GitHub'} Personal Access Token (private repos)`}
                  className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
              ) : (
                <textarea value={repoSshKey} onChange={e => setRepoSshKey(e.target.value)} rows={4}
                  placeholder="Paste your PEM private SSH key (-----BEGIN OPENSSH PRIVATE KEY-----)"
                  className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-xs text-bright font-mono focus:outline-none focus:border-accent resize-none" />
              )}
              <button onClick={handleFetchRepo} disabled={fetchingRepo || !repoUrl.trim()}
                className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors">
                {fetchingRepo ? 'Fetching…' : 'Fetch Repo Context'}
              </button>
              {repoFetched && <p className="text-xs text-emerald-400">✅ Loaded context from {repoFetched}</p>}
            </div>
          )}

          {/* Domain — auto-set but still editable */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">
              Domain <span className="text-slate-500 font-normal normal-case">(auto-detected from industry)</span>
            </label>
            <select value={domain} onChange={e => setDomain(e.target.value)}
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm text-bright focus:outline-none focus:border-accent">
              {['general','saas','fintech','healthcare','ecommerce','analytics','education','iot','marketplace','social','api','cms','erp'].map(d => (
                <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
              ))}
            </select>
          </div>

          {/* Import existing schema */}
          <div className="border border-border rounded-xl overflow-hidden">
            <button type="button" onClick={() => setSchemaOpen(o => !o)}
              className="w-full flex items-center justify-between px-4 py-3 bg-surface hover:bg-surface/80 transition-colors text-left">
              <span className="text-xs font-semibold text-muted uppercase tracking-wider">
                Import existing schema
                {importedSchema && (
                  <span className="ml-2 normal-case text-emerald-400 font-normal">
                    — {importedSchema.tables.length} table{importedSchema.tables.length !== 1 ? 's' : ''} imported
                  </span>
                )}
              </span>
              <span className="text-muted text-xs">{schemaOpen ? '▲' : '▼'}</span>
            </button>
            {schemaOpen && (
              <div className="px-4 pb-4 pt-3 space-y-3 bg-bg border-t border-border">
                <p className="text-xs text-muted">
                  Point at an existing PostgreSQL, MySQL, or SQLite database. AetherOS will read its schema
                  and feed it into the architecture phase instead of generating one from scratch.
                </p>
                <input type="password" value={schemaConnStr} onChange={e => setSchemaConnStr(e.target.value)}
                  placeholder="postgresql://user:pass@host:5432/dbname"
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright font-mono placeholder:text-muted/50 focus:outline-none focus:border-accent" />
                <div className="flex items-center gap-3">
                  <button type="button" onClick={handleImportSchema} disabled={importingSchema || !schemaConnStr.trim()}
                    className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors">
                    {importingSchema ? 'Connecting…' : 'Test & Import'}
                  </button>
                  {importedSchema && !schemaError && (
                    <span className="text-xs text-emerald-400">
                      {importedSchema.tables.length} table{importedSchema.tables.length !== 1 ? 's' : ''} detected
                      {importedSchema.tables.length > 0 && ` (${importedSchema.tables.map(t => t.name).slice(0, 4).join(', ')}${importedSchema.tables.length > 4 ? '…' : ''})`}
                    </span>
                  )}
                </div>
                {schemaError && <p className="text-xs text-danger">{schemaError}</p>}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Step 3: Configure ─── */}
      {step === 3 && (
        <div className="space-y-5">
          <h2 className="text-base font-semibold text-bright">Configure the run</h2>

          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted uppercase tracking-wider">Backend</label>
              <select value={backendFw} onChange={e => setBackendFw(e.target.value)}
                className="w-full bg-surface border border-border rounded-lg px-3 py-2.5 text-sm text-bright focus:outline-none focus:border-accent">
                {BACKEND_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted uppercase tracking-wider">Frontend</label>
              <select value={frontendFw} onChange={e => setFrontendFw(e.target.value)}
                className="w-full bg-surface border border-border rounded-lg px-3 py-2.5 text-sm text-bright focus:outline-none focus:border-accent">
                {FRONTEND_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted uppercase tracking-wider">Database</label>
              <select value={dbChoice} onChange={e => setDbChoice(e.target.value)}
                className="w-full bg-surface border border-border rounded-lg px-3 py-2.5 text-sm text-bright focus:outline-none focus:border-accent">
                {DB_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">LLM Model</label>
            <select value={model} onChange={e => setModel(e.target.value)}
              className="w-full bg-surface border border-border rounded-lg px-3 py-2.5 text-sm text-bright focus:outline-none focus:border-accent">
              {models.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">Priority</label>
            <div className="flex gap-3">
              {PRIORITIES.map(p => (
                <button key={p} onClick={() => setPriority(p)}
                  className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                    priority === p ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-accent/50'
                  }`}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Step 4: Review & Launch ─── */}
      {step === 4 && (
        <div className="space-y-5">
          <h2 className="text-base font-semibold text-bright">Review & Launch</h2>

          <div className="bg-surface border border-border rounded-xl p-5 space-y-3">
            {[
              ['Project', name || '(auto-named)'],
              ['Mode', projectMode === 'existing' ? '🔗 Improve existing' : '✨ Greenfield'],
              ['Domain', domain],
              ['Stack', `${backendFw} · ${frontendFw} · ${dbChoice}`],
              ['Model', models.find(m => m.value === model)?.label || model],
              ['Priority', priority],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="text-xs text-muted uppercase font-semibold tracking-wider">{k}</span>
                <span className="text-sm text-bright font-medium">{v}</span>
              </div>
            ))}
            {wizardAnswers.who && (
              <div className="flex justify-between">
                <span className="text-xs text-muted uppercase font-semibold tracking-wider">Users</span>
                <span className="text-sm text-bright font-medium">{{ internal: 'Internal team', customers: 'Customers', both: 'Both' }[wizardAnswers.who]}</span>
              </div>
            )}
            {wizardAnswers.scale && (
              <div className="flex justify-between">
                <span className="text-xs text-muted uppercase font-semibold tracking-wider">Scale</span>
                <span className="text-sm text-bright font-medium">{{ small: 'Under 100', medium: '100–10K', large: '10K+' }[wizardAnswers.scale]}</span>
              </div>
            )}
            {wizardAnswers.money === true && (
              <div className="flex justify-between">
                <span className="text-xs text-muted uppercase font-semibold tracking-wider">Payments</span>
                <span className="text-sm text-emerald-400 font-medium">Yes</span>
              </div>
            )}
            {repoFetched && (
              <div className="flex justify-between">
                <span className="text-xs text-muted uppercase font-semibold tracking-wider">Repo</span>
                <span className="text-sm text-emerald-400">{repoFetched}</span>
              </div>
            )}
            {importedSchema && importedSchema.tables.length > 0 && (
              <div className="flex justify-between">
                <span className="text-xs text-muted uppercase font-semibold tracking-wider">Schema</span>
                <span className="text-sm text-emerald-400">{importedSchema.tables.length} tables imported</span>
              </div>
            )}
            <div className="border-t border-border pt-3">
              <span className="text-xs text-muted uppercase font-semibold tracking-wider">Requirement</span>
              <p className="text-sm text-bright mt-1 line-clamp-4 leading-relaxed whitespace-pre-line">{prompt}</p>
            </div>
          </div>

          {estimate && (
            <div className="bg-emerald-950/40 border border-emerald-800/40 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">💰 Estimated Hosting Cost</span>
                <span className="text-lg font-bold text-emerald-300">{estimate.range}</span>
              </div>
              <div className="flex gap-4 text-[10px] text-muted">
                <span>Compute: ${estimate.breakdown?.compute}/mo</span>
                <span>Database: ${estimate.breakdown?.database}/mo</span>
                <span>Extras: ${estimate.breakdown?.extras}/mo</span>
              </div>
              <p className="text-[10px] text-muted mt-1">{estimate.note}</p>
            </div>
          )}

          {error && (
            <div className="bg-danger/10 border border-danger/30 rounded-lg px-4 py-3 text-sm text-danger">{error}</div>
          )}

          <div className="flex flex-col gap-3">
            <button onClick={handleLaunch} disabled={loading}
              className="w-full flex items-center justify-center gap-2 py-3 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-xl text-base transition-colors">
              {loading ? (
                <><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Starting Factory Run…</>
              ) : '🚀 Start Factory Run'}
            </button>
            <button type="button"
              onClick={() => {
                const params = new URLSearchParams();
                if (name) params.set('name', name);
                if (selectedTpl && selectedTpl !== 'custom') params.set('template', selectedTpl);
                if (domain) params.set('domain', domain);
                if (prompt.trim()) params.set('req', encodeURIComponent(prompt.trim().slice(0, 1000)));
                params.set('backend', backendFw);
                params.set('frontend', frontendFw);
                params.set('db', dbChoice);
                navigate(`/designer?${params.toString()}`);
              }}
              className="w-full flex items-center justify-center gap-2 py-2.5 border border-border text-muted hover:text-bright hover:border-accent/50 text-sm font-semibold rounded-xl transition-colors">
              🎨 Configure in Designer
            </button>
          </div>
        </div>
      )}

      {/* ── Navigation ─── */}
      <div className="flex justify-between mt-8">
        <button onClick={() => step > 1 ? setStep(step - 1) : navigate('/projects')}
          className="px-5 py-2.5 text-sm font-medium text-muted hover:text-bright border border-border rounded-lg transition-colors">
          {step === 1 ? 'Cancel' : '← Back'}
        </button>
        {step < 4 && (
          <button onClick={() => setStep(step + 1)} disabled={!canProceed()}
            className="px-6 py-2.5 bg-accent hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-bold rounded-lg transition-colors">
            {step === 3 ? 'Review →' : 'Next →'}
          </button>
        )}
      </div>
    </div>
  );
};

export default NewProjectWizard;
