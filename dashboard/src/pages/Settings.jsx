import React, { useState, useEffect } from 'react';
import { api } from '../api';
import {
  Shield,
  Database,
  Cpu,
  Info,
  CheckCircle2,
  XCircle,
  BarChart3,
  Server,
  Key,
  Settings as SettingsIcon,
  ChevronDown,
  ChevronUp,
  FolderTree,
  FileCode,
  Search,
  Sliders,
  Plus,
  Trash2,
  RefreshCw,
} from 'lucide-react';
import StorageWidget from '../components/StorageWidget';
import { useSettings } from '../contexts/SettingsContext';
import hljs from 'highlight.js';

import 'highlight.js/styles/github-dark.css';

const PhaseConfigPanel = ({ phase, config, onSave }) => {
  const [enabled, setEnabled] = useState(config.enabled !== false);
  const [priority, setPriority] = useState(
    config.priority ? config.priority.charAt(0).toUpperCase() + config.priority.slice(1) : 'Normal'
  );
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    // Backend expects { enabled: bool, priority: 'low'|'normal'|'high' }
    await onSave({ enabled, priority: priority.toLowerCase() });
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  return (
    <div className="p-6 bg-border/5 space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <label className="text-[10px] font-bold text-muted uppercase">Execution Status</label>
          <select
            value={enabled ? 'Enabled' : 'Disabled'}
            onChange={(e) => setEnabled(e.target.value === 'Enabled')}
            className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
          >
            <option>Enabled</option>
            <option>Disabled</option>
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-bold text-muted uppercase">Priority Level</label>
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
          >
            <option>Normal</option>
            <option>High</option>
            <option>Low</option>
          </select>
        </div>
      </div>
      <div className="flex items-center space-x-3 pt-2">
        <button
          onClick={handleSave}
          className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-3 py-1 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors"
        >
          {saved ? '✓ Saved' : 'Save Config'}
        </button>
      </div>
    </div>
  );
};

