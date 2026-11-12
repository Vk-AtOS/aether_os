import React, { useState, useMemo } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { api } from '../api';
import RerunDropdown from '../components/RerunDropdown';
import ConfirmDialog from '../components/ConfirmDialog';
import { StatusBadge } from '../components/ui/StatusBadge';
import { Eye, Search, Clock, Rocket, Pause, Play, X, Loader2 } from 'lucide-react';
import { useRuns } from '../contexts/useRuns';
import { useToast } from '../contexts/useToast';
import { isPreviewUrl, openPreviewInTab } from '../previewSession';
import { apiError } from '../apiError';
import { SkeletonTable } from '../components/Skeleton';
import { PHASES } from '../components/project/projectConstants';

// The stage list is shared with the project page so the two can never disagree.
const getCompletedCount = (run) => {
  if (run.status === 'completed') return PHASES.length;
  const phases = run.phases || {};
  const completed = PHASES.filter((p) => {
    const st = phases[p]?.status;
    return st === 'passed' || st === 'completed' || st === 'timeout';
  }).length;
  if (run.current_phase && run.current_phase !== 'pipeline') {
    const idx = PHASES.indexOf(run.current_phase);
    return Math.max(completed, idx >= 0 ? idx : 0);
  }
  return completed;
};

// Gradient progress bar
const ProgressBar = ({ run }) => {
  const completed = getCompletedCount(run);
  const total = PHASES.length;
  const pct = Math.round((completed / total) * 100);
  const isRunning = run.status === 'running';

  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 bg-white/[0.06] rounded-full h-1.5">
        <div
          className={`h-1.5 rounded-full transition-all duration-500 ${
            isRunning
              ? 'bg-gradient-to-r from-blue-500 to-violet-500'
              : run.status === 'completed' || run.status === 'passed'
              ? 'bg-gradient-to-r from-emerald-500 to-teal-400'
              : 'bg-gradient-to-r from-violet-500 to-indigo-400'
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-slate-500 min-w-[40px] text-right font-mono">{completed}/{total}</span>
    </div>
  );
};

const EmptyState = ({ onNewProject }) => (
  <div className="flex flex-col items-center justify-center py-24 space-y-6">
    <div className="w-16 h-16 rounded-2xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center text-3xl">
      ⚡
    </div>
    <div className="text-center space-y-2">
      <h3 className="text-lg font-bold text-white">No projects yet</h3>
      <p className="text-slate-500 text-sm max-w-xs">
        Start your first factory run and AetherOS will generate a complete production-ready codebase.
      </p>
    </div>
    <button
      onClick={onNewProject}
      className="flex items-center gap-2 bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 transition-all text-white font-semibold px-6 py-3 rounded-xl shadow-lg shadow-violet-500/25"
    >
      <Rocket className="w-4 h-4" />
      <span>Start First Project</span>
    </button>
  </div>
);

const ProjectsList = () => {
  const ctx = useOutletContext() || {};
  const onNewProject = ctx.openNewProject || (() => {});
  const { runs, loading, refresh, hasMore, loadMore, total } = useRuns();
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [domainFilter, setDomainFilter] = useState('');
  const [actionLoading, setActionLoading] = useState({});
  const [confirmCancel, setConfirmCancel] = useState(null);
  const navigate = useNavigate();
  const toast = useToast();

  const doAction = async (e, runId, action) => {
    if (e) e.stopPropagation();
    setActionLoading((prev) => ({ ...prev, [runId]: action }));
    try {
      if (action === 'pause')  await api.pauseRun(runId);
      if (action === 'resume') await api.resumeRun(runId);
      if (action === 'cancel') await api.cancelRun(runId);
      if (action === 'restart') await api.restartRun(runId);
      refresh();
    } catch (err) {
      toast(`Could not ${action} the run: ${apiError(err) || err.message}`, 'error', 6000);
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[runId]; return n; });
    }
  };

  const doRerunPhase = async (runId, fromPhase) => {
    setActionLoading((prev) => ({ ...prev, [runId]: 'rerun' }));
    try {
      const res = await api.rerunFromPhase(runId, fromPhase);
      navigate(`/project/${res.data.run_id}`);
    } catch (err) {
      toast(`Could not start the run: ${apiError(err) || err.message}`, 'error', 6000);
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[runId]; return n; });
    }
  };

  const doEditRestart = async (runId, run, editedReq) => {
    setActionLoading((prev) => ({ ...prev, [runId]: 'rerun' }));
    try {
      const res = await api.startPipeline({
        raw_input: editedReq,
        project_name: run.project_name,
        domain: run.domain || 'general',
        client_id: run.client_id || 'client-001',
      });
      navigate(`/project/${res.data.run_id}`);
    } catch (err) {
      toast(`Could not start the run: ${apiError(err) || err.message}`, 'error', 6000);
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[runId]; return n; });
    }
  };

  const domains = useMemo(
    () => [...new Set(runs.map(r => r.domain).filter(Boolean))].sort(),
    [runs]
  );

  const filtered = useMemo(() => {
    const term = searchTerm.toLowerCase();
    return runs.filter((run) => {
      const matchText = run.project_name?.toLowerCase().includes(term) || (run.run_id || run.id)?.toLowerCase().includes(term);
      const matchStatus = !statusFilter || run.status === statusFilter;
      const matchDomain = !domainFilter || run.domain === domainFilter;
      return matchText && matchStatus && matchDomain;
    });
  }, [runs, searchTerm, statusFilter, domainFilter]);

  const truncate = (str, n) =>
    str && str.length > n ? str.slice(0, n) + '…' : (str || '');

  if (loading) {
    return (
      <div className="space-y-6">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-white">Factory Projects</h1>
          <div className="h-9 w-48 bg-white/[0.04] rounded-xl animate-pulse" />
        </header>
        <SkeletonTable rows={6} cols={5} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <header className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Factory Projects</h1>
          <p className="text-slate-500 text-sm mt-1">
            {runs.length} {runs.length === 1 ? 'project' : 'projects'} total
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              placeholder="Search projects…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-white/[0.04] border border-white/[0.08] rounded-xl pl-9 pr-4 py-2 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-violet-500/40 focus:bg-white/[0.06] w-52 transition-all"
            />
          </div>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-violet-500/40 appearance-none cursor-pointer"
          >
            <option value="">All statuses</option>
            {['running', 'completed', 'failed', 'cancelled', 'paused', 'interrupted'].map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          {domains.length > 0 && (
            <select
              value={domainFilter}
              onChange={e => setDomainFilter(e.target.value)}
              className="bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-violet-500/40 appearance-none cursor-pointer"
            >
              <option value="">All domains</option>
              {domains.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          )}
          <button
            onClick={onNewProject}
            className="flex items-center gap-1.5 bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 transition-all text-white text-xs font-semibold px-4 py-2 rounded-xl shadow-md shadow-violet-500/20"
          >
            <Rocket className="w-3.5 h-3.5" />
            <span>New Project</span>
          </button>
        </div>
      </header>

      {/* Empty state */}
      {runs.length === 0 ? (
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl">
          <EmptyState onNewProject={onNewProject} />
        </div>
      ) : (
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-white/[0.06]">
                <th className="px-6 py-3.5 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Project</th>
                <th className="px-6 py-3.5 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Status</th>
                <th className="px-6 py-3.5 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Progress</th>
                <th className="px-6 py-3.5 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Started</th>
                <th className="px-6 py-3.5 text-[10px] font-bold text-slate-500 uppercase tracking-widest text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {filtered.map((run) => (
                <tr
                  key={run.run_id || run.id}
                  onClick={() => navigate(`/project/${run.run_id || run.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      navigate(`/project/${run.run_id || run.id}`);
                    }
                  }}
                  tabIndex={0}
                  role="button"
                  aria-label={run.project_name || 'Untitled Project'}
                  className="hover:bg-white/[0.03] transition-colors cursor-pointer group focus:outline-none focus:bg-violet-500/5"
                >
                  {/* Project name */}
                  <td className="px-6 py-4">
                    <div className="font-semibold text-white group-hover:text-violet-300 transition-colors">
                      {truncate(run.project_name || 'Untitled Project', 40)}
                    </div>
                    <div className="text-[10px] text-slate-600 font-mono mt-0.5">
                      {(run.run_id || run.id || '').slice(0, 8)}
                    </div>
                  </td>

                  {/* Status badge */}
                  <td className="px-6 py-4">
                    <StatusBadge status={run.status} />
                  </td>

                  {/* Progress bar */}
                  <td className="px-6 py-4 min-w-[180px]">
                    <ProgressBar run={run} />
                  </td>

                  {/* Started */}
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-1.5 text-xs text-slate-500">
                      <Clock className="w-3 h-3 shrink-0" />
                      {run.started_at
                        ? new Date(run.started_at).toLocaleString(undefined, {
                            month: 'short', day: 'numeric',
                            hour: '2-digit', minute: '2-digit',
                          })
                        : '—'}
                    </div>
                  </td>

                  {/* Actions */}
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {run.status === 'running' && (
                        <>
                          <button
                            onClick={(e) => doAction(e, run.run_id || run.id, 'pause')}
                            disabled={!!actionLoading[run.run_id || run.id]}
                            className="p-1.5 rounded-lg text-amber-400 hover:bg-amber-400/10 transition-all"
                            title="Pause"
                          >
                            {actionLoading[run.run_id || run.id] === 'pause'
                              ? <Loader2 className="w-4 h-4 animate-spin" />
                              : <Pause className="w-4 h-4" />}
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setConfirmCancel(run); }}
                            disabled={!!actionLoading[run.run_id || run.id]}
                            className="p-1.5 rounded-lg text-red-400 hover:bg-red-400/10 transition-all"
                            title="Cancel run"
                            aria-label="Cancel run"
                          >
                            {actionLoading[run.run_id || run.id] === 'cancel'
                              ? <Loader2 className="w-4 h-4 animate-spin" />
                              : <X className="w-4 h-4" />}
                          </button>
                        </>
                      )}
                      {run.status === 'paused' && (
                        <>
                          <button
                            onClick={(e) => doAction(e, run.run_id || run.id, 'resume')}
                            disabled={!!actionLoading[run.run_id || run.id]}
                            className="p-1.5 rounded-lg text-emerald-400 hover:bg-emerald-400/10 transition-all"
                            title="Resume"
                          >
                            {actionLoading[run.run_id || run.id] === 'resume'
                              ? <Loader2 className="w-4 h-4 animate-spin" />
                              : <Play className="w-4 h-4" />}
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setConfirmCancel(run); }}
                            disabled={!!actionLoading[run.run_id || run.id]}
                            className="p-1.5 rounded-lg text-red-400 hover:bg-red-400/10 transition-all"
                            title="Cancel run"
                            aria-label="Cancel run"
                          >
                            {actionLoading[run.run_id || run.id] === 'cancel'
                              ? <Loader2 className="w-4 h-4 animate-spin" />
                              : <X className="w-4 h-4" />}
                          </button>
                        </>
                      )}
                      {['completed', 'failed', 'cancelled', 'interrupted'].includes(run.status) && (
                        <RerunDropdown
                          status={run.status}
                          rawInput={run.raw_input || run.requirement || ''}
                          loading={actionLoading[run.run_id || run.id] === 'rerun'}
                          variant="compact"
                          onContinue={() => doAction(null, run.run_id || run.id, 'resume')}
                          onRerunPhase={(phase) => doRerunPhase(run.run_id || run.id, phase)}
                          onFullRestart={() => doRerunPhase(run.run_id || run.id, 's01_intake')}
                          onRestart={() => doAction(null, run.run_id || run.id, 'restart')}
                          onEditRestart={(req) => doEditRestart(run.run_id || run.id, run, req)}
                        />
                      )}
                      {run.live_url && (
                        <a
                          href={isPreviewUrl(run.live_url) ? '#' : run.live_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={async (e) => {
                            e.stopPropagation();
                            if (!isPreviewUrl(run.live_url)) return;
                            e.preventDefault();  // a preview link is single-use: ask for a fresh one
                            const err = await openPreviewInTab(run.run_id || run.id);
                            if (err) toast(err, 'error', 8000);
                          }}
                          className="p-1.5 rounded-lg text-emerald-400 hover:text-emerald-300 hover:bg-emerald-400/10 transition-all"
                          title="Open live app"
                        >
                          🌐
                        </a>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); navigate(`/project/${run.run_id || run.id}`); }}
                        className="p-1.5 rounded-lg text-slate-500 hover:text-violet-400 hover:bg-violet-500/10 transition-all opacity-0 group-hover:opacity-100"
                        title="View Details"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

              {filtered.length === 0 && searchTerm && (
                <tr>
                  <td colSpan="5" className="px-6 py-12 text-center text-slate-500 text-sm">
                    No projects match "<span className="text-white">{searchTerm}</span>"
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Load more */}
      {hasMore && !searchTerm && !statusFilter && !domainFilter && (
        <div className="flex flex-col items-center gap-1 py-4">
          <button
            onClick={loadMore}
            className="px-6 py-2 text-xs font-semibold text-slate-500 border border-white/[0.08] rounded-xl hover:text-white hover:border-violet-500/30 hover:bg-violet-500/[0.05] transition-all"
          >
            Load more ({runs.length} of {total} shown)
          </button>
        </div>
      )}

      <ConfirmDialog
        open={!!confirmCancel}
        title="Cancel Run"
        message={confirmCancel ? `Cancel "${confirmCancel.project_name || 'this run'}"? The run will stop and cannot be resumed from the current state.` : ''}
        onConfirm={() => {
          if (confirmCancel) doAction(null, confirmCancel.run_id || confirmCancel.id, 'cancel');
          setConfirmCancel(null);
        }}
        onCancel={() => setConfirmCancel(null)}
        danger
      />
    </div>
  );
};

export default ProjectsList;
