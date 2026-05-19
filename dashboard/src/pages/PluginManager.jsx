import { useState, useEffect } from "react";
import {
  Package, Lock, Shield, Mail, Search as SearchIcon, Upload,
  Bell, BarChart2, Settings, Globe, Zap, Play, CheckCircle,
  Loader2, Code2, Copy, ChevronDown, ChevronRight
} from "lucide-react";
import api from "../api";

const SKILL_ICONS = {
  skill_auth: Lock, skill_crud: Settings, skill_payment: Zap,
  skill_email: Mail, skill_search: SearchIcon, skill_file_upload: Upload,
  skill_notifications: Bell, skill_analytics: BarChart2,
  skill_admin: Shield, skill_i18n: Globe,
};

function SkillCard({ skill, onGenerate }) {
  const [expanded, setExpanded] = useState(false);
  const [params, setParams] = useState({});
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState(null);
  const [copied, setCopied] = useState(false);
  const Icon = SKILL_ICONS[skill.id] || Package;

  const paramHints = {
    skill_auth: [
      { key: "framework", label: "Framework", default: "fastapi", options: ["fastapi", "django", "express", "nextjs"] },
      { key: "auth_type", label: "Auth Type", default: "jwt", options: ["jwt", "oauth", "mfa", "magic_link"] },
    ],
    skill_crud: [
      { key: "resource", label: "Resource Name", default: "item" },
      { key: "framework", label: "Framework", default: "fastapi", options: ["fastapi", "django", "express"] },
      { key: "database", label: "Database", default: "postgresql", options: ["postgresql", "mysql", "sqlite"] },
    ],
    skill_payment: [
      { key: "type", label: "Payment Type", default: "one_time", options: ["one_time", "subscription"] },
      { key: "currency", label: "Currency", default: "usd" },
    ],
    skill_email: [
      { key: "provider", label: "Provider", default: "resend", options: ["resend", "sendgrid", "ses"] },
    ],
    skill_search: [
      { key: "type", label: "Search Type", default: "full_text", options: ["full_text", "vector", "hybrid"] },
      { key: "model", label: "Resource Name", default: "document" },
    ],
    skill_analytics: [
      { key: "provider", label: "Provider", default: "posthog", options: ["posthog", "mixpanel", "segment"] },
    ],
    skill_i18n: [
      { key: "framework", label: "Framework", default: "react", options: ["react", "nextjs", "vue"] },
      { key: "locales", label: "Locales (comma-sep)", default: "en,es,fr,de" },
    ],
  };

  const hints = paramHints[skill.id] || [];

  const handleGenerate = async () => {
    setGenerating(true);
    setResult(null);
    try {
      const processedParams = { ...params };
      if (processedParams.locales && typeof processedParams.locales === "string") {
        processedParams.locales = processedParams.locales.split(",").map((s) => s.trim());
      }
      const res = await onGenerate(skill.id, processedParams);
      setResult(res);
    } finally {
      setGenerating(false);
    }
  };

  const copyAll = () => {
    if (!result?.files) return;
    const text = Object.entries(result.files)
      .map(([path, content]) => `// ${path}\n${content}`)
      .join("\n\n");
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="bg-panel rounded-xl border border-border overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-4 text-left hover:bg-surface transition-colors"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-950/40 rounded-lg">
              <Icon size={18} className="text-blue-400" />
            </div>
            <div>
              <h3 className="font-semibold text-bright">{skill.name}</h3>
              <p className="text-xs text-muted mt-0.5">{skill.description}</p>
            </div>
          </div>
          {expanded ? <ChevronDown size={16} className="text-muted" /> : <ChevronRight size={16} className="text-muted" />}
        </div>
        <div className="flex flex-wrap gap-1 mt-2">
          {(skill.capabilities || []).slice(0, 4).map((cap) => (
            <span key={cap} className="text-xs px-2 py-0.5 bg-border/20 text-muted rounded-full">{cap}</span>
          ))}
          {(skill.capabilities || []).length > 4 && (
            <span className="text-xs px-2 py-0.5 bg-border/20 text-muted rounded-full">
              +{skill.capabilities.length - 4} more
            </span>
          )}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-border/50">
          {/* Params */}
          {hints.length > 0 && (
            <div className="p-4 bg-surface border-b border-border/50">
              <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-3">Parameters</p>
              <div className="grid grid-cols-2 gap-3">
                {hints.map((hint) => (
                  <div key={hint.key}>
                    <label className="block text-xs font-medium text-muted mb-1">{hint.label}</label>
                    {hint.options ? (
                      <select
                        value={params[hint.key] || hint.default}
                        onChange={(e) => setParams((p) => ({ ...p, [hint.key]: e.target.value }))}
                        className="w-full text-sm px-3 py-1.5 border border-border rounded-lg bg-background text-bright focus:outline-none focus:border-blue-400"
                      >
                        {hint.options.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    ) : (
                      <input
                        value={params[hint.key] !== undefined ? params[hint.key] : hint.default}
                        onChange={(e) => setParams((p) => ({ ...p, [hint.key]: e.target.value }))}
                        className="w-full text-sm px-3 py-1.5 border border-border rounded-lg bg-background text-bright focus:outline-none focus:border-blue-400"
                      />
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Generate button */}
          <div className="p-4">
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {generating
                ? <><Loader2 size={14} className="animate-spin" /> Generating...</>
                : <><Play size={14} /> Generate Code</>}
            </button>
          </div>

          {/* Result */}
          {result && (
            <div className="border-t border-border/50 p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 text-green-400">
                  <CheckCircle size={14} />
                  <span className="text-sm font-medium">
                    {result.file_count} file{result.file_count !== 1 ? "s" : ""} generated
                  </span>
                </div>
                <button onClick={copyAll}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-border rounded-lg hover:bg-surface text-muted">
                  <Copy size={12} /> {copied ? "Copied!" : "Copy all"}
                </button>
              </div>

              {result.dependencies?.length > 0 && (
                <div className="mb-3 p-3 bg-amber-950/40 border border-amber-900 rounded-lg text-xs">
                  <p className="font-medium text-amber-400 mb-1">Dependencies:</p>
                  <code className="text-amber-300">{result.dependencies.join(", ")}</code>
                </div>
              )}

              {result.env_vars?.length > 0 && (
                <div className="mb-3 p-3 bg-blue-950/40 border border-blue-900 rounded-lg text-xs">
                  <p className="font-medium text-blue-400 mb-1">Required env vars:</p>
                  <code className="text-blue-300">{result.env_vars.join(", ")}</code>
                </div>
              )}

              <div className="space-y-2 max-h-64 overflow-y-auto">
                {Object.entries(result.files || {}).map(([path, content]) => (
                  <div key={path} className="bg-gray-900 rounded-lg overflow-hidden">
                    <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-800 border-b border-gray-700">
                      <Code2 size={12} className="text-gray-400" />
                      <span className="text-xs text-gray-300 font-mono">{path}</span>
                    </div>
                    <pre className="text-xs text-gray-300 p-3 overflow-x-auto">
                      {String(content).substring(0, 800)}
                      {String(content).length > 800 ? "\n... (truncated)" : ""}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function PluginManager() {
  const [skills, setSkills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await api.client.get("/v2/plugins/skills");
        setSkills(res.data);
      } catch (e) {
        setError(e.response?.data?.detail || "Failed to load skills");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleGenerate = async (skillId, params) => {
    const res = await api.client.post("/v2/plugins/skills/generate", {
      skill_id: skillId,
      params,
    });
    return res.data;
  };

  const filtered = skills.filter((s) =>
    !searchTerm ||
    s.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    s.description?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <Loader2 size={24} className="animate-spin text-blue-500" />
    </div>
  );

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-bright">Skill Library</h1>
        <p className="text-sm text-muted mt-1">
          AI-powered code generators · {skills.length} skills available
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-950/40 border border-red-900 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      <div className="relative mb-6">
        <SearchIcon size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Search skills..."
          className="w-full pl-9 pr-4 py-2.5 border border-border rounded-xl text-sm bg-background text-bright focus:outline-none focus:border-blue-400"
        />
      </div>

      <div className="space-y-3">
        {filtered.map((skill) => (
          <SkillCard key={skill.id} skill={skill} onGenerate={handleGenerate} />
        ))}
        {filtered.length === 0 && (
          <p className="text-center text-muted py-12">No skills match your search.</p>
        )}
      </div>
    </div>
  );
}
