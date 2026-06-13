import React, { useState, useMemo, useCallback } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { api } from '../api';
import PhaseBadge from '../components/PhaseBadge';
import RerunDropdown from '../components/RerunDropdown';
import ConfirmDialog from '../components/ConfirmDialog';
import { Eye, Search, Clock, Rocket, Pause, Play, X, Loader2 } from 'lucide-react';
import { useRuns } from '../contexts/RunsContext';
import { SkeletonTable } from '../components/Skeleton';

// 23-phase list in order (matches factory_pipeline.py PHASE_SEQUENCE)
const PHASES = [
  'p00_research',
  'p01_intake_requirements',
  'p02_architecture',
  'p02b_domain_ir',
  'p03_scaffolding',
  'p04_backend',
  'p04b_business_logic',
  'p05_frontend',
  'p06_review_security',
  'p07_testing',
  'p07b_self_healing',
  'p08_cicd_deployment',
  'p09_observability',
  'p10_docs_delivery',
  'p11_deployment',
  'p11a_monitoring',
  'p11b_error_tracking',
  'p11c_analytics',
  'p11d_alerting',
  'p12a_feature_flags',
  'p12b_ab_testing',
  'p13_app_memory',
  'p14_client_portal',
];

// Map run status/phases → number of completed phases for dot strip
const getCompletedCount = (run) => {
  if (run.status === 'completed') return PHASES.length;
  const phases = run.phases || {};
  const completed = PHASES.filter((p) => {
    const st = phases[p]?.status;
    return st === 'passed' || st === 'completed' || st === 'timeout';
  }).length;
  // If there's a current_phase, count phases before it too
  if (run.current_phase && run.current_phase !== 'pipeline') {
    const idx = PHASES.indexOf(run.current_phase);
    return Math.max(completed, idx >= 0 ? idx : 0);
  }
  return completed;
};

// 23-dot progress strip
const ProgressDots = ({ run }) => {
  const completed = getCompletedCount(run);
  const isRunning = run.status === 'running';

  return (
    <div className="flex items-center space-x-1">
      {PHASES.map((_, i) => {
        const done = i < completed;
        const active = isRunning && i === completed;
        return (
          <span
            key={i}
            className={`inline-block rounded-full transition-all ${
              done
                ? 'w-2.5 h-2.5 bg-emerald-500'
                : active
                ? 'w-2.5 h-2.5 bg-indigo-500 animate-pulse'
                : 'w-2 h-2 bg-slate-700'
            }`}
            title={PHASES[i]}
          />
        );
      })}
    </div>
  );
};

// Hexagon logo for empty state
const HexLogo = () => (
  <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
    <polygon points="32,4 58,18 58,46 32,60 6,46 6,18" fill="none" stroke="#6366f1" strokeWidth="2" opacity="0.4" />
    <polygon points="32,14 48,23 48,41 32,50 16,41 16,23" fill="#6366f1" opacity="0.15" />
    <circle cx="32" cy="32" r="8" fill="#6366f1" opacity="0.6" />
  </svg>
);

