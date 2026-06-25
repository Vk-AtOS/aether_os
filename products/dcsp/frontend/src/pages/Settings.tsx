import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Key, Plus, Trash2, Copy, CheckCircle2, Loader2, User, Shield,
  GitBranch, RefreshCw, ExternalLink,
} from 'lucide-react';
import api from '../lib/api';

interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
}

interface Installation {
  installation_id: number;
  account_login: string;
  account_type: string;
  is_active: boolean;
}

type Section = 'api-keys' | 'profile' | 'security' | 'github';

// ── GitHub section ──────────────────────────────────────────────────────────

const GitHubSection = () => {
  const qc = useQueryClient();
  const [connecting, setConnecting] = useState(false);

  const { data: statusData, isLoading: statusLoading } = useQuery({
    queryKey: ['github-status'],
    queryFn: () => api.get('/github/status').then(r => r.data),
    refetchInterval: 30_000,
  });

  const { data: installData, isLoading: installLoading } = useQuery({
    queryKey: ['github-installations'],
    queryFn: () => api.get('/github/installations').then(r => r.data),
    refetchInterval: 30_000,
  });

  const installations: Installation[] = installData?.installations ?? [];
  const configured = statusData?.configured === true;
  const appId = statusData?.app_id;

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const r = await api.get('/github/oauth/start');
      if (r.data?.url) {
        window.location.href = r.data.url;
      } else {
        alert('GitHub App not configured — ask your administrator to set GITHUB_APP_ID and private key.');
      }
    } catch {
      alert('Failed to start GitHub connection.');
    } finally {
      setConnecting(false);
    }
  };

  const handleRefresh = () => {
    qc.invalidateQueries({ queryKey: ['github-status'] });
    qc.invalidateQueries({ queryKey: ['github-installations'] });
  };

  return (
    <div className="space-y-5">
      {/* Connection status card */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <GitBranch size={18} className="text-white" />
            <span className="text-sm font-semibold text-white">GitHub App Connection</span>
          </div>
          <button onClick={handleRefresh} className="p-1.5 text-slate-500 hover:text-white rounded transition-colors" title="Refresh">
            <RefreshCw size={14} />
          </button>
        </div>

        {statusLoading ? (
          <div className="flex items-center gap-2 text-slate-500 text-sm">
            <Loader2 size={14} className="animate-spin" /> Checking status…
          </div>
        ) : configured ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="inline-block w-2 h-2 rounded-full bg-green-400" />
              <span className="text-sm text-green-400 font-medium">GitHub App configured</span>
              {appId && <span className="text-xs text-slate-500 font-mono">App #{appId}</span>}
            </div>
            <p className="text-xs text-slate-400">
              DCSP is authorised to open auto-fix PRs on repositories where the App is installed.
              Webhooks are registered automatically when you install the App on a repo.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="inline-block w-2 h-2 rounded-full bg-slate-500" />
              <span className="text-sm text-slate-400">GitHub App not configured</span>
            </div>
            <p className="text-xs text-slate-500">
              Configure GITHUB_APP_ID and the App private key, then restart DCSP to enable GitHub integration.
            </p>
          </div>
        )}
      </div>

      {/* Active installations */}
      <div className="bg-surface border border-border rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <span className="text-xs text-slate-500 font-medium">Active Installations</span>
          <span className="text-xs text-slate-600">{installLoading ? '…' : installations.length}</span>
        </div>

        {installLoading ? (
          <div className="px-4 py-6 flex items-center gap-2 text-slate-500 text-sm">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : installations.length === 0 ? (
          <div className="px-4 py-8 text-center space-y-3">
            <p className="text-xs text-slate-600">No GitHub installations found.</p>
            {configured && (
              <button
                onClick={handleConnect}
                disabled={connecting}
                className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-border text-white text-sm font-medium rounded-md transition-colors disabled:opacity-60"
              >
                {connecting ? <Loader2 size={14} className="animate-spin" /> : <GitBranch size={14} />}
                Install GitHub App on a repository
                <ExternalLink size={12} className="text-slate-500" />
              </button>
            )}
          </div>
        ) : (
          installations.map(inst => (
            <div key={inst.installation_id} className="flex items-center justify-between px-4 py-3 border-b border-border last:border-0">
              <div className="flex items-center gap-3">
                <GitBranch size={16} className="text-slate-400" />
                <div>
                  <p className="text-sm text-white font-medium">{inst.account_login}</p>
                  <p className="text-xs text-slate-600">{inst.account_type} · Installation #{inst.installation_id}</p>
                </div>
              </div>
              <span className="text-xs text-green-400 font-medium">Connected</span>
            </div>
          ))
        )}
      </div>

      {/* Instructions */}
      <div className="bg-slate-900/50 border border-border rounded-lg p-4 space-y-2">
        <p className="text-xs font-semibold text-slate-300">How GitHub integration works</p>
        <ol className="text-xs text-slate-500 space-y-1 list-decimal list-inside">
          <li>DCSP GitHub App is installed on your repo via GitHub's App Marketplace page.</li>
          <li>GitHub sends push/check_run webhooks to <code className="text-slate-400">POST /webhook/github</code>.</li>
          <li>On CI failure or SyntaxError push, DCSP auto-repairs and opens a PR.</li>
          <li>The connection persists across restarts — no need to reconnect manually.</li>
        </ol>
      </div>
    </div>
  );
};

// ── Main Settings component ─────────────────────────────────────────────────

const Settings = () => {
  const qc = useQueryClient();
  const [newKeyName, setNewKeyName]   = useState('');
  const [newKeyValue, setNewKeyValue] = useState('');
  const [copied, setCopied]           = useState('');
  const [section, setSection]         = useState<Section>('api-keys');

  const { data: keysData } = useQuery({
    queryKey: ['api-keys'],
    queryFn: () => api.get('/api/api-keys').then(r => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () => api.post('/api/api-keys', { name: newKeyName }),
    onSuccess: (res) => {
      setNewKeyValue(res.data.key ?? '');
      setNewKeyName('');
      qc.invalidateQueries({ queryKey: ['api-keys'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/api/api-keys/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  });

  const copy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(''), 2000);
  };

  const keys: ApiKey[] = keysData?.keys ?? [];

  const tabs = [
    { key: 'github',   label: 'GitHub',   icon: GitBranch },
    { key: 'api-keys', label: 'API Keys',  icon: Key },
    { key: 'profile',  label: 'Profile',   icon: User },
    { key: 'security', label: 'Security',  icon: Shield },
  ] as const;

  return (
    <div className="max-w-xl space-y-6">
      <h2 className="text-xl font-bold text-white">Settings</h2>

      <div className="flex gap-1 border-b border-border overflow-x-auto">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setSection(t.key as Section)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors whitespace-nowrap ${
              section === t.key ? 'border-accent text-accent' : 'border-transparent text-slate-500 hover:text-white'
            }`}
          >
            <t.icon size={14} /> {t.label}
          </button>
        ))}
      </div>

      {section === 'github' && <GitHubSection />}

      {section === 'api-keys' && (
        <div className="space-y-5">
          <p className="text-xs text-slate-500">
            Use API keys to authenticate programmatic webhook calls to DCSP.
          </p>
          <div className="bg-surface border border-border rounded-lg p-5 space-y-3">
            <p className="text-sm font-semibold text-white">Create new key</p>
            <div className="flex gap-2">
              <input
                value={newKeyName}
                onChange={e => setNewKeyName(e.target.value)}
                placeholder="Key name (e.g. CI pipeline)"
                className="flex-1 bg-background border border-border rounded-md px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <button
                onClick={() => createMutation.mutate()}
                disabled={!newKeyName || createMutation.isPending}
                className="flex items-center gap-1.5 px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-md transition-colors disabled:opacity-60"
              >
                {createMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                Create
              </button>
            </div>
            {newKeyValue && (
              <div className="bg-green-500/5 border border-green-500/20 rounded-md p-3">
                <p className="text-green-400 text-xs font-semibold mb-1.5">Copy it now — won't be shown again.</p>
                <div className="flex items-center gap-2 bg-background border border-border rounded px-3 py-2 font-mono text-xs text-white">
                  <span className="flex-1 truncate">{newKeyValue}</span>
                  <button onClick={() => copy(newKeyValue, 'new')}>
                    {copied === 'new' ? <CheckCircle2 size={13} className="text-green-400" /> : <Copy size={13} className="text-slate-500 hover:text-white" />}
                  </button>
                </div>
              </div>
            )}
          </div>
          <div className="bg-surface border border-border rounded-lg overflow-hidden">
            <div className="px-4 py-3 border-b border-border">
              <span className="text-xs text-slate-500 font-medium">Active keys</span>
            </div>
            {keys.length === 0
              ? <p className="px-4 py-8 text-xs text-slate-600 text-center">No API keys yet</p>
              : keys.map(k => (
                <div key={k.id} className="flex items-center justify-between px-4 py-3 border-b border-border last:border-0">
                  <div>
                    <p className="text-sm text-white font-medium">{k.name}</p>
                    <p className="text-xs text-slate-600 font-mono">{k.key_prefix}…</p>
                  </div>
                  <button onClick={() => deleteMutation.mutate(k.id)} className="p-2 text-slate-600 hover:text-red-400 rounded transition-colors">
                    <Trash2 size={14} />
                  </button>
                </div>
              ))
            }
          </div>
        </div>
      )}

      {section === 'profile' && (
        <div className="bg-surface border border-border rounded-lg p-5 space-y-4">
          <div>
            <label className="block text-xs text-slate-500 mb-1">Display Name</label>
            <input defaultValue="Admin" className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-accent" />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Email</label>
            <input type="email" className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-accent" />
          </div>
          <button className="px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-md transition-colors">Save</button>
        </div>
      )}

      {section === 'security' && (
        <div className="bg-surface border border-border rounded-lg p-5 space-y-4">
          {['Current password', 'New password', 'Confirm new password'].map(lbl => (
            <div key={lbl}>
              <label className="block text-xs text-slate-500 mb-1">{lbl}</label>
              <input type="password" className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-accent" />
            </div>
          ))}
          <button className="px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-md transition-colors">Update Password</button>
        </div>
      )}
    </div>
  );
};

export default Settings;
