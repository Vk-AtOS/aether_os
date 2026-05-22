import { useState, useEffect, useCallback } from "react";
import {
  Sparkles, Plus, Pencil, Trash2, Loader2, AlertCircle,
  CheckCircle2, X, RefreshCw, ChevronDown,
} from "lucide-react";
import api from "../api";

const DOMAINS = ["general", "fintech", "healthcare", "saas_multitenant", "ecommerce",
  "industrial", "logistics", "real_estate", "education", "social", "media"];
const TYPES   = ["manual", "learned", "override", "experimental"];

const EMPTY_FORM = {
  domain: "general", pattern_name: "", pattern_type: "manual",
  success_rate: 0.9, usage_count: 1, avg_quality_score: 8.0,
};

// ── Inline modal ──────────────────────────────────────────────────────────────
function PatternModal({ initial, onSave, onClose, saving }) {
  const [form, setForm] = useState(initial ?? EMPTY_FORM);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-panel border border-border rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="font-semibold text-bright">{initial ? "Edit Pattern" : "New Pattern"}</h2>
          <button onClick={onClose} className="text-muted hover:text-bright transition-colors"><X size={18} /></button>
        </div>

        <div className="p-6 space-y-4">
          {/* Domain */}
          <div>
            <label className="block text-xs font-medium text-muted mb-1">Domain</label>
            <div className="relative">
              <select value={form.domain} onChange={(e) => set("domain", e.target.value)}
                className="w-full appearance-none bg-background border border-border rounded-xl px-3 py-2 text-sm text-bright focus:outline-none focus:border-blue-500 pr-8">
                {DOMAINS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
              <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
            </div>
          </div>

          {/* Pattern name */}
          <div>
            <label className="block text-xs font-medium text-muted mb-1">Pattern Name</label>
            <input
              value={form.pattern_name}
              onChange={(e) => set("pattern_name", e.target.value)}
              placeholder="e.g. prefer_sqlalchemy_over_raw_sql"
              className="w-full bg-background border border-border rounded-xl px-3 py-2 text-sm text-bright focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* Pattern type */}
          <div>
            <label className="block text-xs font-medium text-muted mb-1">Type</label>
            <div className="relative">
              <select value={form.pattern_type} onChange={(e) => set("pattern_type", e.target.value)}
                className="w-full appearance-none bg-background border border-border rounded-xl px-3 py-2 text-sm text-bright focus:outline-none focus:border-blue-500 pr-8">
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
            </div>
          </div>

          {/* Numeric fields */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-muted mb-1">
                Success Rate <span className="text-muted/50">(0–1)</span>
              </label>
              <input type="number" min="0" max="1" step="0.01"
                value={form.success_rate}
                onChange={(e) => set("success_rate", parseFloat(e.target.value) || 0)}
                className="w-full bg-background border border-border rounded-xl px-3 py-2 text-sm text-bright focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted mb-1">Usage Count</label>
              <input type="number" min="1" step="1"
                value={form.usage_count}
                onChange={(e) => set("usage_count", parseInt(e.target.value, 10) || 1)}
                className="w-full bg-background border border-border rounded-xl px-3 py-2 text-sm text-bright focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted mb-1">
                Avg Quality <span className="text-muted/50">(0–10)</span>
              </label>
              <input type="number" min="0" max="10" step="0.1"
                value={form.avg_quality_score}
                onChange={(e) => set("avg_quality_score", parseFloat(e.target.value) || 0)}
                className="w-full bg-background border border-border rounded-xl px-3 py-2 text-sm text-bright focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-border flex justify-end gap-3">
          <button onClick={onClose}
            className="px-4 py-2 text-sm text-muted hover:text-bright transition-colors">
            Cancel
          </button>
          <button
            onClick={() => onSave(form)}
            disabled={saving || !form.pattern_name.trim()}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-xl disabled:opacity-50 flex items-center gap-2 transition-colors">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            {initial ? "Save changes" : "Create pattern"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Rate / quality indicator ──────────────────────────────────────────────────
function RateBar({ value, max = 1, color = "bg-blue-500" }) {
  const pct = Math.round((value / max) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-border rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-muted w-10 text-right">{value.toFixed(2)}</span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function GlobalPatternsTuning() {
  const [patterns, setPatterns] = useState([]);
  const [stats,    setStats]    = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  const [toast,    setToast]    = useState(null);
  const [modal,    setModal]    = useState(null); // null | "create" | { pattern }
  const [saving,   setSaving]   = useState(false);
  const [deleting, setDeleting] = useState(null);
  const [filter,   setFilter]   = useState("");

  const showToast = (msg, type = "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.client.get("/intelligence/global-insights");
      setPatterns(res.data?.global_patterns ?? []);
      setStats(res.data?.stats ?? []);
    } catch {
      setError("Could not load patterns — check your connection.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async (form) => {
    setSaving(true);
    try {
      await api.client.post("/intelligence/global-patterns", form);
      showToast("Pattern created successfully.");
      setModal(null);
      await load();
    } catch (e) {
      showToast(e?.response?.data?.detail ?? "Create failed.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async (form) => {
    setSaving(true);
    try {
      await api.client.put(`/intelligence/global-patterns/${modal.pattern.id}`, form);
      showToast("Pattern updated.");
      setModal(null);
      await load();
    } catch (e) {
      showToast(e?.response?.data?.detail ?? "Update failed.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this pattern? This cannot be undone.")) return;
    setDeleting(id);
    try {
      await api.client.delete(`/intelligence/global-patterns/${id}`);
      showToast("Pattern deleted.");
      setPatterns((p) => p.filter((x) => x.id !== id));
    } catch (e) {
      showToast(e?.response?.data?.detail ?? "Delete failed.", "error");
    } finally {
      setDeleting(null);
    }
  };

  const typeColor = {
    manual:       "bg-blue-950 text-blue-300 border-blue-800",
    learned:      "bg-green-950 text-green-300 border-green-800",
    override:     "bg-amber-950 text-amber-300 border-amber-800",
    experimental: "bg-purple-950 text-purple-300 border-purple-800",
  };

  const filtered = patterns.filter(
    (p) => !filter || p.pattern_name?.toLowerCase().includes(filter.toLowerCase())
      || p.domain?.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
            <Sparkles size={22} className="text-blue-400" /> Intelligence Tuning
          </h1>
          <p className="text-sm text-muted mt-1">
            Manually override or inject learned behaviors that guide the AI factory across all projects.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border text-muted hover:text-bright text-xs transition-colors disabled:opacity-50">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          <button onClick={() => setModal("create")}
            className="flex items-center gap-2 px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm transition-colors">
            <Plus size={15} /> Add Pattern
          </button>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className={`mb-4 p-3 rounded-lg border text-sm flex items-center gap-2 ${
          toast.type === "error"
            ? "bg-red-950/40 border-red-800 text-red-300"
            : "bg-green-950/40 border-green-800 text-green-300"
        }`}>
          {toast.type === "error" ? <AlertCircle size={14} /> : <CheckCircle2 size={14} />}
          {toast.msg}
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-amber-950/40 border border-amber-800 rounded-lg text-amber-300 text-sm flex items-center gap-2">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Domain stats strip */}
      {stats.length > 0 && (
        <div className="mb-6 flex gap-3 overflow-x-auto pb-1">
          {stats.slice(0, 8).map((s) => (
            <div key={s.domain}
              className="shrink-0 bg-panel border border-border rounded-xl px-4 py-2.5 text-center min-w-[90px]">
              <div className="text-base font-bold text-bright">{s.count}</div>
              <div className="text-xs text-muted mt-0.5 truncate max-w-[80px]">{s.domain}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filter */}
      <div className="mb-4">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by pattern name or domain…"
          className="w-full max-w-sm bg-background border border-border rounded-xl px-3 py-2 text-sm text-bright focus:outline-none focus:border-blue-500"
        />
      </div>

      {/* Table */}
      <div className="bg-panel border border-border rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-40 gap-2 text-muted text-sm">
            <Loader2 size={18} className="animate-spin" /> Loading patterns…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-muted text-sm gap-2">
            <Sparkles size={28} className="opacity-20" />
            {filter ? "No patterns match your filter." : 'No patterns yet — click "Add Pattern" to create one.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-surface/30">
                  {["Pattern Name", "Domain", "Type", "Success Rate", "Quality", "Usage", ""].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wide whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {filtered.map((p) => (
                  <tr key={p.id ?? p.pattern_name} className="hover:bg-surface/20 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs text-bright max-w-[200px] truncate">
                      {p.pattern_name}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted">{p.domain}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border font-medium ${typeColor[p.pattern_type] ?? "bg-panel text-muted border-border"}`}>
                        {p.pattern_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 min-w-[140px]">
                      <RateBar value={p.success_rate ?? 0} max={1}
                        color={p.success_rate >= 0.8 ? "bg-green-500" : p.success_rate >= 0.5 ? "bg-amber-500" : "bg-red-500"} />
                    </td>
                    <td className="px-4 py-3 min-w-[130px]">
                      <RateBar value={p.avg_quality_score ?? 0} max={10} color="bg-blue-500" />
                    </td>
                    <td className="px-4 py-3 text-xs text-muted tabular-nums">{p.usage_count ?? 0}×</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 justify-end">
                        <button
                          onClick={() => setModal({ pattern: p, initial: { ...p } })}
                          title="Edit"
                          className="p-1.5 rounded-lg text-muted hover:text-bright hover:bg-surface transition-colors">
                          <Pencil size={13} />
                        </button>
                        <button
                          onClick={() => handleDelete(p.id)}
                          disabled={deleting === p.id}
                          title="Delete"
                          className="p-1.5 rounded-lg text-muted hover:text-red-400 hover:bg-red-950/30 transition-colors disabled:opacity-50">
                          {deleting === p.id
                            ? <Loader2 size={13} className="animate-spin" />
                            : <Trash2 size={13} />}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="mt-3 text-xs text-muted/50">
        {filtered.length} of {patterns.length} pattern{patterns.length !== 1 ? "s" : ""}
        {" · "}Admin-only — changes take effect on the next factory run.
      </p>

      {/* Modal */}
      {modal === "create" && (
        <PatternModal
          initial={null}
          onSave={handleCreate}
          onClose={() => setModal(null)}
          saving={saving}
        />
      )}
      {modal?.pattern && (
        <PatternModal
          initial={modal.initial}
          onSave={handleUpdate}
          onClose={() => setModal(null)}
          saving={saving}
        />
      )}
    </div>
  );
}
