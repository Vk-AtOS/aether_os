import { useState, useEffect, useCallback } from "react";
import { TrendingDown, DollarSign, Zap, Database, Target, RefreshCw } from "lucide-react";
import api from "../api";
import { apiError } from '../apiError';

const COST_TARGET = 0.35;

function MetricCard({ icon: Icon, label, value, sub, color = "blue", trend }) {
  const colors = {
    blue: "bg-blue-950/40 text-blue-400 border-blue-900",
    green: "bg-green-950/40 text-green-400 border-green-900",
    amber: "bg-amber-950/40 text-amber-400 border-amber-900",
    red: "bg-red-950/40 text-red-400 border-red-900",
  };
  return (
    <div className={`rounded-xl border p-5 ${colors[color]}`}>
      <div className="flex items-center gap-2 mb-3">
        <Icon size={18} />
        <span className="text-sm font-medium opacity-80">{label}</span>
      </div>
      <div className="text-2xl font-bold">{value}</div>
      {sub && <div className="text-xs mt-1 opacity-70">{sub}</div>}
      {trend !== undefined && (
        <div className={`text-xs mt-1 font-medium ${trend < 0 ? "text-green-400" : "text-red-400"}`}>
          {trend < 0 ? `↓ ${Math.abs(trend)}%` : `↑ ${trend}%`} vs last month
        </div>
      )}
    </div>
  );
}

function CostBar({ label, value, max, target }) {
  const pct = Math.min((value / max) * 100, 100);
  const atTarget = value <= target;
  return (
    <div className="mb-4">
      <div className="flex justify-between text-sm mb-1">
        <span className="text-muted">{label}</span>
        <span className={`font-mono font-semibold ${atTarget ? "text-green-400" : "text-amber-400"}`}>
          ${value.toFixed(3)}
        </span>
      </div>
      <div className="h-2 rounded-full bg-border/30 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${atTarget ? "bg-green-500" : "bg-amber-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between text-xs text-muted mt-1">
        <span>$0</span>
        <span className="text-green-400">target ${target}</span>
        <span>${max.toFixed(2)}</span>
      </div>
    </div>
  );
}

