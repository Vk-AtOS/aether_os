import ConnectorExplore from '../components/ConnectorExplore';
import { useState, useEffect, useCallback } from "react";
import {
  CheckCircle, XCircle, Settings, Plus, Trash2, Loader2,
  GitBranch, MessageSquare, Pen, Globe, Database, Cloud, Bell, CreditCard, Search
} from "lucide-react";
import api from "../api";
import { confirmAction } from '../components/confirmAction';
import { apiError } from '../apiError';

const ICON_MAP = {
  github: GitBranch, gitlab: GitBranch, slack: MessageSquare, figma: Pen,
  vercel: Globe, aws: Cloud, gcp: Cloud, stripe: CreditCard,
  supabase: Database, sentry: Bell, jira: Settings, linear: Settings,
  planetscale: Database,
};

const TAG_COLORS = {
  vcs: "bg-blue-950/40 text-blue-400",
  devtools: "bg-indigo-950/40 text-indigo-400",
  pm: "bg-purple-950/40 text-purple-400",
  agile: "bg-violet-950/40 text-violet-400",
  comms: "bg-green-950/40 text-green-400",
  design: "bg-pink-950/40 text-pink-400",
  deploy: "bg-orange-950/40 text-orange-400",
  cloud: "bg-sky-950/40 text-sky-400",
  payments: "bg-emerald-950/40 text-emerald-400",
  database: "bg-yellow-950/40 text-yellow-400",
  backend: "bg-teal-950/40 text-teal-400",
  observability: "bg-red-950/40 text-red-400",
  monitoring: "bg-rose-950/40 text-rose-400",
};