const Settings = () => {
  const { updateLlmConfig: ctxUpdateLlmConfig } = useSettings();
  const [health, setHealth] = useState(null);
  const [costs, setCosts] = useState({ total_usd: 0, week_usd: 0, today_usd: 0, tokens_today: '—' });
  const [expandedPhase, setExpandedPhase] = useState(null);
  const [apiKeys, setApiKeys] = useState({ anthropic: '', gemini: '', openrouter: '' });
  const [keyStatus, setKeyStatus] = useState({ anthropic: null, gemini: null, openrouter: null }); // null | 'saving' | 'saved' | 'error'
  const [testStatus, setTestStatus] = useState({ anthropic: null, gemini: null, openrouter: null }); // null | 'testing' | 'ok' | 'fail'
  const [phaseConfigs, setPhaseConfigs] = useState({});
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState('');
  const [runFiles, setRunFiles] = useState({});
  const [fileContent, setFileContent] = useState('');
  const [selectedFile, setSelectedFile] = useState('');
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [councilConfig, setCouncilConfig] = useState({ council_enabled: true, council_strict_mode: false });
  const [councilSaveStatus, setCouncilSaveStatus] = useState(null); // null | 'saving' | 'saved' | 'error'
  const [llmConfig, setLlmConfig] = useState({
    openrouter_heavy_model: 'minimax/minimax-m2.5:free',
    openrouter_light_model: 'mistralai/mistral-7b-instruct:free',
    openrouter_fallback_models: [],
  });
  const [availableModels, setAvailableModels] = useState({});
  const [llmSaveStatus, setLlmSaveStatus] = useState(null);
  const [modelTestStatus, setModelTestStatus] = useState({}); // model -> 'testing'|'ok'|'fail'
  const [customModelInput, setCustomModelInput] = useState('');

  // Data region selection
  const [dataRegion, setDataRegion] = useState('global');
  const [regionSaveStatus, setRegionSaveStatus] = useState(null); // null | 'saving' | 'saved' | 'error'

  // SSO / SAML config (T6-04)
  const [ssoConfig, setSsoConfig] = useState(null);
  const [ssoForm, setSsoForm] = useState({ idp_entity_id: '', idp_sso_url: '', idp_cert: '' });
  const [ssoStatus, setSsoStatus] = useState(null); // null | 'saving' | 'saved' | 'error' | 'deleting'

  // Must match PHASE_SEQUENCE in orchestrator/factory_pipeline.py exactly (12 phases).
  // Previously had 10 phases — missing p07b_self_healing and p11_deployment.
  const PHASES = [
    'p01_intake_requirements',
    'p02_architecture',
    'p03_scaffolding',
    'p04_backend',
    'p05_frontend',
    'p06_review_security',
    'p07_testing',
    'p07b_self_healing',
    'p08_cicd_deployment',
    'p09_observability',
    'p10_docs_delivery',
    'p11_deployment',
  ];

  const PHASE_NAMES = {
    p01_intake_requirements: 'Intake & Requirements',
    p02_architecture:        'Architecture',
    p03_scaffolding:         'Scaffolding',
    p04_backend:             'Backend',
    p05_frontend:            'Frontend',
    p06_review_security:     'Review & Security',
    p07_testing:             'Testing',
    p07b_self_healing:       'Self-Healing',
    p08_cicd_deployment:     'CI/CD & Deployment',
    p09_observability:       'Observability',
    p10_docs_delivery:       'Docs & Delivery',
    p11_deployment:          'Deployment',
  };

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [hRes, cRes, rRes, pcRes, keyRes, ccRes, llmRes, modelsRes] = await Promise.allSettled([
          api.getHealth(),
          api.getCosts(),
          api.listRuns(),
          api.getPhaseConfigs(),
          api.getApiKeys(),
          api.getCouncilConfig(),
          api.getLlmConfig(),
          api.getAvailableModels(),
        ]);
        if (hRes.status === 'fulfilled') setHealth(hRes.value.data);
        if (cRes.status === 'fulfilled') setCosts(cRes.value.data);
        if (rRes.status === 'fulfilled') setRuns(rRes.value.data?.items ?? rRes.value.data ?? []);
        if (pcRes.status === 'fulfilled') {
          const cfgArray = pcRes.value.data || [];
          const cfgDict = {};
          cfgArray.forEach(c => { cfgDict[c.phase_name] = c; });
          setPhaseConfigs(cfgDict);
        }
        if (keyRes.status === 'fulfilled') {
          const kd = keyRes.value.data || {};
          setApiKeys({
            anthropic: kd.anthropic || '',
            gemini: kd.google || '',
            openrouter: kd.openrouter || '',
          });
        }
        if (ccRes.status === 'fulfilled') {
          setCouncilConfig(ccRes.value.data || { council_enabled: true, council_strict_mode: false });
        }
        if (llmRes.status === 'fulfilled') {
          const d = llmRes.value.data || {};
          setLlmConfig({
            openrouter_heavy_model: d.openrouter_heavy_model || 'minimax/minimax-m2.5:free',
            openrouter_light_model: d.openrouter_light_model || 'mistralai/mistral-7b-instruct:free',
            openrouter_fallback_models: d.openrouter_fallback_models || [],
          });
        }
        if (modelsRes.status === 'fulfilled') {
          setAvailableModels(modelsRes.value.data?.openrouter || {});
        }
        // SSO config
        try {
          const ssoRes = await api.client.get('/settings/sso');
          setSsoConfig(ssoRes.data);
          if (ssoRes.data.configured) {
            setSsoForm(f => ({ ...f, idp_entity_id: ssoRes.data.idp_entity_id || '', idp_sso_url: ssoRes.data.idp_sso_url || '' }));
          }
        } catch (_) {}

        // Data region — from org compliance report which exposes data_region
        try {
          const compRes = await api.client.get('/compliance/org-report');
          if (compRes.data?.data_region) setDataRegion(compRes.data.data_region.toLowerCase());
        } catch (_) {}
      } catch (err) {
        console.error('Settings fetch error', err);
      }
    };
    fetchData();
  }, []);

  const handleUpdateKey = async (provider) => {
    const key = apiKeys[provider];
    if (!key.trim()) return;
    setKeyStatus(s => ({ ...s, [provider]: 'saving' }));
    try {
      await api.saveApiKeys(provider, key);
      setKeyStatus(s => ({ ...s, [provider]: 'saved' }));
      setTimeout(() => setKeyStatus(s => ({ ...s, [provider]: null })), 3000);
    } catch (err) {
      setKeyStatus(s => ({ ...s, [provider]: 'error' }));
    }
  };

  const handleTestKey = async (provider) => {
    setTestStatus(s => ({ ...s, [provider]: 'testing' }));
    try {
      await api.testProvider(provider);
      setTestStatus(s => ({ ...s, [provider]: 'ok' }));
      setTimeout(() => setTestStatus(s => ({ ...s, [provider]: null })), 4000);
    } catch (err) {
      setTestStatus(s => ({ ...s, [provider]: 'fail' }));
      setTimeout(() => setTestStatus(s => ({ ...s, [provider]: null })), 4000);
    }
  };

  const handleSavePhaseConfig = async (phase, config) => {
    try {
      await api.savePhaseConfig(phase, config);
    } catch (err) {
      console.error('Failed to save phase config', err);
    }
  };

  const handleSaveCouncilConfig = async () => {
    setCouncilSaveStatus('saving');
    try {
      await api.updateCouncilConfig(councilConfig);
      setCouncilSaveStatus('saved');
      setTimeout(() => setCouncilSaveStatus(null), 3000);
    } catch (err) {
      setCouncilSaveStatus('error');
      setTimeout(() => setCouncilSaveStatus(null), 3000);
    }
  };

  const handleSaveLlmConfig = async () => {
    setLlmSaveStatus('saving');
    try {
      await api.updateLlmConfig(llmConfig);
      ctxUpdateLlmConfig(llmConfig);
      setLlmSaveStatus('saved');
      setTimeout(() => setLlmSaveStatus(null), 3000);
    } catch {
      setLlmSaveStatus('error');
      setTimeout(() => setLlmSaveStatus(null), 3000);
    }
  };

  const handleTestModel = async (modelId) => {
    if (!modelId) return;
    setModelTestStatus(s => ({ ...s, [modelId]: 'testing' }));
    try {
      const res = await api.testModel(modelId);
      const ok = res.data?.success;
      setModelTestStatus(s => ({ ...s, [modelId]: ok ? 'ok' : 'fail' }));
      setTimeout(() => setModelTestStatus(s => { const n = { ...s }; delete n[modelId]; return n; }), 4000);
    } catch {
      setModelTestStatus(s => ({ ...s, [modelId]: 'fail' }));
      setTimeout(() => setModelTestStatus(s => { const n = { ...s }; delete n[modelId]; return n; }), 4000);
    }
  };

  const addFallbackModel = (modelId) => {
    const m = modelId.trim();
    if (!m || llmConfig.openrouter_fallback_models.includes(m)) return;
    setLlmConfig(c => ({ ...c, openrouter_fallback_models: [...c.openrouter_fallback_models, m] }));
    setCustomModelInput('');
  };

  const removeFallbackModel = (modelId) => {
    setLlmConfig(c => ({ ...c, openrouter_fallback_models: c.openrouter_fallback_models.filter(m => m !== modelId) }));
  };

  // Recursively flatten the nested tree returned by /factory/runs/{id}/files
  const flattenTree = (items) => {
    const paths = [];
    for (const item of items || []) {
      if (item.type === 'file') {
        paths.push(item.path);
      } else if (item.type === 'directory' && item.children) {
        paths.push(...flattenTree(item.children));
      }
    }
    return paths;
  };

  const handleSaveDataRegion = async () => {
    setRegionSaveStatus('saving');
    try {
      await api.client.post('/account/settings', { data_region: dataRegion });
      setRegionSaveStatus('saved');
      setTimeout(() => setRegionSaveStatus(null), 2500);
    } catch {
      setRegionSaveStatus('error');
      setTimeout(() => setRegionSaveStatus(null), 3000);
    }
  };

  const handleRunSelect = async (runId) => {
    setSelectedRun(runId);
    setSelectedFile('');
    setFileContent('');
    if (!runId) { setRunFiles({}); return; }
    setLoadingFiles(true);
    try {
      const res = await api.getRunFiles(runId);
      // API returns { run_id, tree: [{name, type, path, children?, size_bytes?}] }
      const tree = res.data?.tree || [];
      const filePaths = flattenTree(tree);
      // Group by top-level directory (or 'root' for top-level files)
      const grouped = {};
      filePaths.forEach(path => {
        const parts = path.split('/');
        const group = parts.length > 1 ? parts[0] : 'root';
        if (!grouped[group]) grouped[group] = [];
        grouped[group].push(path);
      });
      setRunFiles(grouped);
    } catch (err) {
      setRunFiles({});
    } finally {
      setLoadingFiles(false);
    }
  };

  const handleFileClick = async (filePath) => {
    setSelectedFile(filePath);
    setFileContent('');
    try {
      const res = await api.getFileContent(selectedRun, filePath);
      // Response shape: { path, content, language, size_bytes, truncated, type }
      const payload = res.data;
      if (payload?.type === 'image') {
        setFileContent('// Image file — cannot preview');
      } else {
        setFileContent(payload?.content || '// (empty file)');
      }
    } catch (err) {
      setFileContent(`// Could not load file: ${filePath}`);
    }
  };

  useEffect(() => {
    if (fileContent) {
      document.querySelectorAll('pre code').forEach((block) => {
        hljs.highlightElement(block);
      });
    }
  }, [fileContent]);

  const StatusRow = ({ label, status, detail }) => (
    <div className="flex items-center justify-between p-4 border-b border-border last:border-0">
      <div className="flex items-center space-x-4">
        <div className={`w-2 h-2 rounded-full ${status ? 'bg-success' : 'bg-danger'}`}></div>
        <span className="text-sm font-medium text-bright">{label}</span>
      </div>
      <div className="flex items-center space-x-3">
        <span className="text-xs text-muted font-mono">{detail}</span>
        {status ? <CheckCircle2 className="w-4 h-4 text-success/50" /> : <XCircle className="w-4 h-4 text-danger/50" />}
      </div>
    </div>
  );

  return (
    <div className="max-w-6xl mx-auto space-y-12 pb-20">
      <header className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold">AetherOS Factory Settings</h1>
          <p className="text-muted mt-1">Configure the autonomous development engine and monitor system health.</p>
        </div>
        <StorageWidget />
      </header>

      <div className="grid grid-cols-3 gap-8">
        <div className="col-span-2 space-y-8">
          {/* API Keys Section */}
          <section className="panel overflow-hidden">
            <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
              <Key className="w-4 h-4 mr-2 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">API Key Management</h3>
            </div>
            <div className="p-6 space-y-6">
              {[
                { id: 'anthropic',  label: 'Anthropic API Key' },
                { id: 'gemini',     label: 'Google Gemini Key' },
                { id: 'openrouter', label: 'OpenRouter Key (5 free models)' },
              ].map(({ id, label }) => (
                <div key={id} className="space-y-2">
                  <label className="text-xs font-bold text-muted uppercase tracking-wider block">{label}</label>
                  <div className="flex space-x-2">
                    <input
                      type="password"
                      placeholder="••••••••••••••••"
                      value={apiKeys[id]}
                      onChange={(e) => setApiKeys({...apiKeys, [id]: e.target.value})}
                      className="flex-1 bg-surface border border-border rounded-lg px-4 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                    />
                    <button
                      onClick={() => handleUpdateKey(id)}
                      disabled={keyStatus[id] === 'saving'}
                      className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors min-w-[80px]"
                    >
                      {keyStatus[id] === 'saving' ? '...' : keyStatus[id] === 'saved' ? '✓ SAVED' : keyStatus[id] === 'error' ? '✗ ERROR' : 'UPDATE'}
                    </button>
                    <button
                      onClick={() => handleTestKey(id)}
                      disabled={testStatus[id] === 'testing'}
                      className="bg-border/50 hover:bg-border disabled:opacity-50 text-bright text-xs font-bold px-4 py-2 rounded-lg transition-colors border border-border min-w-[80px]"
                    >
                      {testStatus[id] === 'testing' ? '...' : testStatus[id] === 'ok' ? '✓ OK' : testStatus[id] === 'fail' ? '✗ FAIL' : 'TEST'}
                    </button>
                  </div>
                </div>
              ))}
              <div className="p-3 bg-indigo-600/10 border border-indigo-600/20 rounded-lg flex items-start space-x-3">
                <Info className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
                <p className="text-[10px] text-indigo-200">
                  Keys are stored in your local .env file and never leave your server. Restart the factory service to apply changes.
                  OpenRouter provides 5 free models including DeepSeek-R1 and Llama 4.
                </p>
              </div>
            </div>
          </section>

          {/* Model Configuration Section */}
          <section className="panel overflow-hidden">
            <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
              <Sliders className="w-4 h-4 mr-2 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Model Configuration</h3>
            </div>
            <div className="p-6 space-y-6">
              <p className="text-[11px] text-muted">
                All models route through <span className="text-bright font-mono">openrouter.ai</span>. Copy any model ID from{' '}
                <span className="text-accent font-mono">openrouter.ai/models</span> and paste it below.
                The fallback chain is cycled automatically when a model hits its rate limit.
              </p>

              {/* Primary models */}
              <div className="grid grid-cols-2 gap-4">
                {[
                  { label: 'Heavy Tasks', key: 'openrouter_heavy_model', hint: 'codegen, review, security, architecture' },
                  { label: 'Light Tasks', key: 'openrouter_light_model', hint: 'requirements, docs, classify' },
                ].map(({ label, key, hint }) => (
                  <div key={key} className="space-y-2">
                    <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">
                      {label} <span className="font-normal normal-case text-muted/60">({hint})</span>
                    </label>
                    <select
                      value={Object.values(availableModels).includes(llmConfig[key]) ? llmConfig[key] : '__custom__'}
                      onChange={(e) => {
                        if (e.target.value !== '__custom__')
                          setLlmConfig(c => ({ ...c, [key]: e.target.value }));
                      }}
                      className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
                    >
                      {Object.entries(availableModels).map(([name, id]) => (
                        <option key={id} value={id}>{name} — {id}</option>
                      ))}
                      <option value="__custom__">— paste custom ID below —</option>
                    </select>
                    <input
                      type="text"
                      placeholder="e.g. provider/model-name:free"
                      value={llmConfig[key]}
                      onChange={(e) => setLlmConfig(c => ({ ...c, [key]: e.target.value }))}
                      className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs font-mono text-bright focus:outline-none focus:border-accent placeholder:text-muted/40"
                    />
                    <button
                      onClick={() => handleTestModel(llmConfig[key])}
                      disabled={modelTestStatus[llmConfig[key]] === 'testing'}
                      className="text-[10px] font-bold px-3 py-1 rounded border transition-colors disabled:opacity-50
                        border-border text-muted hover:text-bright hover:border-bright flex items-center gap-1"
                    >
                      <RefreshCw className="w-3 h-3" />
                      {modelTestStatus[llmConfig[key]] === 'testing' ? 'Testing…'
                        : modelTestStatus[llmConfig[key]] === 'ok' ? '✓ Responding'
                        : modelTestStatus[llmConfig[key]] === 'fail' ? '✗ Failed'
                        : 'Test Model'}
                    </button>
                  </div>
                ))}
              </div>

              {/* Fallback chain */}
              <div className="space-y-3">
                <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">
                  Fallback Chain <span className="font-normal normal-case text-muted/60">— cycled in order when rate-limited</span>
                </label>
                <div className="space-y-2">
                  {llmConfig.openrouter_fallback_models.length === 0 && (
                    <p className="text-xs text-muted italic">No fallback models configured.</p>
                  )}
                  {llmConfig.openrouter_fallback_models.map((m, i) => (
                    <div key={m} className="flex items-center gap-2">
                      <span className="text-[10px] font-bold text-muted/50 w-4 text-right shrink-0">{i + 1}</span>
                      <span className="flex-1 font-mono text-xs text-bright bg-surface border border-border rounded px-3 py-1">{m}</span>
                      <button
                        onClick={() => handleTestModel(m)}
                        disabled={modelTestStatus[m] === 'testing'}
                        className="text-[10px] text-muted hover:text-bright px-2 py-1 border border-border rounded hover:border-bright transition-colors disabled:opacity-50"
                      >
                        {modelTestStatus[m] === 'testing' ? '…'
                          : modelTestStatus[m] === 'ok' ? '✓'
                          : modelTestStatus[m] === 'fail' ? '✗'
                          : 'Test'}
                      </button>
                      <button
                        onClick={() => removeFallbackModel(m)}
                        className="text-danger/50 hover:text-danger p-1 rounded transition-colors"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>

                {/* Add model row */}
                <div className="flex gap-2 pt-1">
                  <select
                    value=""
                    onChange={(e) => { if (e.target.value) addFallbackModel(e.target.value); }}
                    className="bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
                  >
                    <option value="">+ Add from catalogue…</option>
                    {Object.entries(availableModels).map(([name, id]) => (
                      <option key={id} value={id}>{name} — {id}</option>
                    ))}
                  </select>
                  <input
                    type="text"
                    placeholder="or paste model ID"
                    value={customModelInput}
                    onChange={(e) => setCustomModelInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && addFallbackModel(customModelInput)}
                    className="flex-1 bg-surface border border-border rounded px-3 py-1.5 text-xs font-mono text-bright focus:outline-none focus:border-accent placeholder:text-muted/40"
                  />
                  <button
                    onClick={() => addFallbackModel(customModelInput)}
                    className="bg-accent/20 text-accent border border-accent/30 px-3 py-1.5 rounded hover:bg-accent/30 transition-colors"
                  >
                    <Plus className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <button
                onClick={handleSaveLlmConfig}
                disabled={llmSaveStatus === 'saving'}
                className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-4 py-1.5 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
              >
                {llmSaveStatus === 'saving' ? '…' : llmSaveStatus === 'saved' ? '✓ Saved — Applied Immediately' : llmSaveStatus === 'error' ? '✗ Error' : 'Save Model Config'}
              </button>
            </div>
          </section>

          {/* LLM Council Section */}
          <section className="panel overflow-hidden">
            <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
              <Shield className="w-4 h-4 mr-2 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">LLM Council</h3>
            </div>
            <div className="p-6 space-y-5">
              <p className="text-[11px] text-muted">
                The LLM Council reviews every factory request (pre-flight) and delivery (post-pipeline) using an independent LLM evaluation.
              </p>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">Council Reviews</label>
                  <select
                    value={councilConfig.council_enabled ? 'Enabled' : 'Disabled'}
                    onChange={(e) => setCouncilConfig(c => ({ ...c, council_enabled: e.target.value === 'Enabled' }))}
                    className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
                  >
                    <option>Enabled</option>
                    <option>Disabled</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">Strict Mode</label>
                  <select
                    value={councilConfig.council_strict_mode ? 'Strict (block on fail)' : 'Permissive (log only)'}
                    onChange={(e) => setCouncilConfig(c => ({ ...c, council_strict_mode: e.target.value.startsWith('Strict') }))}
                    className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
                  >
                    <option>Permissive (log only)</option>
                    <option>Strict (block on fail)</option>
                  </select>
                </div>
              </div>
              <button
                onClick={handleSaveCouncilConfig}
                disabled={councilSaveStatus === 'saving'}
                className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-4 py-1.5 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
              >
                {councilSaveStatus === 'saving' ? '...' : councilSaveStatus === 'saved' ? '✓ Saved' : councilSaveStatus === 'error' ? '✗ Error' : 'Save Council Config'}
              </button>
            </div>
          </section>

          {/* Phase Controls Section */}
          <section className="panel overflow-hidden">
            <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
              <SettingsIcon className="w-4 h-4 mr-2 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Phase Controls</h3>
            </div>
            <div className="divide-y divide-border">
              {PHASES.map((p) => (
                <div key={p} className="flex flex-col">
                  <button 
                    onClick={() => setExpandedPhase(expandedPhase === p ? null : p)}
                    className="flex items-center justify-between p-4 hover:bg-border/10 transition-colors"
                  >
                    <div className="flex items-center space-x-4">
                      <span className="text-xs font-mono text-accent font-bold">{p}</span>
                      <span className="text-sm font-medium text-bright">{PHASE_NAMES[p]}</span>
                    </div>
                    {expandedPhase === p ? <ChevronUp className="w-4 h-4 text-muted" /> : <ChevronDown className="w-4 h-4 text-muted" />}
                  </button>
                  {expandedPhase === p && (
                    <PhaseConfigPanel
                      phase={p}
                      config={phaseConfigs[p] || {}}
                      onSave={(cfg) => handleSavePhaseConfig(p, cfg)}
                    />
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* File Browser Section */}
          <section className="panel overflow-hidden">
            <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center justify-between">
              <div className="flex items-center">
                <FolderTree className="w-4 h-4 mr-2 text-accent" />
                <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Project File Browser</h3>
              </div>
              <div className="flex items-center space-x-3">
                <select
                  value={selectedRun}
                  onChange={(e) => handleRunSelect(e.target.value)}
                  className="bg-surface border border-border rounded px-3 py-1 text-[10px] font-bold text-muted uppercase focus:outline-none focus:border-accent"
                >
                  <option value="">Select Run</option>
                  {runs.map(r => (
                    <option key={r.run_id || r.id} value={r.run_id || r.id}>{r.project_name} ({r.run_id || r.id})</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-10 h-[500px]">
              <div className="col-span-3 border-r border-border overflow-y-auto custom-scrollbar p-4 space-y-4">
                {!selectedRun ? (
                  <div className="h-full flex flex-col items-center justify-center text-center p-4">
                    <Search className="w-8 h-8 text-muted/20 mb-2" />
                    <p className="text-[10px] text-muted uppercase font-bold">Select a factory run to browse files</p>
                  </div>
                ) : loadingFiles ? (
                  <div className="h-full flex items-center justify-center text-muted text-[10px] uppercase font-bold">Loading...</div>
                ) : Object.keys(runFiles).length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-center p-4">
                    <p className="text-[10px] text-muted uppercase font-bold">No files found for this run</p>
                  </div>
                ) : (
                  Object.entries(runFiles).map(([phase, files]) => (
                    <div key={phase} className="space-y-1">
                      <div className="text-[10px] font-bold text-muted uppercase tracking-tighter flex items-center">
                        <ChevronDown className="w-3 h-3 mr-1" /> {phase}
                      </div>
                      <div className="pl-4 space-y-1">
                        {files.map(filePath => {
                          const fileName = filePath.split('/').pop();
                          return (
                            <button
                              key={filePath}
                              onClick={() => handleFileClick(filePath)}
                              className={`w-full text-left px-2 py-1 rounded text-[11px] flex items-center transition-colors ${selectedFile === filePath ? 'bg-accent/20 text-accent font-bold' : 'text-bright/70 hover:bg-border/30'}`}
                            >
                              <FileCode className="w-3 h-3 mr-2 opacity-50" /> {fileName}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))
                )}
              </div>
              <div className="col-span-7 bg-[#0a0c10] overflow-hidden flex flex-col">
                 <div className="bg-border/10 px-4 py-2 border-b border-border flex justify-between items-center shrink-0">
                    <span className="text-[10px] font-mono text-muted uppercase tracking-widest">{selectedFile || 'No file selected'}</span>
                    <span className="text-[9px] font-mono text-success">READ ONLY</span>
                 </div>
                 <div className="flex-1 overflow-auto p-4 custom-scrollbar">
                    {fileContent ? (() => {
                      const ext = selectedFile?.split('.').pop()?.toLowerCase() || '';
                      const langMap = { js: 'javascript', ts: 'typescript', jsx: 'javascript', tsx: 'typescript', py: 'python', json: 'json', yml: 'yaml', yaml: 'yaml', md: 'markdown', sh: 'bash', css: 'css', html: 'html', sql: 'sql' };
                      const lang = `language-${langMap[ext] || 'plaintext'}`;
                      return <pre className="m-0"><code className={`${lang} font-mono text-sm leading-relaxed`}>{fileContent}</code></pre>;
                    })() : (
                      <div className="h-full flex items-center justify-center text-muted/20">
                        <FileCode className="w-16 h-16" />
                      </div>
                    )}
                 </div>
              </div>
            </div>
          </section>
        </div>

        <aside className="space-y-8">
          <section className="panel overflow-hidden">
            <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
              <Cpu className="w-4 h-4 mr-2 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">LLM Backend Status</h3>
            </div>
            <div>
              <StatusRow label="Anthropic API" status={health?.anthropic_available} detail={health?.anthropic_available ? 'Connected' : 'Not Configured'} />
              <StatusRow label="Gemini API" status={health?.gemini_available} detail="model: gemini-1.5-pro" />
              <StatusRow label="Ollama Local" status={health?.ollama_available} detail="localhost:11434" />
              <div className="bg-accent/5 p-4 flex items-center justify-between">
                 <span className="text-sm font-bold text-accent uppercase tracking-tighter">Active Primary Provider</span>
                 <span className="bg-accent text-white text-[10px] font-bold px-2 py-0.5 rounded uppercase">{health?.llm_provider || 'Gemini'}</span>
              </div>
            </div>
          </section>

          <section className="panel p-6">
            <div className="flex items-center mb-6">
              <BarChart3 className="w-4 h-4 mr-2 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Factory Stats</h3>
            </div>
            <div className="space-y-6">
               <div>
                  <div className="text-[10px] font-bold text-muted uppercase tracking-tighter mb-1">Total Runs</div>
                  <div className="text-2xl font-bold text-bright">{runs.length}</div>
               </div>
               <div>
                  <div className="text-[10px] font-bold text-muted uppercase tracking-tighter mb-1">Tokens Today</div>
                  <div className="text-2xl font-bold text-success">{costs.tokens_today || '—'}</div>
               </div>
               <div>
                  <div className="text-[10px] font-bold text-muted uppercase tracking-tighter mb-1">Avg Cost/Run</div>
                  <div className="text-2xl font-bold text-warning">${costs.avg_cost_per_run?.toFixed(2) || '2.45'}</div>
               </div>
            </div>
          </section>

          {/* SSO Configuration Section */}
          <section className="panel overflow-hidden">
            <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
              <Shield className="w-4 h-4 mr-2 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">SSO / SAML Configuration</h3>
              {ssoConfig?.configured && (
                <span className="ml-3 text-[10px] font-bold bg-success/20 text-success border border-success/30 px-2 py-0.5 rounded uppercase tracking-wider">Active</span>
              )}
            </div>
            <div className="p-6 space-y-4">
              {ssoConfig?.configured && (
                <div className="p-3 rounded-lg bg-success/5 border border-success/20 text-xs text-muted space-y-1">
                  <div><span className="font-bold text-bright">Entity ID: </span>{ssoConfig.idp_entity_id}</div>
                  <div><span className="font-bold text-bright">SSO URL: </span>{ssoConfig.idp_sso_url}</div>
                  <div><span className="font-bold text-bright">Certificate: </span>{ssoConfig.idp_cert_preview}</div>
                </div>
              )}
              <div className="space-y-3">
                <div>
                  <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">IdP Entity ID</label>
                  <input
                    type="text"
                    placeholder="https://idp.example.com/metadata"
                    value={ssoForm.idp_entity_id}
                    onChange={e => setSsoForm(f => ({ ...f, idp_entity_id: e.target.value }))}
                    className="w-full bg-surface border border-border rounded px-3 py-2 text-xs text-bright focus:outline-none focus:border-accent"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">IdP SSO URL</label>
                  <input
                    type="url"
                    placeholder="https://idp.example.com/sso"
                    value={ssoForm.idp_sso_url}
                    onChange={e => setSsoForm(f => ({ ...f, idp_sso_url: e.target.value }))}
                    className="w-full bg-surface border border-border rounded px-3 py-2 text-xs text-bright focus:outline-none focus:border-accent"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">X.509 Certificate (PEM, no headers)</label>
                  <textarea
                    rows={4}
                    placeholder="MIIDdDCCAlygAwIBAgIGA..."
                    value={ssoForm.idp_cert}
                    onChange={e => setSsoForm(f => ({ ...f, idp_cert: e.target.value }))}
                    className="w-full bg-surface border border-border rounded px-3 py-2 text-xs text-bright font-mono focus:outline-none focus:border-accent resize-none"
                  />
                </div>
              </div>
              <div className="flex items-center gap-3 pt-1">
                <button
                  onClick={async () => {
                    if (!ssoForm.idp_entity_id || !ssoForm.idp_sso_url || !ssoForm.idp_cert) return;
                    setSsoStatus('saving');
                    try {
                      const res = await api.client.put('/settings/sso', ssoForm);
                      setSsoConfig(c => ({ ...c, configured: true, idp_entity_id: ssoForm.idp_entity_id, idp_sso_url: ssoForm.idp_sso_url }));
                      setSsoStatus('saved');
                      setTimeout(() => setSsoStatus(null), 2500);
                    } catch { setSsoStatus('error'); setTimeout(() => setSsoStatus(null), 3000); }
                  }}
                  className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-3 py-1 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
                  disabled={ssoStatus === 'saving'}
                >
                  {ssoStatus === 'saving' ? '...' : ssoStatus === 'saved' ? '✓ Saved' : ssoStatus === 'error' ? '✗ Error' : 'Save SSO Config'}
                </button>
                {ssoConfig?.configured && (
                  <button
                    onClick={async () => {
                      if (!window.confirm('Remove SSO configuration? Users will no longer be able to sign in with SSO.')) return;
                      setSsoStatus('deleting');
                      try {
                        await api.client.delete('/settings/sso');
                        setSsoConfig({ configured: false });
                        setSsoForm({ idp_entity_id: '', idp_sso_url: '', idp_cert: '' });
                        setSsoStatus(null);
                      } catch { setSsoStatus('error'); setTimeout(() => setSsoStatus(null), 3000); }
                    }}
                    className="text-[10px] font-bold bg-danger/10 text-danger border border-danger/20 px-3 py-1 rounded uppercase tracking-wider hover:bg-danger/20 transition-colors"
                  >
                    {ssoStatus === 'deleting' ? '...' : 'Remove SSO'}
                  </button>
                )}
              </div>
            </div>
          </section>

          <section className="panel p-6">
            <div className="flex items-center mb-4">
              <Server className="w-4 h-4 mr-2 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Data Region</h3>
            </div>
            <p className="text-xs text-muted mb-4">Select where your organisation's data is processed and stored. Changing this affects compliance reporting.</p>
            <div className="space-y-3">
              <select
                value={dataRegion}
                onChange={e => setDataRegion(e.target.value)}
                className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent transition-colors"
              >
                <option value="global">Global (No Restriction)</option>
                <option value="eu">EU / EEA (GDPR)</option>
                <option value="us">United States</option>
                <option value="apac">Asia-Pacific</option>
                <option value="uk">United Kingdom</option>
              </select>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted">
                  {dataRegion === 'eu' && 'Data stays within EU/EEA boundaries (GDPR compliant)'}
                  {dataRegion === 'us' && 'Data processed in US data centres'}
                  {dataRegion === 'apac' && 'Data processed in Asia-Pacific region'}
                  {dataRegion === 'uk' && 'Data processed in UK (post-Brexit GDPR)'}
                  {dataRegion === 'global' && 'No geographic restriction — lowest latency routing'}
                </span>
                <button
                  onClick={handleSaveDataRegion}
                  disabled={regionSaveStatus === 'saving'}
                  className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-3 py-1 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
                >
                  {regionSaveStatus === 'saving' ? '...' : regionSaveStatus === 'saved' ? '✓ Saved' : regionSaveStatus === 'error' ? '✗ Error' : 'Save Region'}
                </button>
              </div>
            </div>
          </section>

          <section className="panel p-6 bg-accent/5 border-accent/20">
            <div className="flex items-center mb-6">
              <Info className="w-4 h-4 mr-2 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Version Info</h3>
            </div>
            <div className="space-y-2">
               <div className="flex justify-between text-xs">
                  <span className="text-muted">AetherOS Factory Core</span>
                  <span className="font-mono text-bright">v{health?.version || '1.0.0'}</span>
               </div>
               <div className="flex justify-between text-xs">
                  <span className="text-muted">Orchestrator</span>
                  <span className="font-mono text-bright">v1.2.1</span>
               </div>
               <div className="flex justify-between text-xs">
                  <span className="text-muted">UI Dashboard</span>
                  <span className="font-mono text-bright">v1.0.0</span>
               </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
};

export default Settings;
