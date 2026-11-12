import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { ShieldCheck, Search, RefreshCw, Download, ChevronLeft, ChevronRight } from 'lucide-react';

// The server resolves pseudonymous references; a person erased on request comes back as
// "[erased]" and a value that could not be recorded safely as "[withheld]". Never show
// anything else that looks like a stored reference.
const personal = (v) => {
  if (!v) return '—';
  if (v === '[erased]') return <em title="This person's data was erased on request" className="not-italic text-muted/70">erased</em>;
  if (v === '[withheld]') return <em title="Not recorded: it could not be stored safely" className="not-italic text-muted/70">not recorded</em>;
  if (/^sub_[0-9a-f]{32}$/.test(v)) return <em title="A reference that could not be resolved" className="not-italic text-muted/70">erased</em>;
  return v;
};

const AuditLogs = () => {
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);
  const [search, setSearch] = useState('');
  const [exportError, setExportError] = useState(null);
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [userFilter, setUserFilter] = useState('');
  const LIMIT = 50;

  // Promise chain with no state set before the request: this runs from an effect.
  const fetchLogs = useCallback(() => {
    const params = { page, limit: LIMIT };
    if (search) params.action = search;
    if (fromDate) params.from_date = fromDate;
    if (toDate) params.to_date = toDate;
    if (userFilter) params.user_id = userFilter;
    return api.client.get('/audit/logs', { params })
      .then((res) => {
        const data = res.data;
        if (Array.isArray(data)) {
          setLogs(data);
          setTotal(data.length);
        } else {
          setLogs(data.items ?? data.logs ?? []);
          setTotal(data.total ?? 0);
        }
        setFetchError(null);
      })
      .catch((e) => {
        console.warn('Failed to load audit logs:', e);
        setLogs([]);
        setFetchError('Failed to load audit logs. Please refresh.');
      })
      .finally(() => setLoading(false));
  }, [page, search, fromDate, toDate, userFilter]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const handleExport = async () => {
    setExportError(null);
    try {
      const res = await api.client.get('/audit/logs/export', { params: { format: 'csv' }, responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setExportError('Export failed. Check your connection and try again.');
    }
  };

  const actionBadge = (action) => {
    const colors = {
      login: 'bg-blue-900/40 text-blue-300',
      logout: 'bg-gray-800 text-gray-400',
      register: 'bg-green-900/40 text-green-300',
      delete: 'bg-red-900/40 text-red-300',
      update: 'bg-yellow-900/40 text-yellow-300',
      create: 'bg-indigo-900/40 text-indigo-300',
    };
    const key = Object.keys(colors).find(k => action?.toLowerCase().includes(k)) || '';
    return (
      <span className={`px-2 py-0.5 text-[11px] font-mono rounded ${colors[key] || 'bg-gray-800 text-gray-400'}`}>
        {action || '—'}
      </span>
    );
  };

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ShieldCheck className="w-6 h-6 text-accent" />
          <div>
            <h1 className="text-2xl font-bold text-bright">Audit Logs</h1>
            <p className="text-sm text-muted">{total} events recorded</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 px-3 py-2 text-sm bg-panel border border-border rounded-lg text-muted hover:text-bright transition-colors"
          >
            <Download className="w-4 h-4" /> Export CSV
          </button>
          <button
            onClick={fetchLogs}
            className="flex items-center gap-1.5 px-3 py-2 text-sm bg-panel border border-border rounded-lg text-muted hover:text-bright transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </header>

      {/* Fetch error */}
      {fetchError && (
        <div className="flex items-center gap-3 p-3 rounded-lg border bg-red-500/10 border-red-500/30 text-danger text-sm">
          {fetchError}
          <button onClick={() => setFetchError(null)} className="ml-auto text-xs text-muted hover:text-bright">✕</button>
        </div>
      )}

      {/* Export error */}
      {exportError && (
        <div className="flex items-center gap-3 p-3 rounded-lg border bg-red-500/10 border-red-500/30 text-danger text-sm">
          {exportError}
          <button onClick={() => setExportError(null)} className="ml-auto text-xs text-muted hover:text-bright">✕</button>
        </div>
      )}

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
        <input
          type="text"
          placeholder="Filter by action…"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(1); }}
          className="w-full pl-9 pr-4 py-2 bg-panel border border-border rounded-lg text-sm text-bright placeholder-muted focus:outline-none focus:ring-1 focus:ring-accent"
        />
      </div>

      {/* Date range and user filter */}
      <div className="flex flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted whitespace-nowrap">From:</label>
          <input
            type="date"
            value={fromDate}
            onChange={e => { setFromDate(e.target.value); setPage(1); }}
            className="bg-panel border border-border rounded-lg px-3 py-1.5 text-xs text-bright focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted whitespace-nowrap">To:</label>
          <input
            type="date"
            value={toDate}
            onChange={e => { setToDate(e.target.value); setPage(1); }}
            className="bg-panel border border-border rounded-lg px-3 py-1.5 text-xs text-bright focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <input
          type="text"
          placeholder="Filter by user ID…"
          value={userFilter}
          onChange={e => { setUserFilter(e.target.value); setPage(1); }}
          className="bg-panel border border-border rounded-lg px-3 py-1.5 text-xs text-bright placeholder-muted focus:outline-none focus:ring-1 focus:ring-accent min-w-[160px]"
        />
        {(fromDate || toDate || userFilter) && (
          <button
            onClick={() => { setFromDate(''); setToDate(''); setUserFilter(''); setPage(1); }}
            className="text-xs text-muted hover:text-bright transition-colors border border-border rounded-lg px-3 py-1.5"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Table */}
      <div className="panel overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-muted text-xs uppercase tracking-wider">
              <th className="px-4 py-3">Timestamp</th>
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Resource</th>
              <th className="px-4 py-3">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading ? (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-muted">Loading…</td></tr>
            ) : logs.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-muted">No audit events found</td></tr>
            ) : logs.map((log) => (
              <tr key={log.id} className="hover:bg-white/[0.02] transition-colors">
                <td className="px-4 py-3 text-muted font-mono text-xs">
                  {log.created_at
                    ? new Date(log.created_at * 1000).toLocaleString()
                    : '—'}
                </td>
                <td className="px-4 py-3 text-bright truncate max-w-[160px]">{log.user_id || '—'}</td>
                <td className="px-4 py-3">{actionBadge(log.action)}</td>
                <td className="px-4 py-3 text-muted text-xs">
                  {log.resource_type && <span className="font-mono">{log.resource_type}</span>}
                  {log.resource_id && <span className="text-muted/50"> · {log.resource_id.slice(0, 8)}</span>}
                </td>
                <td className="px-4 py-3 text-muted font-mono text-xs">{personal(log.ip_address)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted">Page {page} of {totalPages}</p>
          <div className="flex gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
              className="p-2 rounded-lg border border-border text-muted hover:text-bright disabled:opacity-40 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
              className="p-2 rounded-lg border border-border text-muted hover:text-bright disabled:opacity-40 transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default AuditLogs;
