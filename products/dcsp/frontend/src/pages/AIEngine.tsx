import { useState, useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Cpu, Key, CheckCircle2, XCircle, Loader2,
  ChevronRight, Zap, DollarSign, Globe, AlertCircle
} from 'lucide-react';
import api from '../lib/api';

interface ProviderInfo {
  provider: string;
  icon: string;
  models: ModelInfo[];
  is_free_available: boolean;
  error?: string;
}

interface ModelInfo {
  id: string;
  name: string;
  context_length?: number;
  pricing?: { prompt: string; completion: string };
  is_free: boolean;
  speed: 'fast' | 'medium' | 'slow';
  capability: 'code' | 'general';
}

type KeyStatus = 'idle' | 'detecting' | 'valid' | 'invalid';

// Detect provider from key format without revealing vendor names in UI messaging
function detectProviderHint(key: string): string {
  if (!key.trim()) return '';
  if (key.startsWith('sk-ant-'))          return 'anthropic';
  if (key.startsWith('sk-or-v1-'))        return 'openrouter';
  if (key.startsWith('sk-proj-') || (key.startsWith('sk-') && key.length > 40 && !key.startsWith('sk-ant') && !key.startsWith('sk-or')))
                                          return 'openai';
  if (key.startsWith('gsk_'))             return 'gemini';
  if (key.startsWith('AKIA'))             return 'bedrock';
  if (key.startsWith('http://') || key.startsWith('https://')) return 'ollama';
  if (key.length > 60)                    return 'openrouter'; // guess
  return '';
}

