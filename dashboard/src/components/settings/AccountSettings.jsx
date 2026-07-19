import React from 'react';
import { Key, BarChart3, Info, XCircle, Cpu, CheckCircle2 } from 'lucide-react';

// ── API Key Management Panel ───────────────────────────────────────────────────
export const ApiKeyPanel = ({
  apiKeys, setApiKeys,
  keyStatus, testStatus,
  orgKeys,
  onUpdateKey, onTestKey,
}) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
      <Key className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">API Key Management</h3>
    </div>
    <div className="p-6 space-y-6">
      {[
        { id: 'anthropic',  label: 'Anthropic API Key',             storeKey: 'anthropic'  },
        { id: 'gemini',     label: 'Google Gemini Key',             storeKey: 'google'     },
        { id: 'openrouter', label: 'OpenRouter Key (5 free models)', storeKey: 'openrouter' },
      ].map(({ id, label, storeKey }) => (
        <div key={id} className="space-y-2">
          <label className="text-xs font-bold text-muted uppercase tracking-wider flex items-center gap-2">
            {label}
            {orgKeys?.[storeKey] && <span className="text-[10px] text-emerald-400 font-bold normal-case tracking-normal">Org key active</span>}
          </label>
          <div className="flex space-x-2">
            <input
              type={apiKeys[id].length > 0 ? 'password' : 'text'}
              autoComplete="new-password"
              placeholder={id === 'anthropic' ? 'sk-ant-…' : id === 'gemini' ? 'AIza…' : 'sk-or-…'}
              value={apiKeys[id]}
              onChange={(e) => setApiKeys(k => ({ ...k, [id]: e.target.value }))}
              className="flex-1 bg-surface border border-border rounded-lg px-4 py-2 text-sm text-bright focus:outline-none focus:border-accent"
            />
            <button
              onClick={() => onUpdateKey(id)}
              disabled={keyStatus[id] === 'saving'}
              className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors min-w-[80px]"
            >
              {keyStatus[id] === 'saving' ? '...' : keyStatus[id] === 'saved' ? '✓ SAVED' : keyStatus[id] === 'error' ? '✗ ERROR' : 'UPDATE'}
            </button>
            <button
              onClick={() => onTestKey(id)}
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
          Keys are stored per-organisation in the database and never leave your server. Active immediately — no restart needed.
          When an org-specific key is saved it takes priority over the system default. &quot;Org key active&quot; means your org has its own dedicated key.
          OpenRouter provides free models including MiniMax M2.5, Llama 3.3 70B, Qwen3-Coder, and more.
        </p>
      </div>
    </div>
  </section>
);

// ── Plan & Limits Panel ────────────────────────────────────────────────────────
export const PlanLimitsPanel = ({ usageLoading, usageError, usageData }) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
      <BarChart3 className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Plan &amp; Limits</h3>
    </div>
    <div className="p-6">
      {usageLoading ? (
        <div className="space-y-4 animate-pulse">
          {[1,2,3,4,5].map(i => (
            <div key={i} className="space-y-1.5">
              <div className="h-3 bg-border/40 rounded w-1/3" />
              <div className="h-2 bg-border/30 rounded w-full" />
            </div>
          ))}
        </div>
      ) : usageError ? (
        <div className="flex items-center gap-2 text-sm text-danger py-2">
          <XCircle className="w-4 h-4 shrink-0" /> Unable to load usage data
        </div>
      ) : usageData ? (
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-muted uppercase tracking-wider">Current Plan</span>
            <span className="text-sm font-bold text-accent capitalize">{usageData.plan_name || usageData.plan || 'Free'}</span>
          </div>
          {usageData.projects_limit != null && (
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="font-semibold text-bright">Projects</span>
                <span className="text-muted font-mono">{usageData.projects_used ?? '?'} / {usageData.projects_limit === -1 ? 'Unlimited' : usageData.projects_limit}</span>
              </div>
              {usageData.projects_limit !== -1 && (
                <div className="w-full bg-border/30 rounded-full h-1.5 overflow-hidden">
                  <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.min(100, ((usageData.projects_used ?? 0) / usageData.projects_limit) * 100)}%` }} />
                </div>
              )}
            </div>
          )}
          {usageData.token_budget_monthly != null && (
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="font-semibold text-bright">Monthly Token Budget</span>
                <span className="text-muted font-mono">
                  {(usageData.tokens_used_monthly ?? 0).toLocaleString()} / {usageData.token_budget_monthly === -1 ? 'Unlimited' : usageData.token_budget_monthly.toLocaleString()}
                </span>
              </div>
              {usageData.token_budget_monthly !== -1 && (
                <div className="w-full bg-border/30 rounded-full h-1.5 overflow-hidden">
                  <div className="h-full rounded-full bg-success transition-all" style={{ width: `${Math.min(100, ((usageData.tokens_used_monthly ?? 0) / usageData.token_budget_monthly) * 100)}%` }} />
                </div>
              )}
            </div>
          )}
          {usageData.storage_limit_gb != null && (
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="font-semibold text-bright">File Storage</span>
                <span className="text-muted font-mono">
                  {(usageData.storage_used_gb ?? 0).toFixed(2)} GB / {usageData.storage_limit_gb === -1 ? 'Unlimited' : `${usageData.storage_limit_gb} GB`}
                </span>
              </div>
              {usageData.storage_limit_gb !== -1 && (
                <div className="w-full bg-border/30 rounded-full h-1.5 overflow-hidden">
                  <div className="h-full rounded-full bg-warning transition-all" style={{ width: `${Math.min(100, ((usageData.storage_used_gb ?? 0) / usageData.storage_limit_gb) * 100)}%` }} />
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted">No usage data available.</p>
      )}
    </div>
  </section>
);

// ── Status Row (helper used by LLM Backend Status panel) ─────────────────────
const StatusRow = ({ label, status, detail }) => (
  <div className="flex items-center justify-between p-4 border-b border-border last:border-0">
    <div className="flex items-center space-x-4">
      <div className={`w-2 h-2 rounded-full ${status ? 'bg-success' : 'bg-danger'}`} />
      <span className="text-sm font-medium text-bright">{label}</span>
    </div>
    <div className="flex items-center space-x-3">
      <span className="text-xs text-muted font-mono">{detail}</span>
      {status ? <CheckCircle2 className="w-4 h-4 text-success/50" /> : <XCircle className="w-4 h-4 text-danger/50" />}
    </div>
  </div>
);

// ── LLM Backend Status Panel (sidebar) ────────────────────────────────────────
export const LLMStatusPanel = ({ health, bedrockConfig }) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
      <Cpu className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">LLM Backend Status</h3>
    </div>
    <div>
      <StatusRow label="Anthropic API" status={health?.anthropic_available} detail={health?.anthropic_available ? 'Connected' : 'Not Configured'} />
      <StatusRow label="Gemini API" status={health?.gemini_available} detail="model: gemini-1.5-pro" />
      <StatusRow label="Ollama Local" status={health?.ollama_available} detail="localhost:11434" />
      <StatusRow
        label="AWS Bedrock"
        status={bedrockConfig.bedrock_enabled && bedrockConfig.aws_key_configured}
        detail={bedrockConfig.bedrock_enabled && bedrockConfig.aws_key_configured
          ? `${bedrockConfig.bedrock_model_heavy} · ${bedrockConfig.aws_region}`
          : bedrockConfig.bedrock_enabled ? 'No credentials' : 'Disabled'}
      />
      <div className="bg-accent/5 p-4 flex items-center justify-between">
        <span className="text-sm font-bold text-accent uppercase tracking-tighter">Active Primary Provider</span>
        <span className="bg-accent text-white text-[10px] font-bold px-2 py-0.5 rounded uppercase">
          {health?.llm_provider || bedrockConfig.primary_llm || 'openrouter'}
        </span>
      </div>
    </div>
  </section>
);

// ── Factory Stats Panel (sidebar) ─────────────────────────────────────────────
export const FactoryStatsPanel = ({ runs, costs }) => (
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
);

// ── Version Info Panel (sidebar) ─────────────────────────────────────────────
export const VersionInfoPanel = ({ health }) => (
  <section className="panel p-6 bg-accent/5 border-accent/20">
    <div className="flex items-center mb-4">
      <Info className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Version Info</h3>
    </div>
    <div className="space-y-2">
      <div className="flex justify-between text-xs"><span className="text-muted">AetherOS Factory Core</span><span className="font-mono text-bright">v{health?.version || '1.0.0'}</span></div>
      <div className="flex justify-between text-xs"><span className="text-muted">Orchestrator</span><span className="font-mono text-bright">v1.2.1</span></div>
      <div className="flex justify-between text-xs"><span className="text-muted">UI Dashboard</span><span className="font-mono text-bright">v1.0.0</span></div>
    </div>
  </section>
);
