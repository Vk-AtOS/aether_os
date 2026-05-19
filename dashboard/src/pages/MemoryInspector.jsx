import { useState, useEffect } from "react";
import {
  Brain, RefreshCw, Loader2, Search, Clock, Tag,
  ArrowRight, Layers, Star, AlertCircle
} from "lucide-react";
import api from "../api";

function SimilarRunCard({ run }) {
  const sim = run.similarity || 0;
  const simColor = sim >= 0.8 ? "text-green-400" : sim >= 0.6 ? "text-amber-400" : "text-muted";
  const simBg = sim >= 0.8 ? "bg-green-950/40 border-green-900" : sim >= 0.6 ? "bg-amber-950/40 border-amber-900" : "bg-surface border-border";

  return (
    <div className={`rounded-xl border p-4 ${simBg}`}>
      <div className="flex items-start justify-between mb-2">
        <div>
          <p className="font-medium text-bright text-sm">{run.project || "Unnamed project"}</p>
          <p className="text-xs text-muted mt-0.5">{run.run_id?.substring(0, 8)}</p>
        </div>
        <div className={`text-lg font-bold ${simColor}`}>
          {Math.round(sim * 100)}%
        </div>
      </div>
      {run.domain && (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-panel border border-border rounded-full text-muted">
          <Tag size={10} /> {run.domain}
        </span>
      )}
      {run.hint && (
        <p className="text-xs text-muted mt-2 italic">"{run.hint}"</p>
      )}
    </div>
  );
}

function PreferenceRow({ k, v }) {
  return (
    <div className="flex items-start py-2 border-b border-border/50 last:border-0">
      <span className="text-sm font-mono text-blue-400 w-48 shrink-0">{k}</span>
      <span className="text-sm text-muted ml-4">
        {typeof v === "object" ? JSON.stringify(v) : String(v)}
      </span>
    </div>
  );
}

export default function MemoryInspector() {
  const [prefs, setPrefs] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [testInput, setTestInput] = useState("");
  const [searching, setSearching] = useState(false);
  const [matchResults, setMatchResults] = useState(null);
  const [cacheStats, setCacheStats] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const [prefsRes, cacheRes] = await Promise.all([
          api.client.get("/settings/preferences").catch(() => ({ data: {} })),
          api.client.get("/system/costs").catch(() => ({ data: {} })),
        ]);
        setPrefs(prefsRes.data || {});
        setCacheStats(cacheRes.data?.cache || null);
      } catch (e) {
        setError("Could not load memory data");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSearch = async () => {
    if (!testInput.trim()) return;
    setSearching(true);
    setMatchResults(null);
    try {
      const res = await api.client.post("/memory/search", {
        query: testInput,
        top_k: 5,
      }).catch(() => ({ data: { matches: [] } }));
      setMatchResults(res.data);
    } finally {
      setSearching(false);
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <Loader2 size={24} className="animate-spin text-blue-500" />
    </div>
  );

  const prefEntries = Object.entries(prefs).filter(([k]) => k !== "password" && k !== "token");

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-bright">Memory Inspector</h1>
        <p className="text-sm text-muted mt-1">
          Cross-run learning · Session preferences · LLM cache
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-amber-950/40 border border-amber-900 rounded-lg text-amber-400 text-sm flex items-center gap-2">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Memory system overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="bg-panel rounded-xl border border-border p-5">
          <div className="flex items-center gap-2 mb-3 text-purple-400">
            <Brain size={18} />
            <span className="font-semibold text-sm text-bright">Cross-Run Learning</span>
          </div>
          <p className="text-xs text-muted">
            AetherOS learns from every completed run. Similar future projects get
            context-injected hints about what worked.
          </p>
          <div className="mt-3 flex items-center gap-1 text-xs text-green-400">
            <Star size={12} /> Active — stored in fingerprint DB
          </div>
        </div>

        <div className="bg-panel rounded-xl border border-border p-5">
          <div className="flex items-center gap-2 mb-3 text-blue-400">
            <Layers size={18} />
            <span className="font-semibold text-sm text-bright">Session Memory</span>
          </div>
          <p className="text-xs text-muted">
            User preferences and settings are persisted across sessions in your
            profile — no need to repeat instructions.
          </p>
          <div className="mt-3 text-xs text-muted">
            {prefEntries.length} preference{prefEntries.length !== 1 ? "s" : ""} stored
          </div>
        </div>

        <div className="bg-panel rounded-xl border border-border p-5">
          <div className="flex items-center gap-2 mb-3 text-green-400">
            <RefreshCw size={18} />
            <span className="font-semibold text-sm text-bright">LLM Cache</span>
          </div>
          <p className="text-xs text-muted">
            Identical LLM calls are cached by content hash. Repeated prompts cost
            $0 — the biggest single cost lever.
          </p>
          {cacheStats && (
            <div className="mt-3 text-xs text-muted space-y-0.5">
              <div>{cacheStats.total_entries?.toLocaleString() || 0} cached responses</div>
              <div>{cacheStats.total_hits?.toLocaleString() || 0} total hits</div>
            </div>
          )}
        </div>
      </div>

      {/* Similarity search test */}
      <div className="bg-panel rounded-xl border border-border p-6 mb-6">
        <h2 className="font-semibold text-bright mb-1 flex items-center gap-2">
          <Search size={16} /> Test Memory Recall
        </h2>
        <p className="text-xs text-muted mb-4">
          Enter a project description to see what past runs AetherOS would inject as context.
        </p>
        <div className="flex gap-3">
          <textarea
            rows={2}
            value={testInput}
            onChange={(e) => setTestInput(e.target.value)}
            placeholder="e.g. Build a SaaS app with Stripe subscriptions and user authentication..."
            className="flex-1 px-3 py-2 border border-border rounded-xl text-sm bg-background text-bright focus:outline-none focus:border-blue-400 resize-none"
          />
          <button
            onClick={handleSearch}
            disabled={searching || !testInput.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded-xl text-sm hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2 self-start"
          >
            {searching ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            Recall
          </button>
        </div>

        {matchResults && (
          <div className="mt-4">
            {matchResults.matches?.length > 0 ? (
              <>
                <p className="text-xs font-semibold text-muted mb-3 uppercase tracking-wide">
                  {matchResults.matches.length} similar past run{matchResults.matches.length !== 1 ? "s" : ""} found
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {matchResults.matches.map((m, i) => (
                    <SimilarRunCard key={i} run={m} />
                  ))}
                </div>
              </>
            ) : (
              <div className="mt-3 flex items-center gap-2 text-muted text-sm">
                <Clock size={14} /> No similar runs found yet — memory builds as you complete more projects.
              </div>
            )}
          </div>
        )}
      </div>

      {/* User preferences */}
      <div className="bg-panel rounded-xl border border-border p-6">
        <h2 className="font-semibold text-bright mb-4 flex items-center gap-2">
          <Star size={16} /> Stored Preferences
        </h2>
        {prefEntries.length === 0 ? (
          <p className="text-sm text-muted">
            No preferences stored yet. Settings you configure (like preferred framework or domain) are automatically saved here.
          </p>
        ) : (
          <div>
            {prefEntries.map(([k, v]) => (
              <PreferenceRow key={k} k={k} v={v} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
