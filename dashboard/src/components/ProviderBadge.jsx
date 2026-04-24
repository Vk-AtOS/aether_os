import React, { useState, useEffect } from 'react';
import { api } from '../api';

const ProviderBadge = () => {
  const [provider, setProvider] = useState('Checking...');
  const [status, setStatus] = useState('warning');

  useEffect(() => {
    const check = async () => {
      try {
        const res = await api.getHealth();
        setProvider(res.data.llm_provider || 'Gemini 1.5 Pro');
        setStatus(res.data.llm_status || 'success');
      } catch (err) {
        setProvider('Offline');
        setStatus('danger');
      }
    };
    check();
  }, []);

  const colors = {
    success: 'bg-success',
    warning: 'bg-warning',
    danger: 'bg-danger',
  };

  return (
    <div className="flex items-center text-xs p-2.5 rounded bg-surface border border-border">
      <div className={`w-2 h-2 rounded-full mr-2.5 ${colors[status] || 'bg-muted'}`}></div>
      <div className="flex flex-col">
        <span className="text-[10px] text-muted uppercase font-bold tracking-tighter">Active LLM</span>
        <span className="font-medium">{provider}</span>
      </div>
    </div>
  );
};

export default ProviderBadge;
