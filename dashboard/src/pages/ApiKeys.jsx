import React, { useState, useEffect, useCallback } from 'react';
import { KeyRound, Plus, Trash2, Loader2 } from 'lucide-react';
import { api } from '../api';
import { apiError } from '../apiError';
import { confirmAction } from '../components/confirmAction';

// Organisation API keys (/auth/api-keys): credentials for CI, the MCP routes and integrations.
// The secret is returned once by the server and held here only until the user dismisses it.
const fmt = (v) => (v ? new Date(typeof v === 'number' ? v * 1000 : v).toLocaleString() : 'never');

const ApiKeys = () => {
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);
  const [secret, setSecret] = useState(null);

  const load = useCallback(async () => {
    try {
      setKeys((await api.listOrgApiKeys()).data ?? []);
      setError(null);
    } catch (e) {
      setError(apiError(e) || 'Failed to load API keys.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const create = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const res = await api.createOrgApiKey(name.trim());
      setSecret(res.data.api_key);
      setName('');
      await load();
    } catch (err) {
      setError(apiError(err) || 'Failed to create the key.');
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (key) => {
    if (!(await confirmAction(`Revoke "${key.name}"? Anything using it stops working immediately.`, 'Revoke API key'))) return;
    try {
      await api.revokeOrgApiKey(key.id);
      setKeys((prev) => prev.filter((k) => k.id !== key.id));
    } catch (err) {
      setError(apiError(err) || 'Failed to revoke the key.');
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-bright">API keys</h1>
        <p className="text-muted mt-1">Keys let CI, integrations and the MCP routes act for this organisation. A key cannot create other keys.</p>
      </header>

      {error && <div role="alert" className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-danger text-xs">{error}</div>}

      {secret && (
        <div role="alert" className="p-4 rounded-lg bg-amber-500/10 border border-amber-500/30 text-xs space-y-2">
          <p className="text-bright font-bold">Copy this key now. It is not shown again.</p>
          <code className="block break-all font-mono text-bright select-all">{secret}</code>
          <div className="flex gap-3">
            <button onClick={() => navigator.clipboard?.writeText(secret)} className="text-accent hover:underline">Copy</button>
            <button onClick={() => setSecret(null)} className="text-muted hover:text-bright">I have saved it</button>
          </div>
        </div>
      )}

      <form onSubmit={create} className="panel p-4 flex gap-3 items-end">
        <label className="flex-1 text-xs font-bold text-muted uppercase tracking-wider">
          Key name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} placeholder="ci-pipeline"
            className="mt-1 w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright font-normal normal-case tracking-normal" />
        </label>
        <button type="submit" disabled={creating || !name.trim()}
          className="flex items-center gap-2 bg-accent text-white text-xs font-bold px-4 py-2 rounded-lg uppercase disabled:opacity-50">
          {creating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}Create key
        </button>
      </form>

      <section className="panel overflow-hidden">
        <div className="bg-border/20 px-6 py-3 border-b border-border flex items-center text-xs font-bold text-muted uppercase tracking-widest">
          <KeyRound className="w-4 h-4 mr-2 text-accent" />Active keys ({keys.length})
        </div>
        {loading ? (
          <div className="p-10 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-accent" /></div>
        ) : keys.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted">No API keys yet.</p>
        ) : (
          <ul className="divide-y divide-border">
            {keys.map((k) => (
              <li key={k.id} className="px-6 py-3 flex items-center justify-between">
                <div>
                  <div className="text-sm text-bright font-medium">{k.name}</div>
                  <div className="text-[11px] text-muted">Created {fmt(k.created_at)} · last used {fmt(k.last_used_at)}</div>
                </div>
                <button onClick={() => revoke(k)} aria-label={`Revoke ${k.name}`} className="text-danger/60 hover:text-danger">
                  <Trash2 className="w-4 h-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
};

export default ApiKeys;
