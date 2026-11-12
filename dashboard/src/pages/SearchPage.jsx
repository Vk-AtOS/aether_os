import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { Search, Loader2, FileCode, GitBranch, Clock, ChevronRight, X } from 'lucide-react';

const STATUS_COLORS = {
  completed: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  running:   'bg-accent/20 text-accent border-accent/30',
  failed:    'bg-red-500/20 text-red-400 border-red-500/30',
  interrupted: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
};

const Highlight = ({ text = '', query = '' }) => {
  if (!query || !text) return <span>{text}</span>;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return <span>{text}</span>;
  return (
    <span>
      {text.slice(0, idx)}
      <mark className="bg-accent/30 text-bright rounded px-0.5">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </span>
  );
};

const ResultCard = ({ result, query, onClick }) => {
  const statusCls = STATUS_COLORS[result.status] || 'bg-border/30 text-muted border-border';
  const ts = result.started_at ? new Date(result.started_at * 1000).toLocaleDateString() : '';
  return (
    <button onClick={() => onClick(result)}
      className="w-full text-left bg-panel border border-border hover:border-accent/40 rounded-xl p-4 transition-all group">
      <div className="flex items-start gap-3">
        <FileCode className="w-4 h-4 text-muted mt-0.5 shrink-0 group-hover:text-accent transition-colors" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-bright truncate">
              <Highlight text={result.project_name || result.id} query={query} />
            </span>
            <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${statusCls}`}>
              {result.status}
            </span>
          </div>
          {result.requirement && (
            <p className="text-xs text-muted mt-1 line-clamp-2">
              <Highlight text={result.requirement} query={query} />
            </p>
          )}
          <div className="flex items-center gap-3 mt-2 text-[10px] text-muted">
            {ts && <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{ts}</span>}
            {result.domain && <span className="flex items-center gap-1"><GitBranch className="w-3 h-3" />{result.domain}</span>}
          </div>
        </div>
        <ChevronRight className="w-4 h-4 text-muted shrink-0 group-hover:text-accent transition-colors" />
      </div>
    </button>
  );
};

const SearchPage = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQ = searchParams.get('q') || '';
  const [query, setQuery] = useState(initialQ);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(Boolean(initialQ.trim()));
  const [searched, setSearched] = useState(Boolean(initialQ.trim()));
  const [firstQ] = useState(initialQ); // the query the page was opened with
  const [total, setTotal] = useState(0);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  // Promise chain with no state set before the request: the mount effect calls it.
  const fetchResults = useCallback((q) => api.client.get('/factory/search', { params: { q, limit: 30 } })
    .then((res) => {
      const data = res.data;
      const items = data.results || data.items || (Array.isArray(data) ? data : []);
      setResults(items);
      setTotal(data.total || items.length);
    })
    .catch(() => setResults([]))
    .finally(() => setLoading(false)), []);

  const doSearch = (q) => {
    if (!q.trim()) { setResults([]); setSearched(false); return; }
    setLoading(true);
    setSearched(true);
    setSearchParams({ q });
    fetchResults(q);
  };

  useEffect(() => {
    inputRef.current?.focus();
    if (firstQ.trim()) fetchResults(firstQ);
  }, [firstQ, fetchResults]);

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') { setQuery(''); setResults([]); setSearched(false); }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    doSearch(query);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6 py-4">
      {/* Search bar */}
      <div className="space-y-3">
        <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
          <Search className="w-6 h-6 text-accent" /> Global Search
        </h1>
        <form onSubmit={handleSubmit} className="relative flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
            <input
              ref={inputRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search runs, requirements, projects…"
              className="w-full bg-panel border border-border rounded-xl pl-10 pr-10 py-3 text-sm text-bright placeholder-muted focus:outline-none focus:border-accent transition-colors"
            />
            {query && (
              <button type="button" onClick={() => { setQuery(''); setResults([]); setSearched(false); inputRef.current?.focus(); }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-bright transition-colors">
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
          <button type="submit"
            className="px-5 py-3 bg-accent hover:bg-accent/80 text-white text-sm font-semibold rounded-xl transition-colors flex items-center gap-2 shrink-0">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Search
          </button>
        </form>
        <p className="text-xs text-muted">Press <kbd className="font-mono bg-border/30 rounded px-1">Enter</kbd> to search · <kbd className="font-mono bg-border/30 rounded px-1">Esc</kbd> to clear</p>
      </div>

      {/* Results */}
      {loading && (
        <div className="flex items-center gap-2 text-muted text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Searching…
        </div>
      )}

      {!loading && searched && (
        <div className="space-y-4">
          <p className="text-xs text-muted">
            {total === 0 ? 'No results found' : `${total} result${total !== 1 ? 's' : ''} for "${query}"`}
          </p>
          {results.map((r, i) => (
            <ResultCard key={r.run_id || r.id || i} result={r} query={query}
              onClick={run => navigate(`/project/${run.run_id || run.id}`)} />
          ))}
        </div>
      )}

      {!searched && !loading && (
        <div className="text-center py-16 text-muted">
          <Search className="w-10 h-10 mx-auto mb-3 opacity-20" />
          <p className="text-sm">Search across all your factory runs and artifacts.</p>
          <p className="text-xs mt-1 opacity-60">Try a project name, requirement keyword, or domain.</p>
        </div>
      )}
    </div>
  );
};

export default SearchPage;
