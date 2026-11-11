import React, { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { api } from '../api';
import StorageWidget from '../components/StorageWidget';
import { useSettings } from '../contexts/SettingsContext';

// Extracted panel components (split for 600-line limit)
import { ApiKeyPanel, PlanLimitsPanel, LLMStatusPanel, FactoryStatsPanel, VersionInfoPanel } from '../components/settings/AccountSettings';
import { ModelConfigPanel, BedrockPanel, CouncilPanel, LangsmithPanel } from '../components/settings/LLMSettings';
import { SSOPanel, SCIMPanel } from '../components/settings/SecuritySettings';
import { AuditExportPanel, OrgConfigPanel, DataRegionPanel } from '../components/settings/OrgSettings';
import { PhaseControlsPanel, FileBrowserPanel } from '../components/settings/PhaseSettings';
import { PHASES, PHASE_NAMES } from '../components/project/projectConstants';

const Settings = () => {
  const { orgName, updateLlmConfig: ctxUpdateLlmConfig, reload: ctxReload } = useSettings();
  const location = useLocation();
  const ssoRef = useRef(null);

  useEffect(() => {
    if (location.pathname.endsWith('/sso') && ssoRef.current) {
      setTimeout(() => ssoRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' }), 300);
    }
  }, [location.pathname]);

  const [health, setHealth] = useState(null);
  const [costs, setCosts] = useState({ total_usd: 0, week_usd: 0, today_usd: 0, tokens_today: '—' });
  const [expandedPhase, setExpandedPhase] = useState(null);
  const [apiKeys, setApiKeys] = useState({ anthropic: '', gemini: '', openrouter: '' });
  const [keyStatus, setKeyStatus] = useState({ anthropic: null, gemini: null, openrouter: null });
  const [testStatus, setTestStatus] = useState({ anthropic: null, gemini: null, openrouter: null });
  const [orgKeys, setOrgKeys] = useState({ anthropic: false, google: false, openrouter: false });
  const [phaseConfigs, setPhaseConfigs] = useState({});
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState('');
  const [runFiles, setRunFiles] = useState({});
  const [fileContent, setFileContent] = useState('');
  const [selectedFile, setSelectedFile] = useState('');
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [councilConfig, setCouncilConfig] = useState({ council_enabled: true, council_strict_mode: false });
  const [councilSaveStatus, setCouncilSaveStatus] = useState(null);
  const [llmConfig, setLlmConfig] = useState({
    openrouter_heavy_model: 'minimax/minimax-m2.5:free',
    openrouter_light_model: 'meta-llama/llama-3.3-70b-instruct:free',
    openrouter_fallback_models: [],
  });
  const [availableModels, setAvailableModels] = useState([]);
  const [llmSaveStatus, setLlmSaveStatus] = useState(null);
  const [modelTestStatus, setModelTestStatus] = useState({});
  const [customModelInput, setCustomModelInput] = useState('');
  const [dataRegion, setDataRegion] = useState('global');
  const [regionSaveStatus, setRegionSaveStatus] = useState(null);
  const [langsmithConfig, setLangsmithConfig] = useState({ opt_in: false, api_key: '', project: 'aetheros-factory', api_key_set: false });
  const [langsmithSaveStatus, setLangsmithSaveStatus] = useState(null);
  const [bedrockConfig, setBedrockConfig] = useState({
    bedrock_enabled: false,
    aws_access_key_id: '',
    aws_secret_access_key: '',
    aws_region: 'us-east-1',
    bedrock_model_heavy: 'deepseek.v3.2',
    bedrock_model_light: 'google.gemma-3-27b-it',
    aws_key_configured: false,
    aws_secret_configured: false,
    aws_key_id_masked: '',
    primary_llm: 'openrouter',
  });
  const [bedrockSaveStatus, setBedrockSaveStatus] = useState(null);
  const [bedrockTestStatus, setBedrockTestStatus] = useState(null);
  const [bedrockTestResult, setBedrockTestResult] = useState(null);
  const [ssoConfig, setSsoConfig] = useState(null);
  const [ssoForm, setSsoForm] = useState({ idp_entity_id: '', idp_sso_url: '', idp_cert: '' });
  const [ssoStatus, setSsoStatus] = useState(null);
  const [orgConfig, setOrgConfig] = useState({ autonomous_mode: false });
  const [orgSaveStatus, setOrgSaveStatus] = useState(null);
  const [scimConfig, setScimConfig] = useState({ configured: false, token_masked: null, token_source: 'none' });
  const [scimRotateStatus, setScimRotateStatus] = useState(null);
  const [scimNewToken, setScimNewToken] = useState(null);
  const [deleteOrgStatus, setDeleteOrgStatus] = useState(null);
  const [deleteOrgInput, setDeleteOrgInput] = useState('');
  const [auditFromDate, setAuditFromDate] = useState('');
  const [auditToDate, setAuditToDate] = useState('');
  const [auditActionFilter, setAuditActionFilter] = useState('');
  const [auditExportStatus, setAuditExportStatus] = useState(null);
  const [usageData, setUsageData] = useState(null);
  const [usageLoading, setUsageLoading] = useState(true);
  const [usageError, setUsageError] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [hRes, cRes, rRes, pcRes, keyRes, ccRes, llmRes, modelsRes] = await Promise.allSettled([
          api.getHealth(), api.getCosts(), api.listRuns(), api.getPhaseConfigs(),
          api.getApiKeys(), api.getCouncilConfig(), api.getLlmConfig(), api.getAvailableModels(),
        ]);
        if (hRes.status === 'fulfilled') setHealth(hRes.value.data);
        if (cRes.status === 'fulfilled') setCosts(cRes.value.data);
        if (rRes.status === 'fulfilled') setRuns(rRes.value.data?.items ?? rRes.value.data ?? []);
        if (pcRes.status === 'fulfilled') {
          const cfgDict = {};
          (pcRes.value.data || []).forEach(c => { cfgDict[c.phase_name] = c; });
          setPhaseConfigs(cfgDict);
        }
        if (keyRes.status === 'fulfilled') {
          const kd = keyRes.value.data || {};
          setApiKeys({ anthropic: kd.anthropic || '', gemini: kd.google || '', openrouter: kd.openrouter || '' });
          if (kd.org_keys) setOrgKeys(kd.org_keys);
        }
        if (ccRes.status === 'fulfilled') setCouncilConfig(ccRes.value.data || { council_enabled: true, council_strict_mode: false });
        if (llmRes.status === 'fulfilled') {
          const d = llmRes.value.data || {};
          setLlmConfig({
            openrouter_heavy_model: d.openrouter_heavy_model || 'minimax/minimax-m2.5:free',
            openrouter_light_model: d.openrouter_light_model || 'mistralai/mistral-7b-instruct:free',
            openrouter_fallback_models: d.openrouter_fallback_models || [],
          });
          setBedrockConfig(prev => ({
            ...prev,
            bedrock_enabled: d.bedrock_enabled ?? prev.bedrock_enabled,
            aws_region: d.aws_region || prev.aws_region,
            bedrock_model_heavy: d.bedrock_model_heavy || prev.bedrock_model_heavy,
            bedrock_model_light: d.bedrock_model_light || prev.bedrock_model_light,
            aws_key_configured: d.aws_key_configured ?? prev.aws_key_configured,
            aws_secret_configured: d.aws_secret_configured ?? prev.aws_secret_configured,
            aws_key_id_masked: d.aws_key_id_masked || prev.aws_key_id_masked,
            primary_llm: d.primary_llm || prev.primary_llm,
          }));
        }
        if (modelsRes.status === 'fulfilled') setAvailableModels(modelsRes.value.data || []);

        try {
          const lsRes = await api.client.get('/settings/langsmith');
          setLangsmithConfig(c => ({ ...c, opt_in: lsRes.data.opt_in ?? false, api_key_set: lsRes.data.api_key_set ?? false, project: lsRes.data.project || 'aetheros-factory' }));
        } catch { /* optional section: keep its defaults */ }
        try {
          const ssoRes = await api.client.get('/settings/sso');
          setSsoConfig(ssoRes.data);
          if (ssoRes.data.configured) setSsoForm(f => ({ ...f, idp_entity_id: ssoRes.data.idp_entity_id || '', idp_sso_url: ssoRes.data.idp_sso_url || '' }));
        } catch { /* optional section: keep its defaults */ }
        try {
          const compRes = await api.client.get('/compliance/org-report');
          if (compRes.data?.data_region) setDataRegion(compRes.data.data_region.toLowerCase());
        } catch { /* optional section: keep its defaults */ }
        try {
          const orgRes = await api.client.get('/account/settings');
          if (orgRes.data?.autonomous_mode !== undefined) setOrgConfig(c => ({ ...c, autonomous_mode: !!orgRes.data.autonomous_mode }));
        } catch { /* optional section: keep its defaults */ }
        try {
          const scimRes = await api.client.get('/settings/scim');
          setScimConfig(scimRes.data);
        } catch { /* optional section: keep its defaults */ }
        try {
          const usageRes = await api.client.get('/orgs/me/usage');
          setUsageData(usageRes.data);
          setUsageError(false);
        } catch {
          setUsageError(true);
        } finally {
          setUsageLoading(false);
        }
      } catch (err) {
        console.warn('Settings fetch error:', err);
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
      const storeProvider = provider === 'gemini' ? 'google' : provider;
      setOrgKeys(ok => ({ ...ok, [storeProvider]: true }));
      ctxReload();
    } catch {
      setKeyStatus(s => ({ ...s, [provider]: 'error' }));
    }
  };

  const handleTestKey = async (provider) => {
    setTestStatus(s => ({ ...s, [provider]: 'testing' }));
    try {
      await api.testProvider(provider);
      setTestStatus(s => ({ ...s, [provider]: 'ok' }));
      setTimeout(() => setTestStatus(s => ({ ...s, [provider]: null })), 4000);
    } catch {
      setTestStatus(s => ({ ...s, [provider]: 'fail' }));
      setTimeout(() => setTestStatus(s => ({ ...s, [provider]: null })), 4000);
    }
  };

  const handleSavePhaseConfig = async (phase, config) => {
    try {
      await api.savePhaseConfig(phase, config);
    } catch (err) {
      console.warn('Failed to save phase config:', err);
    }
  };

  const handleSaveCouncilConfig = async () => {
    setCouncilSaveStatus('saving');
    try {
      await api.updateCouncilConfig(councilConfig);
      setCouncilSaveStatus('saved');
      setTimeout(() => setCouncilSaveStatus(null), 3000);
    } catch {
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

  const handleSaveBedrockConfig = async () => {
    setBedrockSaveStatus('saving');
    try {
      const payload = {
        primary_llm: bedrockConfig.bedrock_enabled ? 'bedrock' : 'openrouter',
        bedrock_enabled: bedrockConfig.bedrock_enabled,
        aws_region: bedrockConfig.aws_region,
        bedrock_model_heavy: bedrockConfig.bedrock_model_heavy,
        bedrock_model_light: bedrockConfig.bedrock_model_light,
      };
      if (bedrockConfig.aws_access_key_id.trim()) payload.aws_access_key_id = bedrockConfig.aws_access_key_id.trim();
      if (bedrockConfig.aws_secret_access_key.trim()) payload.aws_secret_access_key = bedrockConfig.aws_secret_access_key.trim();
      await api.updateLlmConfig(payload);
      ctxUpdateLlmConfig(payload);
      setBedrockConfig(prev => ({ ...prev, aws_access_key_id: '', aws_secret_access_key: '', aws_key_configured: prev.aws_key_configured || !!payload.aws_access_key_id, aws_secret_configured: prev.aws_secret_configured || !!payload.aws_secret_access_key, primary_llm: payload.primary_llm }));
      setBedrockSaveStatus('saved');
      setTimeout(() => setBedrockSaveStatus(null), 3000);
      ctxReload();
    } catch {
      setBedrockSaveStatus('error');
      setTimeout(() => setBedrockSaveStatus(null), 3000);
    }
  };

  const handleTestBedrock = async () => {
    setBedrockTestStatus('testing');
    setBedrockTestResult(null);
    try {
      const payload = { aws_region: bedrockConfig.aws_region, model_id: bedrockConfig.bedrock_model_heavy };
      if (bedrockConfig.aws_access_key_id.trim()) payload.aws_access_key_id = bedrockConfig.aws_access_key_id.trim();
      if (bedrockConfig.aws_secret_access_key.trim()) payload.aws_secret_access_key = bedrockConfig.aws_secret_access_key.trim();
      const res = await api.client.post('/settings/test-provider', { provider: 'bedrock' });
      setBedrockTestResult(res.data);
      setBedrockTestStatus(res.data?.success ? 'ok' : 'fail');
      setTimeout(() => setBedrockTestStatus(null), 8000);
    } catch (err) {
      setBedrockTestResult({ success: false, error: err.response?.data?.detail || err.message });
      setBedrockTestStatus('fail');
      setTimeout(() => setBedrockTestStatus(null), 8000);
    }
  };

  const handleTestModel = async (modelId) => {
    if (!modelId) return;
    setModelTestStatus(s => ({ ...s, [modelId]: 'testing' }));
    try {
      const res = await api.testModel(modelId);
      setModelTestStatus(s => ({ ...s, [modelId]: res.data?.success ? 'ok' : 'fail' }));
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

  const flattenTree = (items) => {
    const paths = [];
    for (const item of items || []) {
      if (item.type === 'file') paths.push(item.path);
      else if (item.type === 'directory' && item.children) paths.push(...flattenTree(item.children));
    }
    return paths;
  };

  const handleSaveLangsmith = async () => {
    setLangsmithSaveStatus('saving');
    try {
      const payload = { opt_in: langsmithConfig.opt_in, project: langsmithConfig.project };
      if (langsmithConfig.api_key) payload.api_key = langsmithConfig.api_key;
      await api.client.post('/settings/langsmith', payload);
      setLangsmithConfig(c => ({ ...c, api_key: '', api_key_set: c.api_key_set || !!langsmithConfig.api_key }));
      setLangsmithSaveStatus('saved');
      setTimeout(() => setLangsmithSaveStatus(null), 3000);
    } catch {
      setLangsmithSaveStatus('error');
      setTimeout(() => setLangsmithSaveStatus(null), 3000);
    }
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

  const handleSaveOrgConfig = async () => {
    setOrgSaveStatus('saving');
    try {
      await api.updateOrgSettings({ autonomous_mode: orgConfig.autonomous_mode });
      setOrgSaveStatus('saved');
      setTimeout(() => setOrgSaveStatus(null), 2500);
    } catch {
      setOrgSaveStatus('error');
      setTimeout(() => setOrgSaveStatus(null), 3000);
    }
  };

  const handleRotateScimToken = async () => {
    setScimRotateStatus('rotating');
    setScimNewToken(null);
    try {
      const res = await api.rotateScimToken();
      setScimNewToken(res.data.token);
      const cfgRes = await api.getScimConfig();
      setScimConfig(cfgRes.data);
      setScimRotateStatus('done');
    } catch {
      setScimRotateStatus('error');
      setTimeout(() => setScimRotateStatus(null), 3000);
    }
  };

  const handleAuditExport = async () => {
    setAuditExportStatus('exporting');
    try {
      const token = localStorage.getItem('aether_token');
      const params = new URLSearchParams();
      if (auditFromDate) params.set('from_date', auditFromDate);
      if (auditToDate) params.set('to_date', auditToDate);
      if (auditActionFilter.trim()) params.set('action', auditActionFilter.trim());
      const url = `/api/admin/audit-logs/export?${params.toString()}`;
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) { const text = await res.text(); throw new Error(text || res.statusText); }
      const blob = await res.blob();
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.download = `audit-logs_${auditFromDate || 'all'}_${auditToDate || 'now'}.csv`;
      a.href = objUrl;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(objUrl); a.remove(); }, 1000);
      setAuditExportStatus('done');
      setTimeout(() => setAuditExportStatus(null), 3000);
    } catch (err) {
      console.warn('Audit export failed:', err);
      setAuditExportStatus('error');
      setTimeout(() => setAuditExportStatus(null), 4000);
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
      const tree = res.data?.tree || [];
      const filePaths = flattenTree(tree);
      const grouped = {};
      filePaths.forEach(path => {
        const parts = path.split('/');
        const group = parts.length > 1 ? parts[0] : 'root';
        if (!grouped[group]) grouped[group] = [];
        grouped[group].push(path);
      });
      setRunFiles(grouped);
    } catch {
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
      const payload = res.data;
      if (payload?.type === 'image') setFileContent('// Image file — cannot preview');
      else setFileContent(payload?.content || '// (empty file)');
    } catch {
      setFileContent(`// Could not load file: ${filePath}`);
    }
  };

  const handleDeleteOrg = async () => {
    setDeleteOrgStatus('deleting');
    try {
      await api.client.delete('/account/org');
      setTimeout(() => { api.clearToken(); window.location.href = '/login'; }, 2000);
      setDeleteOrgStatus('done');
    } catch {
      setDeleteOrgStatus('error');
      setTimeout(() => setDeleteOrgStatus(null), 3000);
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-12 pb-20">
      <header className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold">AetherOS Factory Settings</h1>
          <p className="text-muted mt-1">Manage your API keys and configure which AI models power your pipeline.</p>
        </div>
        <StorageWidget />
      </header>

      <div className="grid grid-cols-3 gap-8">
        <div className="col-span-2 space-y-8">
          {/* Account panels (extracted) */}
          <ApiKeyPanel
            apiKeys={apiKeys} setApiKeys={setApiKeys}
            keyStatus={keyStatus} testStatus={testStatus}
            orgKeys={orgKeys}
            onUpdateKey={handleUpdateKey} onTestKey={handleTestKey}
          />
          <PlanLimitsPanel
            usageLoading={usageLoading} usageError={usageError} usageData={usageData}
          />

          {/* LLM Settings panels (extracted) */}
          <ModelConfigPanel
            llmConfig={llmConfig} setLlmConfig={setLlmConfig}
            availableModels={availableModels}
            llmSaveStatus={llmSaveStatus}
            onSave={handleSaveLlmConfig}
            modelTestStatus={modelTestStatus}
            onTestModel={handleTestModel}
            customModelInput={customModelInput}
            setCustomModelInput={setCustomModelInput}
            onAddFallback={addFallbackModel}
            onRemoveFallback={removeFallbackModel}
          />
          <BedrockPanel
            bedrockConfig={bedrockConfig} setBedrockConfig={setBedrockConfig}
            bedrockSaveStatus={bedrockSaveStatus}
            bedrockTestStatus={bedrockTestStatus}
            bedrockTestResult={bedrockTestResult}
            onSave={handleSaveBedrockConfig}
            onTest={handleTestBedrock}
          />
          <CouncilPanel
            councilConfig={councilConfig} setCouncilConfig={setCouncilConfig}
            councilSaveStatus={councilSaveStatus}
            onSave={handleSaveCouncilConfig}
          />
          <LangsmithPanel
            langsmithConfig={langsmithConfig} setLangsmithConfig={setLangsmithConfig}
            langsmithSaveStatus={langsmithSaveStatus}
            onSave={handleSaveLangsmith}
          />
          <PhaseControlsPanel
            PHASES={PHASES} PHASE_NAMES={PHASE_NAMES}
            phaseConfigs={phaseConfigs}
            expandedPhase={expandedPhase} setExpandedPhase={setExpandedPhase}
            onSavePhaseConfig={handleSavePhaseConfig}
          />
          <FileBrowserPanel
            runs={runs} selectedRun={selectedRun} onRunSelect={handleRunSelect}
            runFiles={runFiles} loadingFiles={loadingFiles}
            selectedFile={selectedFile} fileContent={fileContent}
            onFileClick={handleFileClick}
          />
        </div>

        <aside className="space-y-8">
          {/* Status/stats panels (extracted) */}
          <LLMStatusPanel health={health} bedrockConfig={bedrockConfig} />
          <FactoryStatsPanel runs={runs} costs={costs} />

          {/* Security panels (extracted) */}
          <SSOPanel
            ssoRef={ssoRef}
            ssoConfig={ssoConfig} setSsoConfig={setSsoConfig}
            ssoForm={ssoForm} setSsoForm={setSsoForm}
            ssoStatus={ssoStatus} setSsoStatus={setSsoStatus}
          />
          <SCIMPanel
            scimConfig={scimConfig}
            scimRotateStatus={scimRotateStatus}
            scimNewToken={scimNewToken} setScimNewToken={setScimNewToken}
            onRotate={handleRotateScimToken}
          />

          {/* Org panels (extracted) */}
          <AuditExportPanel
            auditFromDate={auditFromDate} setAuditFromDate={setAuditFromDate}
            auditToDate={auditToDate} setAuditToDate={setAuditToDate}
            auditActionFilter={auditActionFilter} setAuditActionFilter={setAuditActionFilter}
            auditExportStatus={auditExportStatus}
            onExport={handleAuditExport}
          />
          <OrgConfigPanel
            orgConfig={orgConfig} setOrgConfig={setOrgConfig}
            orgSaveStatus={orgSaveStatus} onSave={handleSaveOrgConfig}
            deleteOrgStatus={deleteOrgStatus} setDeleteOrgStatus={setDeleteOrgStatus}
            deleteOrgInput={deleteOrgInput} setDeleteOrgInput={setDeleteOrgInput}
            orgName={orgName}
            onDeleteOrg={handleDeleteOrg}
          />
          <DataRegionPanel
            dataRegion={dataRegion} setDataRegion={setDataRegion}
            regionSaveStatus={regionSaveStatus} onSave={handleSaveDataRegion}
          />
          <VersionInfoPanel health={health} />
        </aside>
      </div>
    </div>
  );
};

export default Settings;
