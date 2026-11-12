import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate, useSearchParams, useParams } from 'react-router-dom';
import { Wand2, X, Loader2 } from 'lucide-react';
import { api } from '../api';

// Extracted: static data, helpers, sub-components, tab components (600-line limit)
import {
  TEMPLATES, STACK, PRIORITIES, TABS, COLOR_SLOTS, UI_THEMES, LAYOUTS,
  DEFAULT_MODELS, DEFAULT_SPEC, calcComplexity,
} from '../components/project-designer/DesignerData';
import { SearchableSelect, StackGroup, RunOutput } from '../components/project-designer/DesignerComponents';
import { UnderstandTab, DesignTab, ComplianceTab } from '../components/project-designer/DesignerTabs';
import ErrorText from '../components/ErrorText';
import { apiError, apiErrorState } from '../apiError';

// ── Main Component ─────────────────────────────────────────────────────────────
const ProjectDesigner = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { id: urlRunId } = useParams();

  // Opening /designer/:id shows the build tab; ?template, ?req, ?domain and ?name prefill the form.
  const [activeTab, setActiveTab] = useState(urlRunId ? 5 : 0);
  const [init] = useState(() => {
    const tplParam = searchParams.get('template');
    const match = tplParam ? TEMPLATES.find(t => t.id === tplParam || t.domain === tplParam) : null;
    const req = searchParams.get('req');
    return {
      template: match?.id ?? null,
      name: searchParams.get('name') || (match && match.label !== 'Custom' ? match.label : ''),
      requirement: req ? decodeURIComponent(req) : (match && match.id !== 'custom' ? match.prompt || '' : ''),
      domain: searchParams.get('domain') || match?.domain || tplParam || 'general',
    };
  });
  const [spec, setSpec] = useState(JSON.parse(JSON.stringify(DEFAULT_SPEC)));

  // ── Understand tab state ───────────────────────────────────────────────────
  const [selectedTemplate, setSelectedTemplate] = useState(init.template);
  const [projectName, setProjectName] = useState(init.name);
  const [requirement, setRequirement] = useState(init.requirement);
  const [domain, setDomain] = useState(init.domain);
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

  // ── Compliance tab state (must be at component level — Rules of Hooks) ─────
  const [countrySearch, setCountrySearch] = useState('');

  // ── Launch state ──────────────────────────────────────────────────────────
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState('');
  const [runId, setRunId] = useState(urlRunId || null);


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
    if (activeTab === 4) {
      api.estimateCost({ domain, backend: spec.backend.framework, database: spec.backend.database, scale: 'small' })
        .then(res => setEstimate(res.data))
        .catch(() => {});
    }
  }, [activeTab, domain, spec.backend.framework, spec.backend.database]);

  // ── Helpers ────────────────────────────────────────────────────────────────
  const updateSpec = useCallback((section, key, value) =>
    setSpec(prev => ({ ...prev, [section]: { ...prev[section], [key]: value } })), []);

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
      setUploadError('Upload failed: ' + (apiError(e) || e.message || 'unknown'));
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
      setUploadError('Repo fetch failed: ' + (apiError(e) || e.message));
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
      setSchemaError('Import failed: ' + (apiError(e) || e.message));
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
          ui_theme: spec.design.ui_theme || 'default',
          page_transition: spec.design.page_transition || 'fade',
          animation_speed: spec.design.animation_speed || 'normal',
          micro_interactions: spec.design.micro_interactions !== false,
          scroll_reveal: spec.design.scroll_reveal !== false,
          loading_style: spec.design.loading_style || 'shimmer',
          hover_lift: spec.design.hover_lift !== false,
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
        production_country: spec.compliance.production_country || undefined,
        compliance_flags: {
          data_sensitivity: spec.compliance.data_sensitivity,
          handles_personal_data: spec.compliance.handles_personal_data,
          handles_biometric_data: spec.compliance.handles_biometric_data,
          handles_children_data: spec.compliance.handles_children_data,
          requires_data_residency: spec.compliance.requires_data_residency,
          deployment_type: spec.compliance.deployment_type,
        },
        ...(importedSchema ? { existing_schema: importedSchema } : {}),
      };
      const res = await api.startPipeline(payload);
      const newRunId = res.data?.run_id;
      if (newRunId) {
        setRunId(newRunId);
        setActiveTab(5);
        navigate(`/designer/${newRunId}`, { replace: true });
      }
    } catch (err) {
      setLaunchError(apiErrorState(err, 'Failed to launch build.'));
    } finally {
      setLaunching(false);
    }
  };

  const complexity = calcComplexity(spec);

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
            {key:'multi_tenancy',label:'Multi-tenancy'},{key:'audit_log',label:'Audit Log'},
            {key:'rate_limiting',label:'Rate Limiting'},{key:'webhooks_out',label:'Webhooks Out'},
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

  // ── Tab 5: Preview ─────────────────────────────────────────────────────────
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
            <span className="text-muted">Style: <span className="text-accent font-semibold">{UI_THEMES.find(t => t.id === spec.design.ui_theme)?.label || 'Default Dark'}</span></span>
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
            <p className="text-sm text-red-400"><ErrorText error={launchError} /></p>
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

  // ── Tab 6: Output ──────────────────────────────────────────────────────────
  const renderOutput = () => (
    <div>
      {runId ? <RunOutput runId={runId} /> : (
        <div className="py-20 text-center">
          <Wand2 className="w-12 h-12 text-muted/30 mx-auto mb-4" />
          <p className="text-muted text-sm">No build launched yet.</p>
          <p className="text-muted/60 text-xs mt-1">Your spec is ready — launch the pipeline to generate your app.</p>
          <button onClick={handleLaunch} disabled={launching || !requirement.trim()}
            className="mt-4 px-6 py-2.5 bg-accent hover:bg-accent/90 disabled:opacity-40 text-white text-sm font-semibold rounded-xl transition-colors flex items-center gap-2 mx-auto">
            {launching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
            {launching ? 'Launching…' : '🚀 Launch Build'}
          </button>
          {launchError && <p className="mt-3 text-red-400 text-xs"><ErrorText error={launchError} /></p>}
        </div>
      )}
    </div>
  );

  // Props bundles for extracted tab components
  const understandProps = {
    selectedTemplate, applyTemplate,
    projectMode, setProjectMode,
    projectName, setProjectName,
    domain, setDomain,
    requirement, setRequirement,
    uploadFilename, uploading, uploadError, fileInputRef, handleFileUpload,
    repoType, setRepoType, repoUrl, setRepoUrl, repoToken, setRepoToken,
    repoSshKey, setRepoSshKey, gitlabUrl, setGitlabUrl,
    fetchingRepo, handleFetchRepo, repoFetched,
    schemaOpen, setSchemaOpen, schemaConnStr, setSchemaConnStr,
    importingSchema, handleImportSchema, importedSchema, schemaError,
  };

  const tabContent = [
    () => <UnderstandTab {...understandProps} />,
    renderTechStack,
    () => <DesignTab spec={spec} updateSpec={updateSpec} activeColorSlot={activeColorSlot} setActiveColorSlot={setActiveColorSlot} />,
    () => <ComplianceTab spec={spec} updateSpec={updateSpec} countrySearch={countrySearch} setCountrySearch={setCountrySearch} />,
    renderPreview,
    renderOutput,
  ];

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
          <button key={tab} onClick={() => i !== 4 || runId ? setActiveTab(i) : null}
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
      {(activeTab < 4 || (activeTab === 5 && !runId)) && (
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
