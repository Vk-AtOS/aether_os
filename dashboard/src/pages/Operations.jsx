import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Briefcase, RefreshCw, Loader2, ChevronDown, ChevronRight, Search } from 'lucide-react';
import { api } from '../api';
import EmptyState from '../components/EmptyState';

// One honest status per agent, as reported by Velaris itself.
const STATUS = {
  real:            { label: 'Working',         dot: 'bg-emerald-400', text: 'text-emerald-400' },
  rule_based:      { label: 'Rule-based',      dot: 'bg-sky-400',     text: 'text-sky-400' },
  not_implemented: { label: 'Not implemented', dot: 'bg-slate-600',   text: 'text-muted' },
};
const ORDER = ['real', 'rule_based', 'not_implemented'];

const prettyName = (name) => name.replace(/^_/, '').replace(/_/g, ' ');

const StatusBar = ({ counts, total }) => (
  <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-border/30" aria-hidden="true">
    {ORDER.map((s) => (
      <div key={s} className={STATUS[s].dot} style={{ width: `${total ? (counts[s] / total) * 100 : 0}%` }} />
    ))}
  </div>
);

const Department = ({ dept, query }) => {
  const [open, setOpen] = useState(false);
  const agents = useMemo(
    () => dept.agents.filter((a) => a.name.toLowerCase().includes(query)),
    [dept.agents, query],
  );
  if (query && agents.length === 0) return null;
  const expanded = open || Boolean(query);
  return (
    <div className="bg-panel border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={expanded}
        className="w-full px-5 py-4 text-left hover:bg-surface/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          {expanded
            ? <ChevronDown className="w-3.5 h-3.5 text-muted shrink-0" aria-hidden="true" />
            : <ChevronRight className="w-3.5 h-3.5 text-muted shrink-0" aria-hidden="true" />}
          <span className="flex-1 text-sm font-semibold text-bright capitalize">{prettyName(dept.name)}</span>
          <span className="text-xs text-muted tabular-nums">
            {dept.counts.real + dept.counts.rule_based} of {dept.total} usable
          </span>
        </div>
        <div className="mt-3 pl-6"><StatusBar counts={dept.counts} total={dept.total} /></div>
      </button>
      {expanded && (
        <ul className="border-t border-border px-5 py-3 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5">
          {agents.map((a) => (
            <li key={a.name} className="flex items-center gap-2 min-w-0">
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${STATUS[a.status].dot}`} aria-hidden="true" />
              <span className="text-xs font-mono text-bright/90 truncate">{a.name}</span>
              <span className={`ml-auto text-[10px] shrink-0 ${STATUS[a.status].text}`}>{STATUS[a.status].label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

const Operations = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  // State is only set after the request settles, so the effect below never
  // triggers a synchronous re-render.
  const load = useCallback(async () => {
    try {
      const res = await api.getVelarisInventory();
      setData(res.data);
      setError('');
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load the operations platform.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
            <Briefcase className="w-6 h-6 text-accent" aria-hidden="true" /> Operations
          </h1>
          <p className="text-sm text-muted mt-1">
            Velaris, department by department. Each agent shows what it can really do today.
          </p>
        </div>
        <button
          onClick={() => { setLoading(true); load(); }}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 text-xs font-bold text-muted hover:text-bright border border-border rounded-lg disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Refresh
        </button>
      </header>

      {error && (
        <div role="alert" className="bg-panel border border-danger/40 rounded-xl px-5 py-4 text-sm text-danger">{error}</div>
      )}

      {data && (
        <>
          <section className="bg-panel border border-border rounded-xl px-5 py-4 space-y-3" aria-label="Summary">
            <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
              <div>
                <span className="text-3xl font-bold text-bright tabular-nums">{data.total}</span>
                <span className="text-sm text-muted ml-2">agents in {data.departments.length} departments</span>
              </div>
              {ORDER.map((s) => (
                <div key={s} className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${STATUS[s].dot}`} aria-hidden="true" />
                  <span className="text-sm text-bright tabular-nums">{data.totals[s]}</span>
                  <span className="text-xs text-muted">{STATUS[s].label}</span>
                </div>
              ))}
            </div>
            <StatusBar counts={data.totals} total={data.total} />
          </section>

          <div className="relative">
            <Search className="w-4 h-4 text-muted absolute left-3 top-1/2 -translate-y-1/2" aria-hidden="true" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value.toLowerCase())}
              placeholder="Find an agent"
              aria-label="Find an agent"
              className="w-full bg-surface border border-border rounded-lg pl-9 pr-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
            />
          </div>

          <div className="space-y-3">
            {data.departments.map((d) => <Department key={d.name} dept={d} query={query} />)}
          </div>
        </>
      )}

      {!data && !loading && !error && (
        <EmptyState icon={Briefcase} title="No departments found" description="Velaris returned an empty inventory." />
      )}
    </div>
  );
};

export default Operations;