function ConnectorCard({ plugin, installed, onInstall, onUninstall, onTest }) {
  const [expanded, setExpanded] = useState(false);
  const [editingConfig, setEditingConfig] = useState(false);
  const [configValues, setConfigValues] = useState({});
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [saving, setSaving] = useState(false);
  const Icon = ICON_MAP[plugin.id] || Globe;
  const schema = plugin.config_schema || {};
  const isInstalled = !!installed;

  const handleInstall = async () => {
    setSaving(true);
    try {
      await onInstall(plugin.id, configValues);
      setExpanded(false);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await onTest(plugin.id);
      setTestResult(result);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className={`bg-panel rounded-xl border transition-all ${isInstalled ? "border-green-700" : "border-border"} overflow-hidden`}>
      <div className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${isInstalled ? "bg-green-950/40" : "bg-surface"}`}>
              <Icon size={20} className={isInstalled ? "text-green-400" : "text-muted"} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-bright">{plugin.name}</h3>
                {isInstalled && <CheckCircle size={14} className="text-green-400" />}
              </div>
              <p className="text-xs text-muted mt-0.5">{plugin.description}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {plugin.requires_plan && plugin.requires_plan !== "trial" && (
              <span className="text-xs px-2 py-0.5 bg-purple-950/40 text-purple-400 rounded-full font-medium">
                {plugin.requires_plan}+
              </span>
            )}
            {isInstalled ? (
              <>
                <button onClick={handleTest} disabled={testing}
                  className="text-xs px-3 py-1.5 bg-blue-950/40 text-blue-400 rounded-lg hover:bg-blue-900/50 disabled:opacity-50 flex items-center gap-1">
                  {testing ? <Loader2 size={12} className="animate-spin" /> : null}
                  Test
                </button>
                <button onClick={() => setEditingConfig(v => !v)}
                  className="text-xs px-3 py-1.5 bg-yellow-950/40 text-yellow-400 rounded-lg hover:bg-yellow-900/50 flex items-center gap-1">
                  {editingConfig ? 'Cancel' : 'Edit Config'}
                </button>
                <button onClick={() => onUninstall(plugin.id)}
                  className="p-1.5 text-red-400 hover:bg-red-950/30 rounded-lg">
                  <Trash2 size={14} />
                </button>
              </>
            ) : (
              <button onClick={() => setExpanded(!expanded)}
                className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-1">
                <Plus size={12} /> Connect
              </button>
            )}
          </div>
        </div>

        {/* Tags */}
        <div className="flex flex-wrap gap-1 mt-3">
          {(plugin.tags || []).map((tag) => (
            <span key={tag} className={`text-xs px-2 py-0.5 rounded-full ${TAG_COLORS[tag] || "bg-border/20 text-muted"}`}>
              {tag}
            </span>
          ))}
        </div>

        {isInstalled && <ConnectorExplore pluginId={plugin.id} />}

        {/* Test result */}
        {testResult && (
          <div className={`mt-3 text-xs px-3 py-2 rounded-lg flex items-center gap-2 ${testResult.ok ? "bg-green-950/40 text-green-400" : "bg-red-950/40 text-red-400"}`}>
            {testResult.ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
            {testResult.message}
          </div>
        )}
      </div>

      {/* Edit Config panel */}
      {editingConfig && isInstalled && Object.keys(schema).length > 0 && (
        <div className="border-t border-border/50 p-4 bg-surface">
          <p className="text-xs font-semibold text-muted mb-3 uppercase tracking-wide">Update Configuration</p>
          {Object.entries(schema).map(([key, field]) => (
            <div key={key} className="mb-3">
              <label className="block text-xs font-medium text-muted mb-1">
                {field.label || key}
                {field.required && <span className="text-red-400 ml-1">*</span>}
              </label>
              <input
                type={field.secret ? 'password' : 'text'}
                placeholder={field.default ? String(field.default) : 'New value'}
                value={configValues[key] || ''}
                onChange={(e) => setConfigValues((v) => ({ ...v, [key]: e.target.value }))}
                className="w-full text-sm px-3 py-2 border border-border rounded-lg bg-background text-bright focus:outline-none focus:border-blue-400"
              />
            </div>
          ))}
          <div className="flex gap-2 mt-4">
            <button
              onClick={async () => {
                setSaving(true);
                try {
                  await api.client.put(`/v2/plugins/installed/${plugin.id}/config`, { config: configValues });
                  setEditingConfig(false);
                  setConfigValues({});
                } catch (e) {
                  alert('Update failed: ' + (apiError(e) || e.message));
                } finally {
                  setSaving(false);
                }
              }}
              disabled={saving}
              className="flex-1 py-2 bg-yellow-600 text-white text-sm rounded-lg hover:bg-yellow-700 disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {saving ? 'Saving…' : 'Save Config'}
            </button>
            <button onClick={() => { setEditingConfig(false); setConfigValues({}); }}
              className="px-4 py-2 text-muted border border-border rounded-lg text-sm hover:bg-surface">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Config form */}
      {expanded && !isInstalled && (
        <div className="border-t border-border/50 p-4 bg-surface">
          <p className="text-xs font-semibold text-muted mb-3 uppercase tracking-wide">Configuration</p>
          {Object.entries(schema).map(([key, field]) => (
            <div key={key} className="mb-3">
              <label className="block text-xs font-medium text-muted mb-1">
                {field.label || key}
                {field.required && <span className="text-red-400 ml-1">*</span>}
              </label>
              <input
                type={field.secret ? "password" : "text"}
                placeholder={field.default ? String(field.default) : ""}
                value={configValues[key] || ""}
                onChange={(e) => setConfigValues((v) => ({ ...v, [key]: e.target.value }))}
                className="w-full text-sm px-3 py-2 border border-border rounded-lg bg-background text-bright focus:outline-none focus:border-blue-400"
              />
            </div>
          ))}
          <div className="flex gap-2 mt-4">
            <button onClick={handleInstall} disabled={saving}
              className="flex-1 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Install
            </button>
            <button onClick={() => setExpanded(false)}
              className="px-4 py-2 text-muted border border-border rounded-lg text-sm hover:bg-surface">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ConnectorHub() {
  const [catalog, setCatalog] = useState([]);
  const [installed, setInstalled] = useState({});
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState(null);

  // Promise chain with no state set before the request: this runs from an effect.
  const load = useCallback(() => Promise.all([
    api.client.get("/v2/plugins/catalog", { params: { type: "connector" } }),
    api.client.get("/v2/plugins/installed"),
  ])
    .then(([catRes, instRes]) => {
      setCatalog(catRes.data);
      const instMap = {};
      for (const p of instRes.data) instMap[p.plugin_id] = p;
      setInstalled(instMap);
    })
    .catch((e) => setError(apiError(e) || "Failed to load connectors"))
    .finally(() => setLoading(false)), []);

  useEffect(() => { load(); }, [load]);

  const handleInstall = async (pluginId, config) => {
    await api.client.post("/v2/plugins/install", { plugin_id: pluginId, config });
    await load();
  };

  const handleUninstall = async (pluginId) => {
    if (!(await confirmAction(`Uninstall ${pluginId}? This will remove stored credentials.`))) return;
    await api.client.delete(`/v2/plugins/installed/${pluginId}`);
    await load();
  };

  const handleTest = async (pluginId) => {
    const res = await api.client.post(`/v2/plugins/installed/${pluginId}/test`);
    return res.data;
  };

  const filtered = catalog.filter((p) => {
    if (filter && !p.name.toLowerCase().includes(filter.toLowerCase()) &&
        !p.description.toLowerCase().includes(filter.toLowerCase()) &&
        !(p.tags || []).some((t) => t.includes(filter.toLowerCase()))) return false;
    return true;
  });

  const installedCount = Object.keys(installed).length;

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <Loader2 size={24} className="animate-spin text-blue-500" />
    </div>
  );

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-bright">Connector Hub</h1>
        <p className="text-sm text-muted mt-1">
          Connect your tools · {installedCount} connected · {catalog.length} available
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-950/40 border border-red-900 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Search bar */}
      <div className="flex gap-3 mb-6">
        <div className="flex-1 relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search connectors..."
            className="w-full pl-9 pr-4 py-2.5 border border-border rounded-xl text-sm bg-background text-bright focus:outline-none focus:border-blue-400"
          />
        </div>
      </div>

      {/* Installed banner */}
      {installedCount > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-3">
            Connected ({installedCount})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {catalog.filter((p) => installed[p.id]).map((plugin) => (
              <ConnectorCard
                key={plugin.id}
                plugin={plugin}
                installed={installed[plugin.id]}
                onInstall={handleInstall}
                onUninstall={handleUninstall}
                onTest={handleTest}
              />
            ))}
          </div>
        </div>
      )}

      {/* Available */}
      <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-3">
        Available
      </h2>
      {filtered.filter((p) => !installed[p.id]).length === 0 ? (
        <p className="text-muted text-sm">No connectors match your search.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filtered.filter((p) => !installed[p.id]).map((plugin) => (
            <ConnectorCard
              key={plugin.id}
              plugin={plugin}
              installed={installed[plugin.id]}
              onInstall={handleInstall}
              onUninstall={handleUninstall}
              onTest={handleTest}
            />
          ))}
        </div>
      )}
    </div>
  );
}
