import React from 'react';
import { useSettings } from '../contexts/SettingsContext';

const ProviderBadge = () => {
  const { activeProvider, activeModel } = useSettings();

  const STATUS_COLORS = {
    anthropic:  'bg-orange-400',
    openrouter: 'bg-purple-400',
    gemini:     'bg-blue-400',
    ollama:     'bg-green-400',
    bedrock:    'bg-yellow-400',
  };

  const dotColor = STATUS_COLORS[activeProvider] || 'bg-accent';
  const label = activeProvider && activeModel && activeModel !== '—'
    ? `${activeProvider} (${activeModel})`
    : activeProvider || 'Checking…';

  return (
    <div className="flex items-center text-xs p-2.5 rounded bg-surface border border-border">
      <div className={`w-2 h-2 rounded-full mr-2.5 shrink-0 ${dotColor}`} />
      <div className="flex flex-col min-w-0">
        <span className="text-[10px] text-muted uppercase font-bold tracking-tighter">Active LLM</span>
        <span className="font-medium truncate max-w-[140px]">{label}</span>
      </div>
    </div>
  );
};

export default ProviderBadge;
