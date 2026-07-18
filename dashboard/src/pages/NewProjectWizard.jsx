import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import {
  DEFAULT_TEMPLATES, DEFAULT_MODELS, PRIORITIES, BACKEND_OPTIONS, FRONTEND_OPTIONS, DB_OPTIONS,
  StepIndicator, TemplateCard,
} from '../components/new-project/WizardShared';
import WizardStep2 from '../components/new-project/WizardStep2';

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
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">New Factory Run</h1>
        <p className="text-sm text-slate-500 mt-1">AetherOS will generate a complete working application from your requirements.</p>
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
        <WizardStep2
          name={name} setName={setName}
          wizardAnswers={wizardAnswers} setWizardAnswers={setWizardAnswers}
          uploading={uploading} uploadFilename={uploadFilename}
          uploadError={uploadError} fileInputRef={fileInputRef} handleFileUpload={handleFileUpload}
          projectMode={projectMode}
          repoType={repoType} setRepoType={setRepoType}
          repoUrl={repoUrl} setRepoUrl={setRepoUrl}
          repoToken={repoToken} setRepoToken={setRepoToken}
          repoSshKey={repoSshKey} setRepoSshKey={setRepoSshKey}
          gitlabUrl={gitlabUrl} setGitlabUrl={setGitlabUrl}
          fetchingRepo={fetchingRepo} handleFetchRepo={handleFetchRepo} repoFetched={repoFetched}
          domain={domain} setDomain={setDomain}
          schemaOpen={schemaOpen} setSchemaOpen={setSchemaOpen}
          schemaConnStr={schemaConnStr} setSchemaConnStr={setSchemaConnStr}
          importingSchema={importingSchema} handleImportSchema={handleImportSchema}
          importedSchema={importedSchema} schemaError={schemaError}
        />
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
            <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3 text-sm text-red-400">{error}</div>
          )}

          <div className="flex flex-col gap-3">
            <button onClick={handleLaunch} disabled={loading}
              className="w-full flex items-center justify-center gap-2 py-3.5 bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-xl text-base transition-all shadow-xl shadow-violet-500/25 hover:shadow-violet-500/40 active:scale-[0.98]">
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
              className="w-full flex items-center justify-center gap-2 py-2.5 border border-white/[0.08] text-slate-400 hover:text-white hover:border-violet-500/30 hover:bg-violet-500/[0.05] text-sm font-semibold rounded-xl transition-all">
              🎨 Configure in Designer
            </button>
          </div>
        </div>
      )}

      {/* ── Navigation ─── */}
      <div className="flex justify-between mt-8">
        <button onClick={() => step > 1 ? setStep(step - 1) : navigate('/projects')}
          className="px-5 py-2.5 text-sm font-medium text-slate-400 hover:text-white border border-white/[0.08] rounded-xl hover:border-white/[0.16] hover:bg-white/[0.04] transition-all">
          {step === 1 ? 'Cancel' : '← Back'}
        </button>
        {step < 4 && (
          <button onClick={() => setStep(step + 1)} disabled={!canProceed()}
            className="px-6 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-bold rounded-xl transition-all shadow-lg shadow-violet-500/20 active:scale-95">
            {step === 3 ? 'Review →' : 'Next →'}
          </button>
        )}
      </div>
    </div>
  );
};

export default NewProjectWizard;