const EmptyState = ({ onNewProject }) => (
  <div className="flex flex-col items-center justify-center py-24 space-y-6">
    <HexLogo />
    <div className="text-center space-y-2">
      <h3 className="text-xl font-bold text-bright">No projects yet</h3>
      <p className="text-muted text-sm max-w-xs">
        Start your first factory run and AetherOS will generate a complete production-ready codebase.
      </p>
    </div>
    <button
      onClick={onNewProject}
      className="flex items-center space-x-2 bg-accent hover:bg-accent/90 transition-colors text-white font-bold px-6 py-3 rounded-lg"
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
  const [actionLoading, setActionLoading] = useState({}); // { [runId]: 'pause'|'resume'|'cancel' }
  const [confirmCancel, setConfirmCancel] = useState(null); // run object pending cancel confirmation
  const navigate = useNavigate();

  const doAction = async (e, runId, action) => {
    if (e) e.stopPropagation();
    setActionLoading((prev) => ({ ...prev, [runId]: action }));
    try {
      if (action === 'pause')  await api.pauseRun(runId);
      if (action === 'resume') await api.resumeRun(runId);
      if (action === 'cancel') await api.cancelRun(runId);
      refresh();
    } catch {
      /* silent fail */
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[runId]; return n; });
    }
  };

  const doRerunPhase = async (runId, fromPhase) => {
    setActionLoading((prev) => ({ ...prev, [runId]: 'rerun' }));
    try {
      const res = await api.rerunFromPhase(runId, fromPhase);
      navigate(`/project/${res.data.run_id}`);
    } catch {
      /* silent fail */
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
    } catch {
      /* silent fail */
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
          <h1 className="text-2xl font-bold text-bright">Factory Projects</h1>
          <div className="h-9 w-48 bg-border/40 rounded-lg animate-pulse" />
        </header>
        <SkeletonTable rows={6} cols={5} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright">Factory Projects</h1>
          <p className="text-muted text-sm mt-1">
            {runs.length} {runs.length === 1 ? 'project' : 'projects'} total
          </p>
        </div>
        <div className="flex items-center space-x-3 flex-wrap gap-2">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="text"
              placeholder="Search projects…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-panel border border-border rounded-lg pl-10 pr-4 py-2 text-sm text-bright focus:outline-none focus:border-accent w-52 transition-colors"
            />
          </div>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="bg-panel border border-border rounded-lg px-3 py-2 text-xs text-bright focus:outline-none focus:border-accent"
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
              className="bg-panel border border-border rounded-lg px-3 py-2 text-xs text-bright focus:outline-none focus:border-accent"
            >
              <option value="">All domains</option>
              {domains.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          )}
          <button
            onClick={onNewProject}
            className="flex items-center space-x-1.5 bg-accent hover:bg-accent/90 transition-colors text-white text-xs font-bold px-4 py-2 rounded-lg"
          >
            <Rocket className="w-3.5 h-3.5" />
            <span>New Project</span>
          </button>
        </div>
      </header>

      {/* Empty state */}
      {runs.length === 0 ? (
        <div className="panel">
          <EmptyState onNewProject={onNewProject} />
        </div>
      ) : (
        <div className="panel overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-border/20 text-[10px] font-bold text-muted uppercase tracking-widest border-b border-border">
                <th className="px-6 py-4">Project</th>
                <th className="px-6 py-4">Status</th>
                <th className="px-6 py-4">Progress</th>
                <th className="px-6 py-4">Started</th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
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
                  className="hover:bg-white/[0.02] transition-colors cursor-pointer group focus:outline-none focus:bg-accent/5"
                >
                  {/* Project name */}
                  <td className="px-6 py-4">
                    <div className="font-semibold text-bright group-hover:text-accent transition-colors">
                      {truncate(run.project_name || 'Untitled Project', 40)}
                    </div>
                    <div className="text-[10px] text-muted font-mono mt-0.5">
                      {(run.run_id || run.id || '').slice(0, 8)}
                    </div>
                  </td>

                  {/* Status badge */}
                  <td className="px-6 py-4">
                    <PhaseBadge status={run.status} />
                  </td>

                  {/* 10-dot progress strip */}
                  <td className="px-6 py-4">
                    <ProgressDots run={run} />
                  </td>

                  {/* Started */}
                  <td className="px-6 py-4">
                    <div className="flex items-center text-xs text-muted">
                      <Clock className="w-3 h-3 mr-1.5 shrink-0" />
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
                    <div className="flex items-center justify-end space-x-1">
                      {/* Running → Pause + Cancel */}
                      {run.status === 'running' && (
                        <>
                          <button
                            onClick={(e) => doAction(e, run.run_id || run.id, 'pause')}
                            disabled={!!actionLoading[run.run_id || run.id]}
                            className="p-1.5 rounded text-yellow-400 hover:bg-yellow-400/10 transition-colors"
                            title="Pause"
                          >
                            {actionLoading[run.run_id || run.id] === 'pause'
                              ? <Loader2 className="w-4 h-4 animate-spin" />
                              : <Pause className="w-4 h-4" />}
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setConfirmCancel(run); }}
                            disabled={!!actionLoading[run.run_id || run.id]}
                            className="p-1.5 rounded text-red-400 hover:bg-red-400/10 transition-colors"
                            title="Cancel run"
                            aria-label="Cancel run"
                          >
                            {actionLoading[run.run_id || run.id] === 'cancel'
                              ? <Loader2 className="w-4 h-4 animate-spin" />
                              : <X className="w-4 h-4" />}
                          </button>
                        </>
                      )}
                      {/* Paused → Resume + Cancel */}
                      {run.status === 'paused' && (
                        <>
                          <button
                            onClick={(e) => doAction(e, run.run_id || run.id, 'resume')}
                            disabled={!!actionLoading[run.run_id || run.id]}
                            className="p-1.5 rounded text-green-400 hover:bg-green-400/10 transition-colors"
                            title="Resume"
                          >
                            {actionLoading[run.run_id || run.id] === 'resume'
                              ? <Loader2 className="w-4 h-4 animate-spin" />
                              : <Play className="w-4 h-4" />}
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setConfirmCancel(run); }}
                            disabled={!!actionLoading[run.run_id || run.id]}
                            className="p-1.5 rounded text-red-400 hover:bg-red-400/10 transition-colors"
                            title="Cancel run"
                            aria-label="Cancel run"
                          >
                            {actionLoading[run.run_id || run.id] === 'cancel'
                              ? <Loader2 className="w-4 h-4 animate-spin" />
                              : <X className="w-4 h-4" />}
                          </button>
                        </>
                      )}
                      {/* Completed / failed / cancelled / interrupted → RerunDropdown */}
                      {['completed', 'failed', 'cancelled', 'interrupted'].includes(run.status) && (
                        <RerunDropdown
                          status={run.status}
                          rawInput={run.raw_input || run.requirement || ''}
                          loading={actionLoading[run.run_id || run.id] === 'rerun'}
                          variant="compact"
                          onContinue={() => doAction(null, run.run_id || run.id, 'resume')}
                          onRerunPhase={(phase) => doRerunPhase(run.run_id || run.id, phase)}
                          onFullRestart={() => doRerunPhase(run.run_id || run.id, 'p01_intake_requirements')}
                          onEditRestart={(req) => doEditRestart(run.run_id || run.id, run, req)}
                        />
                      )}
                      {/* Live URL globe — shown when container is running */}
                      {run.live_url && (
                        <a
                          href={run.live_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="p-1.5 rounded text-emerald-400 hover:text-emerald-300 hover:bg-emerald-400/10 transition-colors"
                          title={`Open live app — ${run.live_url}`}
                        >
                          🌐
                        </a>
                      )}
                      {/* Always show View eye */}
                      <button
                        onClick={(e) => { e.stopPropagation(); navigate(`/project/${run.run_id || run.id}`); }}
                        className="p-1.5 rounded text-muted hover:text-accent transition-colors opacity-0 group-hover:opacity-100"
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
                  <td colSpan="5" className="px-6 py-12 text-center text-muted text-sm">
                    No projects match "<span className="text-bright">{searchTerm}</span>"
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
            className="px-6 py-2 text-xs font-bold text-muted border border-border rounded-lg hover:text-bright hover:border-accent/40 transition-colors"
          >
            Load more ({runs.length} of {total} shown)
          </button>
        </div>
      )}

      {/* Cancel run confirmation */}
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