export default function CostDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Promise chain with no state set before the request: this runs from an effect.
  const load = useCallback(() => api.client.get("/system/costs")
    .then((res) => { setData(res.data); setError(null); })
    .catch((e) => setError(apiError(e) || "Failed to load cost data"))
    .finally(() => setLoading(false)), []);

  useEffect(() => { load(); }, [load]);

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <RefreshCw size={24} className="animate-spin text-blue-500" />
    </div>
  );

  if (error) return (
    <div className="p-6 text-red-400 bg-red-950/40 rounded-xl">{error}</div>
  );

  const m = data?.this_month || {};
  const targets = data?.targets || {};
  const cache = data?.cache || {};
  const history = data?.history || [];

  const hitRate = ((m.cache_hit_rate || 0) * 100).toFixed(1);
  const costPerRun = m.cost_per_run || 0;
  const reductionNeeded = targets.reduction_needed_pct || 0;
  const onTarget = costPerRun <= COST_TARGET;

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-bright">Cost Dashboard</h1>
          <p className="text-sm text-muted mt-1">
            API cost tracking · Target: ${COST_TARGET}/run
          </p>
        </div>
        <button onClick={load} className="flex items-center gap-2 px-4 py-2 bg-panel border border-border rounded-lg text-sm text-muted hover:bg-surface">
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* Target progress banner */}
      <div className={`rounded-xl p-4 mb-6 flex items-center gap-4 ${onTarget ? "bg-green-950/40 border border-green-900" : "bg-amber-950/40 border border-amber-900"}`}>
        <Target size={24} className={onTarget ? "text-green-400" : "text-amber-400"} />
        <div>
          <p className={`font-semibold ${onTarget ? "text-green-400" : "text-amber-400"}`}>
            {onTarget
              ? `✓ On target — $${costPerRun.toFixed(3)}/run (goal: $${COST_TARGET})`
              : `${reductionNeeded}% cost reduction still needed to hit $${COST_TARGET}/run target`}
          </p>
          <p className="text-xs opacity-70 mt-0.5 text-muted">
            At scale (80K users, 1% DAU): {onTarget
              ? `~$${(costPerRun * 800).toFixed(0)}/day`
              : `currently ~$${(costPerRun * 800).toFixed(0)}/day vs target $${(COST_TARGET * 800).toFixed(0)}/day`}
          </p>
        </div>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <MetricCard
          icon={DollarSign}
          label="Cost / Run"
          value={`$${costPerRun.toFixed(4)}`}
          sub={`vs $${COST_TARGET} target`}
          color={onTarget ? "green" : "amber"}
        />
        <MetricCard
          icon={Zap}
          label="Cache Hit Rate"
          value={`${hitRate}%`}
          sub={`${m.cache_hits || 0} hits / ${(m.cache_hits || 0) + (m.cache_misses || 0)} calls`}
          color={parseFloat(hitRate) >= 25 ? "green" : "blue"}
        />
        <MetricCard
          icon={Database}
          label="Tokens This Month"
          value={((m.input_tokens || 0) + (m.output_tokens || 0)).toLocaleString()}
          sub={`${m.runs || 0} runs · ${Math.round(((m.input_tokens || 0) + (m.output_tokens || 0)) / Math.max(m.runs || 1, 1)).toLocaleString()} avg/run`}
          color="blue"
        />
        <MetricCard
          icon={TrendingDown}
          label="Monthly Spend"
          value={`$${(m.estimated_cost_usd || 0).toFixed(2)}`}
          sub={`${Math.round(m.budget_used_pct || 0)}% of plan budget`}
          color={(m.budget_used_pct || 0) > 85 ? "red" : "green"}
        />
      </div>

      {/* Cost per run chart */}
      <div className="bg-panel border border-border rounded-xl p-6 mb-6">
        <h2 className="font-semibold text-bright mb-4">Cost Per Run — Monthly Trend</h2>
        {history.length === 0 ? (
          <p className="text-muted text-sm">No historical data yet</p>
        ) : (
          history.map((h) => (
            <CostBar
              key={h.month}
              label={h.month}
              value={h.cost_per_run}
              max={Math.max(...history.map((x) => x.cost_per_run), 3)}
              target={COST_TARGET}
            />
          ))
        )}
      </div>

      {/* Cost reduction levers */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-panel border border-border rounded-xl p-5">
          <h3 className="font-semibold text-bright mb-3 flex items-center gap-2">
            <Zap size={16} className="text-yellow-500" /> Semantic Cache
          </h3>
          <div className="text-3xl font-bold text-bright mb-1">{hitRate}%</div>
          <p className="text-xs text-muted">hit rate (target: 25%+)</p>
          <div className="mt-3 text-xs text-muted space-y-1">
            <div>{cache.total_entries?.toLocaleString() || 0} cached responses</div>
            <div>{cache.total_hits?.toLocaleString() || 0} total cache hits</div>
          </div>
        </div>

        <div className="bg-panel border border-border rounded-xl p-5">
          <h3 className="font-semibold text-bright mb-3 flex items-center gap-2">
            <TrendingDown size={16} className="text-blue-400" /> Prompt Caching
          </h3>
          <div className="text-3xl font-bold text-bright mb-1">90%</div>
          <p className="text-xs text-muted">discount on cached system tokens</p>
          <div className="mt-3 text-xs text-muted space-y-1">
            <div>Prompt caching enabled</div>
            <div>System prompt cached after 1st call</div>
          </div>
        </div>

        <div className="bg-panel border border-border rounded-xl p-5">
          <h3 className="font-semibold text-bright mb-3 flex items-center gap-2">
            <Database size={16} className="text-purple-400" /> Context Compression
          </h3>
          <div className="text-3xl font-bold text-bright mb-1">~70%</div>
          <p className="text-xs text-muted">token reduction when triggered</p>
          <div className="mt-3 text-xs text-muted space-y-1">
            <div>AI-powered summarization</div>
            <div>Triggers at 6K+ token context</div>
          </div>
        </div>
      </div>

      {/* Budget usage */}
      <div className="bg-panel border border-border rounded-xl p-6">
        <h2 className="font-semibold text-bright mb-4">Monthly Budget</h2>
        <div className="flex items-center justify-between mb-2 text-sm text-muted">
          <span>Tokens used this month</span>
          <span className="font-mono">{((m.input_tokens || 0) + (m.output_tokens || 0)).toLocaleString()} / {(m.budget_tokens || 500000).toLocaleString()}</span>
        </div>
        <div className="h-3 rounded-full bg-border/30 overflow-hidden mb-1">
          <div
            className={`h-full rounded-full transition-all ${
              (m.budget_used_pct || 0) > 85 ? "bg-red-500" :
              (m.budget_used_pct || 0) > 60 ? "bg-amber-500" : "bg-blue-500"
            }`}
            style={{ width: `${Math.min(m.budget_used_pct || 0, 100)}%` }}
          />
        </div>
        <p className="text-xs text-muted mt-1">
          {(m.budget_used_pct || 0).toFixed(1)}% used · Resets on the 1st of next month
        </p>
      </div>
    </div>
  );
}
