import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { Bot, Play, RefreshCw, Loader2, CheckCircle2, XCircle, ChevronDown, ChevronRight, Cpu, Zap } from 'lucide-react';
import EmptyState from '../components/EmptyState';

const KIND_COLORS = {
  code:     'text-blue-400',
  security: 'text-red-400',
  review:   'text-yellow-400',
  deploy:   'text-purple-400',
  test:     'text-cyan-400',
  docs:     'text-emerald-400',
  default:  'text-accent',
};

const AGENT_TIMEOUT_MS = 60_000;

const AgentCard = ({ agent, onRun, recentRuns = [] }) => {
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [projectPath, setProjectPath] = useState('.');
  const [filePath, setFilePath] = useState('');
  const [workflowId, setWorkflowId] = useState('');

  const kindColor = KIND_COLORS[agent.kind] ?? KIND_COLORS.default;

  const run = async () => {
    setRunning(true);
    setError('');
    setResult(null);
    const timeoutId = setTimeout(() => {
      setError('Agent is taking longer than expected (60 s). It may still be running in the background.');
      setRunning(false);
    }, AGENT_TIMEOUT_MS);
    try {
      const res = await api.client.post(`/agents/${agent.name}/run`, {
        project_path: projectPath || '.',
        file_path: filePath || undefined,
        workflow_id: workflowId || undefined,
        metadata: {},
      });
      clearTimeout(timeoutId);
      setResult(res.data);
    } catch (e) {
      clearTimeout(timeoutId);
      setError(e.response?.data?.detail || 'Agent run failed');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="bg-panel border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-3 px-5 py-4 hover:bg-surface/50 transition-colors text-left"
      >
        {open ? <ChevronDown className="w-3.5 h-3.5 text-muted shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-muted shrink-0" />}
        <Bot className={`w-4 h-4 shrink-0 ${kindColor}`} />
        <div className="flex-1 min-w-0">
          <span className="text-sm font-semibold text-bright">{agent.name}</span>
        </div>
        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${kindColor} border-current/30 bg-current/10`}>
          {agent.kind}
        </span>
      </button>

      {open && (
        <div className="px-5 pb-5 border-t border-border space-y-4 pt-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Project Path</label>
              <input
                value={projectPath}
                onChange={e => setProjectPath(e.target.value)}
                placeholder="."
                className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono text-bright focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">File Path (optional)</label>
              <input
                value={filePath}
                onChange={e => setFilePath(e.target.value)}
                placeholder="src/main.py"
                className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono text-bright focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Run ID (optional)</label>
              {recentRuns.length > 0 ? (
                <select
                  value={workflowId}
                  onChange={e => setWorkflowId(e.target.value)}
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono text-bright focus:outline-none focus:border-accent"
                >
                  <option value="">— none —</option>
                  {recentRuns.map(r => (
                    <option key={r.id} value={r.id}>{r.id.slice(0, 8)} · {r.app_name || 'untitled'}</option>
                  ))}
                </select>
              ) : (
                <input
                  value={workflowId}
                  onChange={e => setWorkflowId(e.target.value)}
                  placeholder="run-id or workflow-id"
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs font-mono text-bright focus:outline-none focus:border-accent"
                />
              )}
            </div>
          </div>

          {error && <p className="text-xs text-danger">{error}</p>}

          <button
            onClick={run}
            disabled={running}
            className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors"
          >
            {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            {running ? 'Running…' : `Run ${agent.name}`}
          </button>

          {result && (
            <div className={`rounded-xl border p-4 space-y-3 ${result.status === 'success' || result.status === 'completed' ? 'bg-emerald-500/5 border-emerald-500/30' : 'bg-yellow-500/5 border-yellow-500/30'}`}>
              <div className="flex items-center gap-2">
                {result.status === 'success' || result.status === 'completed'
                  ? <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  : <XCircle className="w-4 h-4 text-yellow-400" />}
                <span className="text-xs font-bold text-bright">{result.status}</span>
                {result.duration_ms != null && (
                  <span className="ml-auto text-[10px] text-muted font-mono">{result.duration_ms}ms</span>
                )}
              </div>
              {result.message && <p className="text-xs text-bright/90">{result.message}</p>}
              {result.payload && Object.keys(result.payload).length > 0 && (
                <details>
                  <summary className="text-[10px] font-bold text-muted cursor-pointer hover:text-bright">Payload</summary>
                  <pre className="mt-2 text-[11px] font-mono text-bright/80 bg-surface rounded-lg p-3 overflow-auto max-h-48 whitespace-pre-wrap leading-relaxed">
                    {JSON.stringify(result.payload, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const Agents = () => {
  const [agents, setAgents] = useState([]);
  const [recentRuns, setRecentRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [agentsRes, runsRes] = await Promise.all([
        api.client.get('/agents'),
        api.listRuns(1, 20).catch(() => ({ data: { runs: [] } })),
      ]);
      setAgents(agentsRes.data?.agents ?? []);
      setRecentRuns(runsRes.data?.runs ?? []);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = agents.filter(a =>
    !filter || a.name.toLowerCase().includes(filter.toLowerCase()) || a.kind.toLowerCase().includes(filter.toLowerCase())
  );

  const kinds = [...new Set(agents.map(a => a.kind))].sort();

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
            <Bot className="w-6 h-6 text-accent" /> Agents
          </h1>
          <p className="text-sm text-muted mt-1">Browse and run registered AI agents. {agents.length} agents available.</p>
        </div>
        <button
          onClick={load}
          className="p-2 text-muted hover:text-bright border border-border rounded-lg transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </header>

      {error && (
        <div className="p-4 bg-danger/10 border border-danger/30 rounded-xl text-sm text-danger">{error}</div>
      )}

      {/* Kind summary */}
      {kinds.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setFilter('')}
            className={`text-[10px] font-bold px-3 py-1 rounded-full border uppercase tracking-wider transition-colors ${!filter ? 'bg-accent text-white border-accent' : 'border-border text-muted hover:text-bright'}`}
          >
            All ({agents.length})
          </button>
          {kinds.map(k => (
            <button
              key={k}
              onClick={() => setFilter(filter === k ? '' : k)}
              className={`text-[10px] font-bold px-3 py-1 rounded-full border uppercase tracking-wider transition-colors ${filter === k ? 'bg-accent text-white border-accent' : 'border-border text-muted hover:text-bright'}`}
            >
              {k} ({agents.filter(a => a.kind === k).length})
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 gap-3 text-muted">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Loading agents…</span>
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={Cpu}
          title={`No agents found${filter ? ` for kind "${filter}"` : ''}`}
          description="Agents are registered via the agent registry in the backend."
        />
      ) : (
        <div className="space-y-2">
          {filtered.map(agent => (
            <AgentCard key={agent.name} agent={agent} recentRuns={recentRuns} />
          ))}
        </div>
      )}
    </div>
  );
};

export default Agents;
