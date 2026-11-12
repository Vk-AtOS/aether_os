import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { api } from '../api';
import {
  ChevronLeft,
  ExternalLink,
  Download,
  AlertTriangle,
  RefreshCw,
  Zap,
  Shield,
  Star,
  FileCode,
  Pause,
  Play,
  X,
  Rocket,
  Globe,
  Loader2,
  XCircle,
} from 'lucide-react';
import RerunDropdown from '../components/RerunDropdown';
import { PHASES, PHASE_NAMES, stageStates, summariseRunEvents } from '../components/project/projectConstants';
import ClientAccessPanel from '../components/project/ClientAccessPanel';
import { useRole } from '../hooks/useRole';
import { fmtTime } from '../components/run-detail/format';
import {
  StatusBadge,
  PhaseRow,
  LiveEventLog,
} from '../components/run-detail/RunDetailComponents';
import { confirmAction } from '../components/confirmAction';
import { apiError } from '../apiError';
import { isPreviewUrl, openPreviewInTab } from '../previewSession';

// ── Main page ─────────────────────────────────────────────────────────────────

const RunDetail = () => {
  const { runId } = useParams();
  const navigate = useNavigate();
  const { role, isAdmin } = useRole();

  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [rerunning, setRerunning] = useState(false);

  // Promise chain with no state set before the requests: this runs from an effect.
  const loadRun = useCallback(() => Promise.allSettled([
    api.getRun(runId),
    api.getRunEvents(runId).catch(() => ({ data: [] })),
  ]).then(([runRes, eventsRes]) => {
    if (runRes.status === 'fulfilled') setRun(runRes.value.data);
    else setError(apiError(runRes.reason) || 'Failed to load run');
    if (eventsRes.status === 'fulfilled') {
      const raw = eventsRes.value.data;
      setEvents(Array.isArray(raw) ? raw : raw?.events ?? []);
    }
  }).finally(() => setLoading(false)), [runId]);

  // FE-H4: use a ref to hold the interval ID so there is always exactly one active
  // interval. The previous pattern re-created the interval on every status change
  // but React's strict-mode / fast re-renders could leave orphan intervals that
  // fired the stale closure. Now we start once on mount, read run status from a ref
  // so the callback always sees the latest value, and clear on unmount.
  const runStatusRef = useRef(run?.status);
  useEffect(() => {
    runStatusRef.current = run?.status;
  }, [run?.status]);

  // The preview link only works once this browser holds the run's preview cookie,
  // which the status call issues.
  useEffect(() => {
    if (run?.live_url) api.getRunAppStatus(runId).catch(() => {});
  }, [run?.live_url, runId]);

  useEffect(() => {
    loadRun();
    const iv = setInterval(() => {
      const st = runStatusRef.current;
      if (st === 'running' || st === 'needs_review') loadRun();
    }, 10_000);
    return () => clearInterval(iv);
  }, [loadRun]);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const res = await api.downloadRunZip(runId);
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = `run-${runId.slice(0, 8)}.zip`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
    } catch (e) {
      console.warn('ZIP download failed:', e);
      setError('Download failed. Please try again.');
    } finally {
      setDownloading(false);
    }
  };

  const handleCancel = async () => {
    if (!(await confirmAction('Cancel this run? It cannot be resumed.'))) return;
    setCancelling(true);
    try {
      await api.cancelRun(runId);
      await loadRun();
    } catch (e) {
      alert('Cancel failed: ' + (apiError(e) || e.message));
    } finally {
      setCancelling(false);
    }
  };

  const handlePause = async () => {
    setPausing(true);
    try {
      await api.pauseRun(runId);
      await loadRun();
    } catch (e) {
      alert('Pause failed: ' + (apiError(e) || e.message));
    } finally {
      setPausing(false);
    }
  };

  const handleResume = async () => {
    setPausing(true);
    try {
      await api.resumeRun(runId);
      await loadRun();
    } catch (e) {
      alert('Resume failed: ' + (apiError(e) || e.message));
    } finally {
      setPausing(false);
    }
  };

  const handleDeploy = async () => {
    setDeploying(true);
    try {
      await api.deployRun(runId);
      await loadRun();
    } catch (e) {
      alert('Deploy failed: ' + (apiError(e) || e.message));
    } finally {
      setDeploying(false);
    }
  };

  const handleUndeploy = async () => {
    if (!(await confirmAction('Stop this deployed app?'))) return;
    setDeploying(true);
    try {
      await api.stopDeploy(runId);
      await loadRun();
    } catch (e) {
      alert('Undeploy failed: ' + (apiError(e) || e.message));
    } finally {
      setDeploying(false);
    }
  };

  const handleRerunPhase = async (phase) => {
    setRerunning(true);
    try {
      const res = await api.rerunFromPhase(runId, phase);
      navigate(`/runs/${res.data.run_id}`);
    } catch (e) {
      alert('Rerun failed: ' + (apiError(e) || e.message));
    } finally {
      setRerunning(false);
    }
  };

  const handleFullRestart = async () => {
    setRerunning(true);
    try {
      const res = await api.rerunFromPhase(runId, 's01_intake');
      navigate(`/runs/${res.data.run_id}`);
    } catch (e) {
      alert('Restart failed: ' + (apiError(e) || e.message));
    } finally {
      setRerunning(false);
    }
  };

  const handleRestart = async () => {
    setRerunning(true);
    try {
      await api.restartRun(runId);
      await loadRun();
    } catch (e) {
      alert('Restart failed: ' + (apiError(e) || e.message));
    } finally {
      setRerunning(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto space-y-6 animate-pulse">
        <div className="h-8 bg-border/30 rounded w-1/3" />
        <div className="h-4 bg-border/20 rounded w-1/2" />
        <div className="h-64 bg-border/20 rounded-xl" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center gap-2 text-danger p-4 bg-danger/10 border border-danger/30 rounded-xl">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
        <button onClick={() => navigate(-1)} className="mt-4 flex items-center gap-1 text-sm text-muted hover:text-bright transition-colors">
          <ChevronLeft className="w-4 h-4" /> Back
        </button>
      </div>
    );
  }

  if (!run) return null;

  // Build phase progress from run.phases or run.phase_results
  const phaseMap = run.phases || run.phase_results || {};
  // The 12 stages; a run recorded before the stage pipeline lists the phases it actually has.
  const isStageRun = Object.keys(phaseMap).every(k => PHASES.includes(k));
  const phaseList = isStageRun ? PHASES : Object.keys(phaseMap);
  const stages = isStageRun ? stageStates(run, summariseRunEvents(events)) : {};
  const failedStage = PHASES.find(p => stages[p]?.status === 'failed');

  // Derive council verdict from run
  const councilVerdict = run.council_verdict || run.council?.verdict || null;
  const councilScore   = run.council_score   || run.council?.score   || null;
  const qualityScore   = run.quality_score   ?? run.quality?.score   ?? null;
  const llmCostUsd     = run.llm_cost_usd    ?? run.cost_usd         ?? null;
  const liveUrl        = run.live_url        || run.preview_url      || run.app_url || null;
  const errorMsg       = run.message || run.error_message || run.error || null;
  const suggestions    = run.suggestions     || run.recovery_suggestions || [];

  return (
    <div className="max-w-5xl mx-auto space-y-6 pb-20">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-xs text-muted hover:text-bright transition-colors mb-2">
            <ChevronLeft className="w-3.5 h-3.5" /> Back
          </button>
          <h1 className="text-2xl font-bold text-bright">
            {run.app_name || run.project_name || `Run ${runId.slice(0, 8)}`}
          </h1>
          <div className="flex items-center gap-3 mt-1.5 flex-wrap">
            <StatusBadge status={run.status} />
            <span className="text-xs text-muted font-mono">{runId.slice(0, 12)}…</span>
            {run.created_at && <span className="text-xs text-muted">{fmtTime(run.created_at)}</span>}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0 mt-6">
          <button
            onClick={loadRun}
            className="p-2 text-muted hover:text-bright border border-border rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>

          {/* Cancel — only when running */}
          {run.status === 'running' && (
            <button
              onClick={handleCancel}
              disabled={cancelling}
              className="flex items-center gap-1.5 px-3 py-2 bg-danger/20 text-danger border border-danger/30 rounded-lg text-xs font-bold hover:bg-danger/30 transition-colors disabled:opacity-50"
              title="Cancel run"
            >
              {cancelling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <X className="w-3.5 h-3.5" />}
              Cancel
            </button>
          )}

          {/* Pause / Resume */}
          {run.status === 'running' && (
            <button
              onClick={handlePause}
              disabled={pausing}
              className="flex items-center gap-1.5 px-3 py-2 bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded-lg text-xs font-bold hover:bg-blue-500/30 transition-colors disabled:opacity-50"
              title="Pause run"
            >
              {pausing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Pause className="w-3.5 h-3.5" />}
              Pause
            </button>
          )}
          {run.status === 'paused' && (
            <button
              onClick={handleResume}
              disabled={pausing}
              className="flex items-center gap-1.5 px-3 py-2 bg-success/20 text-success border border-success/30 rounded-lg text-xs font-bold hover:bg-success/30 transition-colors disabled:opacity-50"
              title="Resume run"
            >
              {pausing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              Resume
            </button>
          )}

          {/* Rerun dropdown — for completed/failed/paused/needs_review/cancelled */}
          {['completed', 'failed', 'needs_review', 'paused', 'cancelled'].includes(run.status) && (
            <RerunDropdown
              status={run.status}
              rawInput={run.raw_input || run.requirement || ''}
              onContinue={handleResume}
              onEditRestart={(req) => { navigate('/new-project', { state: { prefill: req } }); }}
              onRerunPhase={handleRerunPhase}
              onFullRestart={handleFullRestart}
              onRestart={handleRestart}
              loading={rerunning}
              variant="button"
            />
          )}

          {/* Deploy / Undeploy */}
          {run.status === 'completed' && !run.live_url && !run.deployed_at && (
            <button
              onClick={handleDeploy}
              disabled={deploying}
              className="flex items-center gap-1.5 px-3 py-2 bg-purple-500/20 text-purple-400 border border-purple-500/30 rounded-lg text-xs font-bold hover:bg-purple-500/30 transition-colors disabled:opacity-50"
              title="Deploy app"
            >
              {deploying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Rocket className="w-3.5 h-3.5" />}
              Deploy
            </button>
          )}
          {(run.live_url || run.deployed_at) && run.status !== 'failed' && (
            <button
              onClick={handleUndeploy}
              disabled={deploying}
              className="flex items-center gap-1.5 px-3 py-2 bg-danger/20 text-danger border border-danger/30 rounded-lg text-xs font-bold hover:bg-danger/30 transition-colors disabled:opacity-50"
              title="Stop deployment"
            >
              {deploying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <X className="w-3.5 h-3.5" />}
              Undeploy
            </button>
          )}

          {/* Open Portal */}
          <button
            onClick={() => navigate(`/portal/${runId}`)}
            className="flex items-center gap-1.5 px-3 py-2 bg-surface border border-border rounded-lg text-xs font-bold text-muted hover:text-bright hover:border-accent/40 transition-colors"
            title="Open client portal"
          >
            <Globe className="w-3.5 h-3.5" />
            Portal
          </button>

          {(run.status === 'completed' || run.status === 'needs_review' || run.status === 'failed') && (
            <button
              onClick={handleDownload}
              disabled={downloading}
              className="flex items-center gap-1.5 px-3 py-2 bg-accent/20 text-accent border border-accent/30 rounded-lg text-xs font-bold hover:bg-accent/30 transition-colors disabled:opacity-50"
            >
              {downloading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
              Download ZIP
            </button>
          )}
          {liveUrl && (
            <a
              href={isPreviewUrl(liveUrl) ? '#' : liveUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={async (e) => {
                if (!isPreviewUrl(liveUrl)) return;
                e.preventDefault();  // single-use preview link: ask for a fresh one
                const err = await openPreviewInTab(run.run_id || run.id || runId);
                if (err) window.alert(err);
              }}
              className="flex items-center gap-1.5 px-3 py-2 bg-success/20 text-success border border-success/30 rounded-lg text-xs font-bold hover:bg-success/30 transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" /> Live App
            </a>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="bg-panel border border-border rounded-xl p-4">
          <div className="text-[10px] font-bold text-muted uppercase tracking-widest mb-1 flex items-center gap-1">
            <Star className="w-3 h-3" /> Quality Score
          </div>
          <div className={`text-2xl font-bold ${qualityScore != null ? (qualityScore >= 80 ? 'text-success' : qualityScore >= 60 ? 'text-warning' : 'text-danger') : 'text-muted'}`}>
            {qualityScore != null ? `${qualityScore}` : '—'}
            {qualityScore != null && <span className="text-sm font-normal text-muted">/100</span>}
          </div>
        </div>
        <div className="bg-panel border border-border rounded-xl p-4">
          <div className="text-[10px] font-bold text-muted uppercase tracking-widest mb-1 flex items-center gap-1">
            <Zap className="w-3 h-3" /> LLM Cost
          </div>
          <div className="text-2xl font-bold text-bright">
            {llmCostUsd != null ? `$${llmCostUsd.toFixed(4)}` : '—'}
          </div>
        </div>
        <div className="bg-panel border border-border rounded-xl p-4">
          <div className="text-[10px] font-bold text-muted uppercase tracking-widest mb-1 flex items-center gap-1">
            <Shield className="w-3 h-3" /> Council
          </div>
          <div className={`text-2xl font-bold ${
            councilVerdict === 'approved' ? 'text-success' :
            councilVerdict === 'rejected' ? 'text-danger' :
            councilScore != null ? (councilScore >= 70 ? 'text-success' : 'text-warning') : 'text-muted'
          }`}>
            {councilVerdict ? (councilVerdict === 'approved' ? 'Approved' : councilVerdict === 'rejected' ? 'Rejected' : councilVerdict)
              : councilScore != null ? `${councilScore}` : '—'}
          </div>
        </div>
        <div className="bg-panel border border-border rounded-xl p-4">
          <div className="text-[10px] font-bold text-muted uppercase tracking-widest mb-1 flex items-center gap-1">
            <FileCode className="w-3 h-3" /> Stages
          </div>
          <div className="text-2xl font-bold text-bright">
            {Object.values(phaseMap).filter(p => ['passed', 'completed', 'complete'].includes(p?.status)).length}
            <span className="text-sm font-normal text-muted">/{phaseList.length}</span>
          </div>
        </div>
      </div>

      {/* Live SSE panel (when running) */}
      {run.status === 'running' && (
        <section>
          <h2 className="text-xs font-bold text-muted uppercase tracking-widest mb-3">Live Pipeline Output</h2>
          <LiveEventLog runId={runId} />
        </section>
      )}

      {/* Error + suggestions (when failed) */}
      {run.status === 'failed' && (errorMsg || failedStage) && (
        <div className="bg-danger/5 border border-danger/30 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <XCircle className="w-4 h-4 text-danger shrink-0" />
            <h3 className="text-sm font-bold text-danger">Build failed{failedStage ? ` at ${PHASE_NAMES[failedStage]}` : ''}</h3>
          </div>
          <p className="text-xs text-bright/80 font-mono whitespace-pre-wrap">{errorMsg || stages[failedStage]?.reason || 'No reason was recorded.'}</p>
          <p className="text-[11px] text-muted">Restart this run (Re-run options) to continue from the stage that stopped it.</p>
          {suggestions.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-muted uppercase tracking-wider">Suggestions</p>
              <ul className="space-y-1">
                {suggestions.map((s, i) => (
                  <li key={i} className="text-xs text-bright/70 flex items-start gap-1.5">
                    <span className="text-accent shrink-0 mt-0.5">→</span>{s}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Council verdict (needs_review) */}
      {run.status === 'needs_review' && (
        <div className="bg-yellow-500/5 border border-yellow-500/30 rounded-xl p-5 space-y-2">
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-yellow-400 shrink-0" />
            <h3 className="text-sm font-bold text-yellow-400">Awaiting Council Review</h3>
          </div>
          {councilVerdict && (
            <p className="text-xs text-bright/70">Council verdict: <span className="font-bold text-bright">{councilVerdict}</span></p>
          )}
          {run.council?.summary && (
            <p className="text-xs text-bright/70">{run.council.summary}</p>
          )}
          <p className="text-xs text-muted">Go to the project view to approve or reject.</p>
          <Link
            to={`/project/${runId}`}
            className="inline-flex items-center gap-1.5 text-xs text-accent hover:text-accent/80 font-bold transition-colors"
          >
            Open Project View <ExternalLink className="w-3 h-3" />
          </Link>
        </div>
      )}

      {/* Phase progress table */}
      <section>
        <h2 className="text-xs font-bold text-muted uppercase tracking-widest mb-3">Stage Progress</h2>
        <div className="bg-panel border border-border rounded-xl overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border bg-border/10">
                <th className="px-4 py-2.5 text-[10px] font-bold text-muted uppercase tracking-wider">Phase</th>
                <th className="px-4 py-2.5 text-[10px] font-bold text-muted uppercase tracking-wider">Name</th>
                <th className="px-4 py-2.5 text-[10px] font-bold text-muted uppercase tracking-wider">Status</th>
                <th className="px-4 py-2.5 text-[10px] font-bold text-muted uppercase tracking-wider text-right">Duration</th>
              </tr>
            </thead>
            <tbody>
              {phaseList.map(p => (
                <PhaseRow key={p} name={p} phaseData={phaseMap[p]} state={stages[p]}
                  href={isStageRun ? `/project/${runId}/phase/${p}` : null} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {(isAdmin || role === 'superadmin') && <ClientAccessPanel runId={runId} />}

      {/* Recent events log (non-running) */}
      {run.status !== 'running' && events.length > 0 && (
        <section>
          <h2 className="text-xs font-bold text-muted uppercase tracking-widest mb-3">Event Log</h2>
          <div className="bg-panel border border-border rounded-xl overflow-hidden">
            <div className="divide-y divide-border/50 max-h-80 overflow-y-auto custom-scrollbar">
              {/* Streamed model output (llm_chunk) is the Live view's job, not the log's. */}
              {events.filter((ev) => (ev.event_type || ev.type) !== 'llm_chunk').slice(-50).map((ev, i) => {
                // GET /factory/runs/{id}/events rows: {event_type, phase, payload, created_at}
                const type = ev.event_type || ev.type || 'event';
                const p = ev.payload || {};
                const failed = p.status === 'failed' || p.status === 'timeout' || type === 'error';
                const text = p.error || p.reason || p.message
                  || [ev.phase || p.phase, p.status].filter(Boolean).join(' ') || ev.message || '';
                return (
                  <div key={ev.id || i} className="px-4 py-2 flex items-start gap-3 text-xs">
                    <span className="text-muted font-mono text-[10px] shrink-0 mt-0.5">{fmtTime(ev.created_at || ev.timestamp)}</span>
                    <span className={`shrink-0 mt-0.5 text-[10px] font-bold uppercase ${
                      failed ? 'text-danger' : type === 'phase_complete' ? 'text-success' : type === 'phase_start' ? 'text-accent' : 'text-muted'
                    }`}>{type}</span>
                    <span className="text-bright/80 break-words min-w-0">{text}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}
    </div>
  );
};

export default RunDetail;
