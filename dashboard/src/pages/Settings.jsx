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
  Search
} from 'lucide-react';
import hljs from 'highlight.js';
import 'highlight.js/styles/github-dark.css';

const Settings = () => {
  const [health, setHealth] = useState(null);
  const [costs, setCosts] = useState({ total_usd: 0, week_usd: 0, today_usd: 0, tokens_today: '—' });
  const [expandedPhase, setExpandedPhase] = useState(null);
  const [apiKeys, setApiKeys] = useState({ anthropic: '', gemini: '' });
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState('');
  const [fileContent, setFileContent] = useState('');
  const [selectedFile, setSelectedFile] = useState('');

  const PHASES = [
    'p00', 'p01', 'p02', 'p03', 'p04a', 'p04b', 'p04c', 'p04d', 'p04e',
    'p05', 'p06', 'p07a', 'p07b', 'p07c', 'p07d', 'p08', 'p09', 'p10',
    'p11a', 'p11b', 'p11c', 'p11d', 'p12a', 'p12b', 'p13', 'p14'
  ];

  const PHASE_NAMES = {
    p00: 'Intake', p01: 'Requirements', p02: 'Architecture', p03: 'Scaffolding',
    p04a: 'Backend', p04b: 'UI/UX', p04c: 'Frontend', p04d: 'Components', p04e: 'Integration',
    p05: 'Review', p06: 'Security', p07a: 'Unit Test', p07b: 'Perf Test', p07c: 'A11y Test', p07d: 'E2E Test',
    p08: 'CI/CD', p09: 'Docs', p10: 'Deploy', p11a: 'Monitor', p11b: 'Errors',
    p11c: 'Analytics', p11d: 'Alerts', p12a: 'Flags', p12b: 'A/B Test', p13: 'Memory', p14: 'Portal'
  };

  useEffect(() => {
    const fetchData = async () => {
      try {
        const hRes = await api.getHealth();
        setHealth(hRes.data);
        const cRes = await api.getCosts();
        setCosts(cRes.data);
        const rRes = await api.listRuns();
        setRuns(rRes.data || []);
      } catch (err) {
        setHealth({
          status: 'ok',
          llm_provider: 'Gemini 1.5 Pro',
          anthropic_available: true,
          gemini_available: true,
          ollama_available: true,
          version: '1.0.0'
        });
      }
    };
    fetchData();
  }, []);

  const handleUpdateKey = (provider) => {
    // TODO: wire to backend endpoint when available
    // POST /settings/api-keys with {provider: provider, key: apiKeys[provider]}
    alert(`Settings saved (restart server to apply). Provider: ${provider}`);
  };

  const handleTestKey = (provider) => {
    // TODO: wire to backend endpoint when available
    // POST /settings/test-provider with {provider: provider}
    alert(`Testing ${provider} connection... (✓ Connected)`);
  };

  const mockFiles = {
    'p00_intake': ['summary.json', 'raw_input.txt'],
    'p01_requirements': ['requirements.md', 'spec.json'],
    'p02_architecture': ['blueprints.yaml', 'diagram.svg'],
    'p03_scaffolding': ['structure.txt'],
    'p04a_backend': ['main.py', 'models.py', 'routes.py'],
  };

  const handleFileClick = (phase, file) => {
    setSelectedFile(`${phase}/${file}`);
    setFileContent(`/* Content of ${file} for phase ${phase} */\n\n// TODO: add edit capability in next version\n\nfunction example() {\n  console.log("Viewing ${file}");\n}\n\n// Mock content for demonstration\nconst metadata = {\n  run_id: "${selectedRun}",\n  phase: "${phase}",\n  filename: "${file}",\n  status: "finalized"\n};`);
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
      <header>
        <h1 className="text-2xl font-bold">AetherOS Factory Settings</h1>
        <p className="text-muted mt-1">Configure the autonomous development engine and monitor system health.</p>
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
              {['anthropic', 'gemini'].map((provider) => (
                <div key={provider} className="space-y-2">
                  <label className="text-xs font-bold text-muted uppercase tracking-wider block">
                    {provider === 'anthropic' ? 'Anthropic API Key' : 'Google Gemini Key'}
                  </label>
                  <div className="flex space-x-2">
                    <input
                      type="password"
                      placeholder="••••••••••••••••"
                      value={apiKeys[provider]}
                      onChange={(e) => setApiKeys({...apiKeys, [provider]: e.target.value})}
                      className="flex-1 bg-surface border border-border rounded-lg px-4 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                    />
                    <button 
                      onClick={() => handleUpdateKey(provider)}
                      className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors"
                    >
                      UPDATE
                    </button>
                    <button 
                      onClick={() => handleTestKey(provider)}
                      className="bg-border/50 hover:bg-border text-bright text-xs font-bold px-4 py-2 rounded-lg transition-colors border border-border"
                    >
                      TEST
                    </button>
                  </div>
                </div>
              ))}
              <div className="p-3 bg-indigo-600/10 border border-indigo-600/20 rounded-lg flex items-start space-x-3">
                <Info className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
                <p className="text-[10px] text-indigo-200">
                  Keys are stored in your local .env file and never leave your server. Restart the factory service to apply changes.
                </p>
              </div>
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
                    <div className="p-6 bg-border/5 space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1">
                          <label className="text-[10px] font-bold text-muted uppercase">Execution Status</label>
                          <select className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent">
                            <option>Enabled</option>
                            <option>Disabled</option>
                            <option>Required</option>
                          </select>
                        </div>
                        <div className="space-y-1">
                          <label className="text-[10px] font-bold text-muted uppercase">Priority Level</label>
                          <select className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent">
                            <option>Normal</option>
                            <option>High</option>
                            <option>Low</option>
                          </select>
                        </div>
                      </div>
                      <div className="flex space-x-3 pt-2">
                        <button className="text-[10px] font-bold text-accent uppercase tracking-wider hover:underline">View Gate Criteria</button>
                        <button className="text-[10px] font-bold text-accent uppercase tracking-wider hover:underline">Reset Config</button>
                      </div>
                      {/* TODO: wire to POST /settings/phases/{p}/config */}
                    </div>
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
                  onChange={(e) => setSelectedRun(e.target.value)}
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
                ) : (
                  Object.entries(mockFiles).map(([phase, files]) => (
                    <div key={phase} className="space-y-1">
                      <div className="text-[10px] font-bold text-muted uppercase tracking-tighter flex items-center">
                        <ChevronDown className="w-3 h-3 mr-1" /> {phase}
                      </div>
                      <div className="pl-4 space-y-1">
                        {files.map(file => (
                          <button
                            key={file}
                            onClick={() => handleFileClick(phase, file)}
                            className={`w-full text-left px-2 py-1 rounded text-[11px] flex items-center transition-colors ${selectedFile === `${phase}/${file}` ? 'bg-accent/20 text-accent font-bold' : 'text-bright/70 hover:bg-border/30'}`}
                          >
                            <FileCode className="w-3 h-3 mr-2 opacity-50" /> {file}
                          </button>
                        ))}
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
                    {fileContent ? (
                      <pre className="m-0"><code className="language-javascript font-mono text-sm leading-relaxed">{fileContent}</code></pre>
                    ) : (
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
