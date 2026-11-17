import React from 'react';
import {
  Sliders, Server, Shield, BarChart3,
  Plus, Trash2, RefreshCw, Info,
} from 'lucide-react';

// ── Model Configuration Panel ─────────────────────────────────────────────────
export const ModelConfigPanel = ({
  llmConfig, setLlmConfig,
  availableModels,
  llmSaveStatus,
  onSave,
  modelTestStatus,
  onTestModel,
  customModelInput,
  setCustomModelInput,
  onAddFallback,
  onRemoveFallback,
}) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
      <Sliders className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Model Configuration</h3>
    </div>
    <div className="p-6 space-y-6">
      <p className="text-[11px] text-muted">
        These are OpenRouter model IDs, used when OpenRouter is the primary provider and as the fallback chain (with Bedrock as primary they are not used). Copy any model ID from{' '}
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
              value={availableModels.find(m => m.id === llmConfig[key]) ? llmConfig[key] : '__custom__'}
              onChange={(e) => {
                if (e.target.value !== '__custom__')
                  setLlmConfig(c => ({ ...c, [key]: e.target.value }));
              }}
              className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
            >
              {availableModels.map(m => (
                <option
                  key={m.id}
                  value={m.id}
                  disabled={!m.plan_allowed}
                  title={!m.plan_allowed ? 'Upgrade to Pro to use this model' : undefined}
                  style={!m.plan_allowed ? { color: '#6b7280' } : undefined}
                >
                  {m.name}{m.plan_allowed ? '' : ' (Pro only)'}
                </option>
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
              onClick={() => onTestModel(llmConfig[key])}
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
                onClick={() => onTestModel(m)}
                disabled={modelTestStatus[m] === 'testing'}
                className="text-[10px] text-muted hover:text-bright px-2 py-1 border border-border rounded hover:border-bright transition-colors disabled:opacity-50"
              >
                {modelTestStatus[m] === 'testing' ? '…'
                  : modelTestStatus[m] === 'ok' ? '✓'
                  : modelTestStatus[m] === 'fail' ? '✗'
                  : 'Test'}
              </button>
              <button onClick={() => onRemoveFallback(m)} className="text-danger/50 hover:text-danger p-1 rounded transition-colors">
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>

        {/* Add model row */}
        <div className="flex gap-2 pt-1">
          <select
            value=""
            onChange={(e) => { if (e.target.value) onAddFallback(e.target.value); }}
            className="bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
          >
            <option value="">+ Add from catalogue…</option>
            {availableModels.map(model => (
              <option
                key={model.id}
                value={model.id}
                disabled={!model.plan_allowed}
                title={!model.plan_allowed ? 'Upgrade to Pro to use this model' : undefined}
                style={!model.plan_allowed ? { color: '#6b7280' } : undefined}
              >
                {model.name} — {model.id}{model.plan_allowed ? '' : ' (Pro only)'}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="or paste model ID"
            value={customModelInput}
            onChange={(e) => setCustomModelInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onAddFallback(customModelInput)}
            className="flex-1 bg-surface border border-border rounded px-3 py-1.5 text-xs font-mono text-bright focus:outline-none focus:border-accent placeholder:text-muted/40"
          />
          <button
            onClick={() => onAddFallback(customModelInput)}
            className="bg-accent/20 text-accent border border-accent/30 px-3 py-1.5 rounded hover:bg-accent/30 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <button
        onClick={onSave}
        disabled={llmSaveStatus === 'saving'}
        className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-4 py-1.5 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
      >
        {llmSaveStatus === 'saving' ? '…' : llmSaveStatus === 'saved' ? '✓ Saved — Applied Immediately' : llmSaveStatus === 'error' ? '✗ Error' : 'Save Model Config'}
      </button>
    </div>
  </section>
);

// ── AWS Bedrock Panel ──────────────────────────────────────────────────────────
export const BedrockPanel = ({
  bedrockConfig, setBedrockConfig,
  bedrockSaveStatus,
  bedrockTestStatus,
  bedrockTestResult,
  onSave,
  onTest,
}) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center justify-between">
      <div className="flex items-center">
        <Server className="w-4 h-4 mr-2 text-accent" />
        <h3 className="text-xs font-bold text-muted uppercase tracking-widest">AWS Bedrock — Native Cloud LLMs</h3>
      </div>
      <span className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase ${bedrockConfig.bedrock_enabled && bedrockConfig.primary_llm === 'bedrock' ? 'bg-green-500/20 text-green-400 border border-green-500/30' : 'bg-surface text-muted border border-border'}`}>
        {bedrockConfig.bedrock_enabled && bedrockConfig.primary_llm === 'bedrock' ? '● Active Primary' : '○ Not Active'}
      </span>
    </div>
    <div className="p-6 space-y-6">
      <p className="text-[11px] text-muted">
        Use AWS Bedrock to run Claude, Nova, Llama, and other models directly billed to your AWS account credits.
        Requires a valid AWS IAM user with <span className="font-mono text-bright">bedrock:InvokeModel</span> permission.
        Enable model access in the{' '}
        <span className="font-mono text-accent">AWS Console → Bedrock → Model access</span> page first.
      </p>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">Bedrock Enabled</label>
          <select
            value={bedrockConfig.bedrock_enabled ? 'Enabled' : 'Disabled'}
            onChange={(e) => setBedrockConfig(c => ({ ...c, bedrock_enabled: e.target.value === 'Enabled' }))}
            className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
          >
            <option>Enabled</option>
            <option>Disabled</option>
          </select>
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">Use as Primary Provider</label>
          <div className="flex items-center gap-2 h-[34px]">
            <input
              type="checkbox"
              id="bedrock-primary"
              checked={bedrockConfig.bedrock_enabled && bedrockConfig.primary_llm === 'bedrock'}
              onChange={(e) => setBedrockConfig(c => ({
                ...c,
                bedrock_enabled: e.target.checked ? true : c.bedrock_enabled,
                primary_llm: e.target.checked ? 'bedrock' : 'openrouter',
              }))}
              className="w-4 h-4 accent-[var(--color-accent)] cursor-pointer"
            />
            <label htmlFor="bedrock-primary" className="text-xs text-bright cursor-pointer">
              Set Bedrock as primary LLM
            </label>
          </div>
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">AWS Credentials</label>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-[10px] text-muted">Access Key ID {bedrockConfig.aws_key_configured && <span className="text-green-400">✓ configured</span>}</label>
            <input
              type="text"
              placeholder={bedrockConfig.aws_key_id_masked || 'AKIA…'}
              value={bedrockConfig.aws_access_key_id}
              onChange={(e) => setBedrockConfig(c => ({ ...c, aws_access_key_id: e.target.value }))}
              className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs font-mono text-bright focus:outline-none focus:border-accent placeholder:text-muted/40"
            />
          </div>
          <div className="space-y-1">
            <label className="text-[10px] text-muted">Secret Access Key {bedrockConfig.aws_secret_configured && <span className="text-green-400">✓ configured</span>}</label>
            <input
              type="password"
              placeholder={bedrockConfig.aws_secret_configured ? '••••••••••••••••' : 'Enter secret key…'}
              value={bedrockConfig.aws_secret_access_key}
              onChange={(e) => setBedrockConfig(c => ({ ...c, aws_secret_access_key: e.target.value }))}
              className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs font-mono text-bright focus:outline-none focus:border-accent placeholder:text-muted/40"
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">AWS Region</label>
          <select
            value={bedrockConfig.aws_region}
            onChange={(e) => setBedrockConfig(c => ({ ...c, aws_region: e.target.value }))}
            className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
          >
            <option value="us-east-1">us-east-1 (N. Virginia)</option>
            <option value="us-west-2">us-west-2 (Oregon)</option>
            <option value="eu-west-1">eu-west-1 (Ireland)</option>
            <option value="ap-southeast-1">ap-southeast-1 (Singapore)</option>
            <option value="ap-northeast-1">ap-northeast-1 (Tokyo)</option>
            <option value="ap-south-1">ap-south-1 (Mumbai)</option>
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">Heavy Model</label>
          <select
            value={bedrockConfig.bedrock_model_heavy}
            onChange={(e) => setBedrockConfig(c => ({ ...c, bedrock_model_heavy: e.target.value }))}
            className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs font-mono text-bright focus:outline-none focus:border-accent"
          >
            <option value="deepseek.v3.2">DeepSeek V3.2 ✓ Works</option>
            <option value="mistral.devstral-2-123b">Mistral Devstral 123B ✓ Works</option>
            <option value="mistral.mistral-large-3-675b-instruct">Mistral Large 675B ✓ Works</option>
            <option value="google.gemma-3-27b-it">Gemma 3 27B IT ✓ Works</option>
            <option value="us.meta.llama3-3-70b-instruct-v1:0">Llama 3.3 70B (us) ✓ Works</option>
            <option value="meta.llama3-70b-instruct-v1:0">Llama 3 70B ✓ Works</option>
            <option value="us.amazon.nova-pro-v1:0">Amazon Nova Pro ✓ Works</option>
            <option value="amazon.nova-pro-v1:0">Amazon Nova Pro (direct)</option>
            <option value="us.anthropic.claude-sonnet-4-6">Claude Sonnet 4.6 (us)</option>
            <option value="us.anthropic.claude-opus-4-7">Claude Opus 4.7 (us)</option>
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">Light Model</label>
          <select
            value={bedrockConfig.bedrock_model_light}
            onChange={(e) => setBedrockConfig(c => ({ ...c, bedrock_model_light: e.target.value }))}
            className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs font-mono text-bright focus:outline-none focus:border-accent"
          >
            <option value="google.gemma-3-27b-it">Gemma 3 27B IT ✓ Works</option>
            <option value="google.gemma-3-12b-it">Gemma 3 12B IT ✓ Works</option>
            <option value="us.meta.llama3-3-70b-instruct-v1:0">Llama 3.3 70B (us) ✓ Works</option>
            <option value="meta.llama3-70b-instruct-v1:0">Llama 3 70B ✓ Works</option>
            <option value="meta.llama3-8b-instruct-v1:0">Llama 3 8B ✓ Works</option>
            <option value="amazon.nova-lite-v1:0">Amazon Nova Lite ✓ Works</option>
            <option value="us.anthropic.claude-haiku-4-5-20251001-v1:0">Claude Haiku 4.5 (us)</option>
          </select>
        </div>
      </div>

      {bedrockTestResult && (
        <div className={`rounded border px-4 py-3 text-xs space-y-1 ${bedrockTestResult.success ? 'bg-green-500/10 border-green-500/30 text-green-300' : 'bg-red-500/10 border-red-500/30 text-red-300'}`}>
          {bedrockTestResult.success ? (
            <>
              <p className="font-bold">✓ Bedrock Connected — {bedrockTestResult.model}</p>
              <p>Response: <span className="font-mono">{bedrockTestResult.response}</span></p>
              <p className="text-muted">Tokens: {bedrockTestResult.tokens?.input} in / {bedrockTestResult.tokens?.output} out · Region: {bedrockTestResult.region}</p>
            </>
          ) : (
            <>
              <p className="font-bold">✗ Bedrock Test Failed</p>
              <p className="font-mono text-[10px] break-all">{bedrockTestResult.error}</p>
              {bedrockTestResult.hint && <p className="text-yellow-300">{bedrockTestResult.hint}</p>}
            </>
          )}
        </div>
      )}

      <div className="flex gap-3">
        <button
          onClick={onTest}
          disabled={bedrockTestStatus === 'testing'}
          className="text-[10px] font-bold px-4 py-1.5 rounded border transition-colors disabled:opacity-50
            border-border text-muted hover:text-bright hover:border-bright flex items-center gap-1"
        >
          <RefreshCw className="w-3 h-3" />
          {bedrockTestStatus === 'testing' ? 'Testing…'
            : bedrockTestStatus === 'ok' ? '✓ Connected'
            : bedrockTestStatus === 'fail' ? '✗ Failed'
            : 'Test Bedrock'}
        </button>
        <button
          onClick={onSave}
          disabled={bedrockSaveStatus === 'saving'}
          className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-4 py-1.5 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
        >
          {bedrockSaveStatus === 'saving' ? '…'
            : bedrockSaveStatus === 'saved' ? '✓ Saved — Active'
            : bedrockSaveStatus === 'error' ? '✗ Error'
            : 'Save & Activate Bedrock'}
        </button>
      </div>
    </div>
  </section>
);

// ── LLM Council Panel ──────────────────────────────────────────────────────────
export const CouncilPanel = ({ councilConfig, setCouncilConfig, councilSaveStatus, onSave }) => (
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
        onClick={onSave}
        disabled={councilSaveStatus === 'saving'}
        className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-4 py-1.5 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
      >
        {councilSaveStatus === 'saving' ? '...' : councilSaveStatus === 'saved' ? '✓ Saved' : councilSaveStatus === 'error' ? '✗ Error' : 'Save Council Config'}
      </button>
    </div>
  </section>
);

// ── LangSmith / Observability Panel ───────────────────────────────────────────
export const LangsmithPanel = ({ langsmithConfig, setLangsmithConfig, langsmithSaveStatus, onSave }) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
      <BarChart3 className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Observability — LangSmith Tracing</h3>
      {langsmithConfig.opt_in && (
        <span className="ml-3 text-[10px] font-bold bg-success/20 text-success border border-success/30 px-2 py-0.5 rounded uppercase tracking-wider">Opt-in Active</span>
      )}
    </div>
    <div className="p-6 space-y-5">
      <p className="text-[11px] text-muted">
        LangSmith traces every LLM call through the factory pipeline. Enabling this sends structured traces to your LangSmith workspace. Explicit opt-in is required — your API key alone does not enable tracing.
      </p>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">Tracing Consent</label>
          <select
            value={langsmithConfig.opt_in ? 'Enabled' : 'Disabled'}
            onChange={(e) => setLangsmithConfig(c => ({ ...c, opt_in: e.target.value === 'Enabled' }))}
            className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
          >
            <option>Disabled</option>
            <option>Enabled</option>
          </select>
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">LangChain Project</label>
          <input
            type="text"
            placeholder="aetheros-factory"
            value={langsmithConfig.project}
            onChange={(e) => setLangsmithConfig(c => ({ ...c, project: e.target.value }))}
            className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs font-mono text-bright focus:outline-none focus:border-accent"
          />
        </div>
      </div>
      <div className="space-y-2">
        <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">
          LangSmith API Key
          {langsmithConfig.api_key_set && <span className="ml-2 text-success font-normal normal-case">— key on file</span>}
        </label>
        <input
          type="password"
          autoComplete="new-password"
          placeholder={langsmithConfig.api_key_set ? '••••••••••••••••  (key saved)' : 'ls-...'}
          value={langsmithConfig.api_key}
          onChange={(e) => setLangsmithConfig(c => ({ ...c, api_key: e.target.value }))}
          className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
        />
      </div>
      <div className="flex items-center gap-4">
        <button
          onClick={onSave}
          disabled={langsmithSaveStatus === 'saving'}
          className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-4 py-1.5 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
        >
          {langsmithSaveStatus === 'saving' ? '...' : langsmithSaveStatus === 'saved' ? '✓ Saved & Active' : langsmithSaveStatus === 'error' ? '✗ Error' : 'Save Observability Config'}
        </button>
        <p className="text-[10px] text-muted">Changes apply immediately — no restart required.</p>
      </div>
    </div>
  </section>
);
