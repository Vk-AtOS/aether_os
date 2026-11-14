import React, { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import { api } from '../../api';

const EnvVarsPanel = ({ runId, onToast }) => {
  const [envVars, setEnvVars] = useState(null);
  const [envSaving, setEnvSaving] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    if (envVars === null) {
      api.getEnvVars(runId)
        .then(r => setEnvVars(r.data?.vars || []))
        .catch(() => { setLoadFailed(true); setEnvVars([]); }); // Save stays off: an empty list would wipe the .env
    }
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSave = async () => {
    setEnvSaving(true);
    try {
      await api.patchEnvVars(runId, envVars.filter(v => v.key.trim()));
      onToast('Environment saved.');
    } catch {
      onToast('Save failed.');
    } finally {
      setEnvSaving(false);
    }
  };

  return (
    <div className="p-4 space-y-3 h-[420px] overflow-y-auto custom-scrollbar">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-bold text-muted uppercase tracking-wider">Environment Variables</span>
        <div className="flex items-center space-x-2">
          <button
            onClick={() => setEnvVars(prev => [...(prev || []), { key: '', value: '' }])}
            className="text-[10px] px-2 py-1 bg-indigo-700 hover:bg-indigo-600 text-white rounded"
          >+ Add</button>
          <button
            disabled={envSaving || loadFailed}
            onClick={handleSave}
            className="text-[10px] px-2 py-1 bg-emerald-700 hover:bg-emerald-600 text-white rounded disabled:opacity-50"
          >{envSaving ? 'Saving…' : 'Save .env'}</button>
        </div>
      </div>

      {loadFailed && <div role="alert" className="text-danger text-xs">Could not load the .env file, so saving is disabled. Reload the tab to try again.</div>}
      {envVars === null ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="w-5 h-5 text-accent animate-spin" />
        </div>
      ) : envVars.length === 0 ? (
        <div className="text-muted text-xs italic text-center py-8">No .env file found. Add variables above.</div>
      ) : (
        envVars.map((v, i) => (
          <div key={i} className="flex items-center space-x-2">
            <input
              value={v.key}
              onChange={e => setEnvVars(prev => prev.map((x, j) => j === i ? { ...x, key: e.target.value } : x))}
              placeholder="KEY"
              className="w-40 bg-bg border border-border rounded px-2 py-1 text-xs font-mono text-bright focus:outline-none focus:border-accent"
            />
            <span className="text-muted text-xs">=</span>
            <input
              type="password"
              autoComplete="off"
              value={v.value}
              onChange={e => setEnvVars(prev => prev.map((x, j) => j === i ? { ...x, value: e.target.value } : x))}
              placeholder="value"
              className="flex-1 bg-bg border border-border rounded px-2 py-1 text-xs font-mono text-bright focus:outline-none focus:border-accent"
            />
            <button
              onClick={() => setEnvVars(prev => prev.filter((_, j) => j !== i))}
              className="text-danger hover:text-red-400 text-xs px-1"
            >✕</button>
          </div>
        ))
      )}
    </div>
  );
};

export default EnvVarsPanel;
