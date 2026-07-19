import React from 'react';
import { useSettings } from '../contexts/SettingsContext';

const PROVIDER_STYLES = {
  anthropic:  { dot: 'bg-orange-400', pill: 'bg-orange-500/10 border-orange-500/20 text-orange-400' },
  openrouter: { dot: 'bg-purple-400', pill: 'bg-purple-500/10 border-purple-500/20 text-purple-400' },
  gemini:     { dot: 'bg-blue-400',   pill: 'bg-blue-500/10 border-blue-500/20 text-blue-400' },
  ollama:     { dot: 'bg-green-400',  pill: 'bg-green-500/10 border-green-500/20 text-green-400' },
  bedrock:    { dot: 'bg-amber-400',  pill: 'bg-amber-500/10 border-amber-500/20 text-amber-400' },
};

const ProviderBadge = () => {
  const { activeProvider, activeModel, ready } = useSettings();

  // While settings are loading, show nothing to avoid a hardcoded flash
  if (!ready) return null;

  // If no provider is configured after load, show a clear unconfigured state
  if (!activeProvider) {
    return (
      <div className="flex items-center gap-2 text-xs px-3 py-2 rounded-xl border bg-slate-500/10 border-slate-500/20 text-slate-400 transition-all">
        <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-slate-500" />
        <div className="min-w-0">
          <span className="text-[9px] font-bold uppercase tracking-widest opacity-60 block leading-none mb-0.5">Active LLM</span>
          <span className="font-medium truncate block max-w-[130px] text-[11px]">Not configured</span>
        </div>
      </div>
    );
  }

  const style = PROVIDER_STYLES[activeProvider] || { dot: 'bg-violet-400', pill: 'bg-violet-500/10 border-violet-500/20 text-violet-400' };
  const label = activeModel && activeModel !== '—'
    ? `${activeProvider} · ${activeModel.split('/').pop()?.slice(0, 18) || activeModel.slice(0, 18)}`
    : activeProvider;

  return (
    <div className={`flex items-center gap-2 text-xs px-3 py-2 rounded-xl border ${style.pill} transition-all`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${style.dot}`} />
      <div className="min-w-0">
        <span className="text-[9px] font-bold uppercase tracking-widest opacity-60 block leading-none mb-0.5">Active LLM</span>
        <span className="font-medium truncate block max-w-[130px] text-[11px]">{label}</span>
      </div>
    </div>
  );
};

export default ProviderBadge;