const AIEngine = () => {
  const qc = useQueryClient();
  const [apiKey, setApiKey] = useState('');
  const [awsSecret, setAwsSecret] = useState('');
  const [awsRegion, setAwsRegion] = useState('us-east-1');
  const [keyStatus, setKeyStatus] = useState<KeyStatus>('idle');
  const [providerInfo, setProviderInfo] = useState<ProviderInfo | null>(null);
  const [selectedModel, setSelectedModel] = useState('');
  const [detectionError, setDetectionError] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const isAws = detectProviderHint(apiKey) === 'bedrock';

  // Fetch current config
  const { data: currentConfig } = useQuery({
    queryKey: ['llm-config'],
    queryFn: () => api.get('/api/llm/config').then(r => r.data).catch(() => null),
  });

  useEffect(() => {
    if (currentConfig?.api_key_hint) {
      setKeyStatus('valid');
      setSelectedModel(currentConfig.model_id ?? '');
    }
  }, [currentConfig]);

  // Auto-detect on key change
  useEffect(() => {
    if (!apiKey.trim()) { setKeyStatus('idle'); setProviderInfo(null); return; }
    setKeyStatus('detecting');
    setDetectionError('');
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void (async () => {
      try {
        const body: Record<string, string> = { api_key: apiKey };
        if (isAws) { body.aws_secret = awsSecret; body.aws_region = awsRegion; }
        const res = await api.post('/api/llm/detect', body);
        setProviderInfo(res.data);
        setKeyStatus('valid');
        const models: ModelInfo[] = res.data.models ?? [];
        const freeModel = models.find(m => m.is_free);
        setSelectedModel(freeModel?.id ?? models[0]?.id ?? '');
      } catch (e: unknown) {
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Could not validate key';
        setDetectionError(msg);
        setKeyStatus('invalid');
        setProviderInfo(null);
      }
      })();
    }, 600);
  }, [apiKey, awsSecret, awsRegion]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const body: Record<string, string> = { api_key: apiKey, model_id: selectedModel };
      if (isAws) { body.aws_secret = awsSecret; body.aws_region = awsRegion; }
      return api.post('/api/llm/configure', body);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['llm-config'] }),
  });

  const speedColor = { fast: 'text-success', medium: 'text-warning', slow: 'text-slate-500' };
  const freeModels = providerInfo?.models.filter(m => m.is_free) ?? [];
  const paidModels = providerInfo?.models.filter(m => !m.is_free) ?? [];

  return (
    <div className="max-w-2xl space-y-7">
      <div>
        <h2 className="text-xl font-bold text-white">AI Engine</h2>
        <p className="text-slate-500 text-xs mt-0.5">Connect any AI provider to power patch generation.</p>
      </div>

      {/* Current status */}
      {currentConfig?.provider && (
        <div className="bg-success/5 border border-success/20 rounded-lg px-4 py-3 flex items-center gap-3">
          <CheckCircle2 size={16} className="text-success shrink-0" />
          <div>
            <p className="text-success text-sm font-semibold">Active: {currentConfig.provider}</p>
            <p className="text-slate-400 text-xs">{currentConfig.model_id}</p>
          </div>
        </div>
      )}

      {/* API Key input */}
      <div className="bg-surface border border-border rounded-lg p-6 space-y-5">
        <div className="flex items-center gap-2 mb-1">
          <Key size={15} className="text-slate-500" />
          <span className="text-white font-semibold text-sm">API Key</span>
        </div>

        <div>
          <label className="block text-xs text-slate-500 mb-1.5">
            Paste your API key — provider is detected automatically
          </label>
          <div className="relative">
            <input
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder="Enter API key…"
              className="w-full bg-background border border-border rounded-md px-3 py-2.5 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-accent pr-10"
            />
            <div className="absolute right-3 top-1/2 -translate-y-1/2">
              {keyStatus === 'detecting' && <Loader2 size={15} className="text-slate-500 animate-spin" />}
              {keyStatus === 'valid'     && <CheckCircle2 size={15} className="text-success" />}
              {keyStatus === 'invalid'   && <XCircle size={15} className="text-error" />}
            </div>
          </div>
          {detectionError && (
            <p className="text-error text-xs mt-1.5 flex items-center gap-1">
              <AlertCircle size={11} /> {detectionError}
            </p>
          )}
        </div>

        {/* AWS extra fields */}
        {isAws && (
          <div className="space-y-3 pt-2 border-t border-border">
            <p className="text-xs text-slate-500">AWS credentials detected — additional fields required:</p>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Secret Access Key</label>
              <input
                type="password"
                value={awsSecret}
                onChange={e => setAwsSecret(e.target.value)}
                placeholder="AWS Secret Access Key"
                className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Region</label>
              <input
                value={awsRegion}
                onChange={e => setAwsRegion(e.target.value)}
                placeholder="us-east-1"
                className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
          </div>
        )}

        {/* Provider detected banner */}
        {keyStatus === 'valid' && providerInfo && (
          <div className="bg-accent/5 border border-accent/20 rounded-md px-3 py-2 flex items-center gap-2">
            <Globe size={13} className="text-accent shrink-0" />
            <span className="text-accent text-xs font-semibold">{providerInfo.provider} detected</span>
            <span className="text-slate-500 text-xs ml-auto">
              {providerInfo.models.length} model{providerInfo.models.length !== 1 ? 's' : ''} available
            </span>
          </div>
        )}
      </div>

      {/* Model selection */}
      {keyStatus === 'valid' && providerInfo && providerInfo.models.length > 0 && (
        <div className="bg-surface border border-border rounded-lg p-6 space-y-4">
          <div className="flex items-center gap-2">
            <Cpu size={15} className="text-slate-500" />
            <span className="text-white font-semibold text-sm">Choose Model</span>
          </div>

          {freeModels.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-bold text-success uppercase tracking-widest flex items-center gap-1">
                <Zap size={10} /> Free tier
              </p>
              {freeModels.map(m => (
                <ModelRow key={m.id} model={m} selected={selectedModel === m.id}
                  onSelect={() => setSelectedModel(m.id)} speedColor={speedColor} />
              ))}
            </div>
          )}

          {paidModels.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest flex items-center gap-1">
                <DollarSign size={10} /> Paid models
              </p>
              {paidModels.map(m => (
                <ModelRow key={m.id} model={m} selected={selectedModel === m.id}
                  onSelect={() => setSelectedModel(m.id)} speedColor={speedColor} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Save */}
      {keyStatus === 'valid' && selectedModel && (
        <div className="flex items-center gap-3">
          <button
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
            className="flex items-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-md transition-colors disabled:opacity-60"
          >
            {saveMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} />}
            Activate Engine
          </button>
          {saveMutation.isSuccess && (
            <span className="text-success text-xs font-semibold flex items-center gap-1">
              <CheckCircle2 size={13} /> Saved
            </span>
          )}
        </div>
      )}

      {/* How it fits */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <h3 className="text-white font-semibold text-sm mb-3">DCSP guardrails — always enforced</h3>
        <p className="text-slate-400 text-xs leading-relaxed mb-3">
          No matter which model you choose, every generated patch passes through the DSEE verification pipeline before
          it reaches your queue:
        </p>
        <ul className="space-y-2">
          {[
            'Boundary: max 40 lines, single file, no infra files touched',
            'Impact: public function removal and call-graph ripple checks',
            'Tests: failing test and related tests must pass',
            'Stability: no new warnings, performance threshold respected',
          ].map(r => (
            <li key={r} className="flex gap-2 text-xs text-slate-400">
              <CheckCircle2 size={12} className="text-success shrink-0 mt-0.5" /> {r}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

function ModelRow({ model, selected, onSelect, speedColor }: {
  model: ModelInfo;
  selected: boolean;
  onSelect: () => void;
  speedColor: Record<string, string>;
}) {
  return (
    <button
      onClick={onSelect}
      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md border text-left transition-colors ${
        selected
          ? 'border-accent/50 bg-accent/8'
          : 'border-border bg-background hover:border-slate-600'
      }`}
    >
      <span className={`w-3.5 h-3.5 rounded-full border-2 shrink-0 ${selected ? 'border-accent bg-accent' : 'border-slate-600'}`} />
      <span className="flex-1 text-xs text-white font-medium">{model.name || model.id}</span>
      <span className={`text-[10px] font-semibold capitalize ${speedColor[model.speed]}`}>{model.speed}</span>
      {model.pricing ? (
        <span className="text-[10px] text-slate-500 tabular-nums">
          ${model.pricing.prompt}/<span className="text-slate-600">in</span>
        </span>
      ) : (
        <span className="text-[10px] text-success font-bold">FREE</span>
      )}
    </button>
  );
}

export default AIEngine;
