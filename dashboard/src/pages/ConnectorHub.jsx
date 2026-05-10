import { useState, useEffect } from "react";
import {
  CheckCircle, XCircle, Settings, Plus, Trash2, Loader2,
  GitBranch, MessageSquare, Pen, Globe, Database, Cloud, Bell, CreditCard, Search
} from "lucide-react";
import api from "../api";

const ICON_MAP = {
  github: GitBranch, gitlab: GitBranch, slack: MessageSquare, figma: Pen,
  vercel: Globe, aws: Cloud, gcp: Cloud, stripe: CreditCard,
  supabase: Database, sentry: Bell, jira: Settings, linear: Settings,
  planetscale: Database,
};

const TAG_COLORS = {
  vcs: "bg-blue-100 text-blue-700",
  devtools: "bg-indigo-100 text-indigo-700",
  pm: "bg-purple-100 text-purple-700",
  agile: "bg-violet-100 text-violet-700",
  comms: "bg-green-100 text-green-700",
  design: "bg-pink-100 text-pink-700",
  deploy: "bg-orange-100 text-orange-700",
  cloud: "bg-sky-100 text-sky-700",
  payments: "bg-emerald-100 text-emerald-700",
  database: "bg-yellow-100 text-yellow-700",
  backend: "bg-teal-100 text-teal-700",
  observability: "bg-red-100 text-red-700",
  monitoring: "bg-rose-100 text-rose-700",
};

function ConnectorCard({ plugin, installed, onInstall, onUninstall, onTest }) {
  const [expanded, setExpanded] = useState(false);
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
    <div className={`bg-white rounded-xl border transition-all ${isInstalled ? "border-green-200" : "border-gray-200"} overflow-hidden`}>
      <div className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${isInstalled ? "bg-green-50" : "bg-gray-50"}`}>
              <Icon size={20} className={isInstalled ? "text-green-600" : "text-gray-500"} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-gray-900">{plugin.name}</h3>
                {isInstalled && <CheckCircle size={14} className="text-green-500" />}
              </div>
              <p className="text-xs text-gray-500 mt-0.5">{plugin.description}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {plugin.requires_plan && plugin.requires_plan !== "trial" && (
              <span className="text-xs px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full font-medium">
                {plugin.requires_plan}+
              </span>
            )}
            {isInstalled ? (
              <>
                <button onClick={handleTest} disabled={testing}
                  className="text-xs px-3 py-1.5 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 disabled:opacity-50 flex items-center gap-1">
                  {testing ? <Loader2 size={12} className="animate-spin" /> : null}
                  Test
                </button>
                <button onClick={() => onUninstall(plugin.id)}
                  className="p-1.5 text-red-400 hover:bg-red-50 rounded-lg">
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
            <span key={tag} className={`text-xs px-2 py-0.5 rounded-full ${TAG_COLORS[tag] || "bg-gray-100 text-gray-600"}`}>
              {tag}
            </span>
          ))}
        </div>

        {/* Test result */}
        {testResult && (
          <div className={`mt-3 text-xs px-3 py-2 rounded-lg flex items-center gap-2 ${testResult.ok ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
            {testResult.ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
            {testResult.message}
          </div>
        )}
      </div>

      {/* Config form */}
      {expanded && !isInstalled && (
        <div className="border-t border-gray-100 p-4 bg-gray-50">
          <p className="text-xs font-semibold text-gray-600 mb-3 uppercase tracking-wide">Configuration</p>
          {Object.entries(schema).map(([key, field]) => (
            <div key={key} className="mb-3">
              <label className="block text-xs font-medium text-gray-600 mb-1">
                {field.label || key}
                {field.required && <span className="text-red-400 ml-1">*</span>}
              </label>
              <input
                type={field.secret ? "password" : "text"}
                placeholder={field.default ? String(field.default) : ""}
                value={configValues[key] || ""}
                onChange={(e) => setConfigValues((v) => ({ ...v, [key]: e.target.value }))}
                className="w-full text-sm px-3 py-2 border border-gray-200 rounded-lg bg-white focus:outline-none focus:border-blue-400"
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
              className="px-4 py-2 text-gray-600 border border-gray-200 rounded-lg text-sm hover:bg-gray-50">
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
  const [typeFilter, setTypeFilter] = useState("connector");
  const [error, setError] = useState(null);

  const load = async () => {
    try {
      setLoading(true);
      const [catRes, instRes] = await Promise.all([
        api.client.get("/v2/plugins/catalog", { params: { type: "connector" } }),
        api.client.get("/v2/plugins/installed"),
      ]);
      setCatalog(catRes.data);
      const instMap = {};
      for (const p of instRes.data) instMap[p.plugin_id] = p;
      setInstalled(instMap);
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to load connectors");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleInstall = async (pluginId, config) => {
    await api.client.post("/v2/plugins/install", { plugin_id: pluginId, config });
    await load();
  };

  const handleUninstall = async (pluginId) => {
    if (!confirm(`Uninstall ${pluginId}? This will remove stored credentials.`)) return;
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
        <h1 className="text-2xl font-bold text-gray-900">Connector Hub</h1>
        <p className="text-sm text-gray-500 mt-1">
          Connect your tools · {installedCount} connected · {catalog.length} available
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm">
          {error}
        </div>
      )}

      {/* Search bar */}
      <div className="flex gap-3 mb-6">
        <div className="flex-1 relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search connectors..."
            className="w-full pl-9 pr-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-400"
          />
        </div>
      </div>

      {/* Installed banner */}
      {installedCount > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
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
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
        Available
      </h2>
      {filtered.filter((p) => !installed[p.id]).length === 0 ? (
        <p className="text-gray-400 text-sm">No connectors match your search.</p>
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
