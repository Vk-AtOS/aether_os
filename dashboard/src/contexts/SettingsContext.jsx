import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api } from '../api';

const SettingsContext = createContext(null);

export const useSettings = () => {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider');
  return ctx;
};

export const SettingsProvider = ({ children }) => {
  const [llmConfig, setLlmConfig] = useState(null);      // { provider, primary_model, ... }
  const [orgSettings, setOrgSettings] = useState(null);  // { org_name, plan, ... }
  const [prefs, setPrefs] = useState({});                 // user preferences
  const [ready, setReady] = useState(false);

  const load = useCallback(async () => {
    try {
      const token = api.getToken();
      if (!token) return;
      const [llm, acct, pref] = await Promise.allSettled([
        api.client.get('/settings/llm-config'),
        api.client.get('/account/usage'),
        api.client.get('/settings/preferences'),
      ]);
      if (llm.status === 'fulfilled') setLlmConfig(llm.value.data);
      if (acct.status === 'fulfilled') setOrgSettings(acct.value.data);
      if (pref.status === 'fulfilled') setPrefs(pref.value.data?.preferences || {});
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Called by Settings page when LLM config is saved — propagates instantly
  const updateLlmConfig = useCallback((patch) => {
    setLlmConfig(prev => ({ ...prev, ...patch }));
  }, []);

  const updateOrgSettings = useCallback((patch) => {
    setOrgSettings(prev => ({ ...prev, ...patch }));
  }, []);

  const updatePrefs = useCallback((patch) => {
    setPrefs(prev => ({ ...prev, ...patch }));
  }, []);

  // Derived helpers consumed by TopBar, Sidebar, etc.
  // API returns primary_llm (the configured provider) and active_model (last successful call).
  // Do NOT fall back to 'anthropic' — show null until the real config is loaded so badges
  // never display a hardcoded provider name.
  const activeProvider = llmConfig?.primary_llm || llmConfig?.provider || llmConfig?.active_provider || null;
  const activeModel = llmConfig?.active_model || llmConfig?.primary_model || llmConfig?.model || '—';
  // False only when the server says the configured provider has no credential at all.
  const providerKeyMissing = llmConfig?.primary_key_configured === false;
  const orgName = orgSettings?.org_name || '';
  const plan = orgSettings?.plan || 'free';

  return (
    <SettingsContext.Provider value={{
      llmConfig, orgSettings, prefs,
      ready,
      activeProvider, activeModel, providerKeyMissing, orgName, plan,
      updateLlmConfig, updateOrgSettings, updatePrefs,
      reload: load,
    }}>
      {children}
    </SettingsContext.Provider>
  );
};
