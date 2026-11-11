import React, { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api';
import { useRole } from '../hooks/useRole';
import { useProjectView } from '../hooks/useProjectView';
import PhaseBadge from '../components/PhaseBadge';
import LogViewer from './LogViewer';
import AppPreviewPanel from '../components/project/AppPreviewPanel';
import QualityPanel from '../components/project/QualityPanel';
import FeedbackPanel from '../components/project/FeedbackPanel';
import CouncilPanel from '../components/project/CouncilPanel';
import DecisionsPanel from '../components/project/DecisionsPanel';
import EnvVarsPanel from '../components/project/EnvVarsPanel';
import RunAppPanel from '../components/project/RunAppPanel';
import SpecReviewModal from '../components/project/SpecReviewModal';
import ClarifyingQuestionsPanel from '../components/project/ClarifyingQuestionsPanel';
import FileExplorer from '../components/project/FileExplorer';
import RunControlPanel from '../components/project/RunControlPanel';
import { LiveFeedTab, AgentEventsLog } from '../components/project/RunEventLog';
import ProjectLivePreviewPanel from '../components/project/ProjectLivePreviewPanel';
import { TraceTab } from '../components/TraceTab';
import {
  ExternalLink, FileCode, ChevronLeft, Loader2, AlertTriangle, Pause,
  Play, Smartphone, Monitor, ExternalLink as OpenTab, Radio, Download,
  GitBranch, Zap, ShieldCheck, Users, GitPullRequest, CheckCircle2, List,
} from 'lucide-react';
import {
  PHASES, PHASE_NAMES, PRIORITY_CONFIG, PRIORITY_CYCLE, countFiles,
} from '../components/project/projectConstants';

// ── Toast ─────────────────────────────────────────────────────────────────────

const Toast = ({ message, onDone }) => {
  useEffect(() => { const t = setTimeout(onDone, 2500); return () => clearTimeout(t); }, [onDone]);
  return (
    <div className="fixed bottom-6 right-6 z-50 bg-panel border border-border rounded-xl px-5 py-3 shadow-2xl text-bright text-sm font-medium animate-fade-in">
      {message}
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

const ProjectView = () => {
  const { id } = useParams();
  const { isViewer } = useRole();
  const pv = useProjectView(id);

  const {
    run, elapsed, loading, error, setError, setLoading, fileTree, toast, setToast,
    controlLoading, priority, deploying,
    activeArtifactTab, setActiveArtifactTab,
    viewMode, setViewMode, previewMode, setPreviewMode,
    previewHtml, previewLoading, previewFile,
    iframeDevice, setIframeDevice, iframeKey, setIframeKey,
    feedLines, feedDone, feedEndRef, feedContainerRef,
    appRunning, setAppRunning, qualityData, complianceData,
    specReview, specModalOpen, setSpecModalOpen, specApproving, setSpecApproving, setSpecReview,
    showGitHubModal, setShowGitHubModal,
    showAddFeatureModal, setShowAddFeatureModal,
    gitHubToken, setGitHubToken, gitHubRepoName, setGitHubRepoName, gitHubPushing,
    addFeatureText, setAddFeatureText, addingFeature, branchPhaseState, setBranchPhaseState,
    getPhaseStatus, completedPhases, progressPercent, eta, artifactCount,
    fetchRunDetail, showToast,
    handlePause, handleResume, handleCancel, handlePriorityCycle, handleRerun, handleEditRestart,
    handleDeploy, handleStopDeploy, handleDownload, handlePushGitHub, handleAddFeature,
    navigate,
  } = pv;

  // ── Loading / error states ─────────────────────────────────────────────────

  if (loading && !run) {
    return <div className="flex flex-col items-center justify-center h-full space-y-4"><Loader2 className="w-12 h-12 text-accent animate-spin" /><p className="text-muted font-medium">Loading project details...</p></div>;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full p-6">
        <div className="text-center panel p-12 max-w-lg border-danger/20 shadow-2xl">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-danger/10 mb-6"><AlertTriangle className="w-8 h-8 text-danger" /></div>
          <h2 className="text-danger text-2xl font-bold mb-4">Pipeline Error</h2>
          <div className="text-bright font-mono text-sm bg-black/40 p-4 rounded-lg border border-border mb-6 break-words">{error}</div>
          <div className="flex flex-col space-y-3">
            <button onClick={() => navigate('/new')} className="w-full py-3 bg-indigo-600 text-white rounded-lg font-bold hover:bg-indigo-700 transition-colors">START NEW PIPELINE</button>
            <button onClick={() => { setError(null); setLoading(true); fetchRunDetail(); }} className="w-full py-3 bg-border/50 text-bright rounded-lg font-bold hover:bg-border transition-colors border border-border">RETRY FETCH</button>
          </div>
        </div>
      </div>
    );
  }

  if (!run) {
    return <div className="flex flex-col items-center justify-center h-full space-y-4"><AlertTriangle className="w-12 h-12 text-warning" /><p className="text-muted font-medium">Project not found.</p><button onClick={() => navigate('/projects')} className="text-accent hover:underline">Back to Projects</button></div>;
  }

  const events      = run.events || [];
  const phases      = run.phases || {};
  const passedCount = PHASES.filter((p) => ['passed', 'completed'].includes(getPhaseStatus(p))).length;
  const successRate = completedPhases > 0 ? Math.round((passedCount / completedPhases) * 100) : 0;

  const secFindings = (() => {
    const p06 = (phases?.s05_quality || phases?.p06_review_security)?.output;
    if (!p06) return null;
    if (typeof p06.security_total === 'number') return p06.security_total;
    if (Array.isArray(p06.security_findings)) return p06.security_findings.length;
    const findings = p06?.phases?.security?.metadata?.findings || p06?.findings || [];
    return Array.isArray(findings) ? findings.length : null;
  })();

  const secGrade = (() => {
    if (secFindings === null) return null;
    if (secFindings === 0) return { grade: 'A', color: 'text-emerald-400 bg-emerald-900/40 border-emerald-700' };
    if (secFindings <= 2) return { grade: 'B', color: 'text-green-400 bg-green-900/40 border-green-700' };
    if (secFindings <= 5) return { grade: 'C', color: 'text-yellow-400 bg-yellow-900/40 border-yellow-700' };
    if (secFindings <= 10) return { grade: 'D', color: 'text-orange-400 bg-orange-900/40 border-orange-700' };
    return { grade: 'F', color: 'text-red-400 bg-red-900/40 border-red-700' };
  })();

  const priConf   = PRIORITY_CONFIG[priority] || PRIORITY_CONFIG.normal;
  const runStatus = run.status;
  const isRunning = runStatus === 'running';
  const isPaused  = runStatus === 'paused';
  const isDone    = ['completed', 'failed', 'cancelled', 'interrupted'].includes(runStatus);

  const openPreviewTab = () => {
    if (!previewHtml) return;
    const blob = new Blob([previewHtml], { type: 'text/html' });
    const url  = URL.createObjectURL(blob);
    window.open(url, '_blank');
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden -m-6">

      {toast && <Toast message={toast} onDone={() => setToast(null)} />}

      {specModalOpen && (
        <SpecReviewModal spec={specReview} approving={specApproving}
          onApprove={async (remember) => {
            setSpecApproving(true);
            try {
              await api.approveSpec(id, 'approve');
              if (remember) await api.updateOrgSettings({ autonomous_mode: true }).catch(() => {});
              setSpecModalOpen(false);
              showToast(remember ? 'Approved - autonomous mode enabled' : 'Spec approved - starting code generation');
            } catch (e) { showToast('Failed to approve spec: ' + (e.message || 'unknown error')); }
            finally { setSpecApproving(false); }
          }}
          onCancel={async () => {
            try { await api.approveSpec(id, 'cancel'); setSpecModalOpen(false); showToast('Build cancelled at spec review'); fetchRunDetail(); }
            catch { setSpecModalOpen(false); }
          }}
        />
      )}

      {/* LEFT: Phase sidebar */}
      <div className="w-56 bg-[#0a0a10] border-r border-white/[0.06] flex flex-col shrink-0 overflow-hidden">
        <div className="px-3 py-3 border-b border-white/[0.06]">
          <button onClick={() => navigate('/projects')} className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-white transition-colors px-2 py-1.5 rounded-lg hover:bg-white/[0.04] w-full">
            <ChevronLeft className="w-3.5 h-3.5" /><span>All Projects</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto py-2 px-2 custom-scrollbar space-y-0.5">
          {PHASES.map((p) => {
            const st = getPhaseStatus(p);
            const pData = phases[p] || {};
            const dur = pData.duration_s != null ? (pData.duration_s < 60 ? `${pData.duration_s}s` : `${Math.round(pData.duration_s / 60)}m`) : null;
            const isActive = st === 'running' || run.current_phase === p;
            const isDone2  = st === 'passed' || st === 'completed' || st === 'timeout';
            const isFailed = st === 'failed';
            return (
              <div key={p} className="relative group/phase">
                <button onClick={() => navigate(`/project/${id}/phase/${p}`)}
                  className={`w-full flex items-center px-3 py-2.5 text-xs rounded-xl transition-all duration-200 text-left ${isActive ? 'bg-violet-500/10 text-violet-300 border border-violet-500/20' : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]'}`}>
                  <span className={`w-2 h-2 rounded-full shrink-0 mr-2.5 flex-shrink-0 ${isDone2 ? 'bg-emerald-400' : isActive ? 'bg-blue-400 animate-pulse' : isFailed ? 'bg-red-400' : 'bg-slate-700'}`} />
                  <span className="flex-1 truncate font-medium">{PHASE_NAMES[p]}</span>
                  {(p === 's06_testing' || p === 'p07_testing') && pData?.output?.test_quality_flag && (
                    <span className={`ml-2 px-2 py-0.5 rounded-full text-xs font-medium shrink-0 ${pData.output.test_quality_flag === 'pass' ? 'bg-green-500/20 text-green-400' : pData.output.test_quality_flag === 'warn' ? 'bg-amber-500/20 text-amber-400' : 'bg-red-500/20 text-red-400'}`}>
                      {pData.output.test_quality_flag === 'pass' ? `${pData.output.passed_tests}/${pData.output.total_tests} passed` : pData.output.test_quality_flag === 'warn' ? 'partial' : `${pData.output.passed_tests || 0}/${pData.output.total_tests || 0} FAILED`}
                    </span>
                  )}
                  {dur && <span className="text-[9px] text-slate-600 ml-1 shrink-0 font-mono">{dur}</span>}
                </button>
                {(isDone2 || isFailed) && (
                  <button onClick={() => { setShowAddFeatureModal(true); setAddFeatureText(''); setBranchPhaseState(p); }}
                    className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover/phase:opacity-100 p-1 rounded-lg hover:bg-violet-500/20 text-slate-500 hover:text-violet-400 transition-all"
                    title={`Branch from ${PHASE_NAMES[p]}`}><GitBranch className="w-3 h-3" /></button>
                )}
              </div>
            );
          })}
        </div>
        <div className="px-3 py-3 border-t border-white/[0.06]">
          <div className="flex justify-between text-[9px] font-bold text-slate-600 uppercase mb-1.5">
            <span>Progress</span><span>{completedPhases}/{PHASES.length}</span>
          </div>
          <div className="w-full h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-violet-500 to-indigo-400 transition-all duration-1000" style={{ width: `${progressPercent}%` }} />
          </div>
        </div>
      </div>

      {/* RIGHT: Main area */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">

        {/* A failed run keeps its page: logs, artifacts and the trace are how you find out why. */}
        {run.status === 'failed' && (
          <div role="alert" className="flex items-start gap-3 rounded-xl border border-danger/40 bg-danger/10 px-5 py-4">
            <AlertTriangle className="w-5 h-5 text-danger shrink-0 mt-0.5" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold text-danger">This build failed{run.current_phase ? ` at ${run.current_phase}` : ''}</p>
              <p className="text-xs text-bright/80 mt-1 break-words">
                {run.message || events[events.length - 1]?.detail || 'No reason was recorded. Check the Logs and Trace tabs.'}
              </p>
            </div>
            <button onClick={() => navigate('/new')} className="shrink-0 px-3 py-1.5 text-xs font-bold text-white bg-accent hover:bg-accent/90 rounded-lg">
              Start a new build
            </button>
          </div>
        )}

        <header className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <h1 className="text-xl font-bold text-bright truncate max-w-sm">{run.project_name || 'Untitled Project'}</h1>
            <PhaseBadge status={run.status} size="md" />
            {isViewer ? (
              <span className={`flex items-center space-x-1.5 text-xs font-bold px-2.5 py-1 rounded-full border border-border/50 ${priConf.color}`}><span className={`w-1.5 h-1.5 rounded-full ${priConf.dot}`} /><span>{priConf.label}</span></span>
            ) : (
              <button onClick={() => handlePriorityCycle(priority, PRIORITY_CYCLE)} className={`flex items-center space-x-1.5 text-xs font-bold px-2.5 py-1 rounded-full border border-border/50 hover:bg-border/30 transition-colors ${priConf.color}`} title="Click to change priority">
                <span className={`w-1.5 h-1.5 rounded-full ${priConf.dot}`} /><span>{priConf.label}</span>
              </button>
            )}
          </div>
          {secGrade && <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-bold ${secGrade.color}`} title={`Security grade: ${secFindings} findings`}><span>{secGrade.grade}</span></div>}
          <div className="flex items-center space-x-2">
            {run.live_url ? (
              <>
                <a href={run.live_url} target="_blank" rel="noopener noreferrer" className="flex items-center space-x-2 px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-black font-bold rounded-lg transition-colors text-xs animate-pulse">
                  <span>LAUNCH APP</span>
                  {!run.live_url.startsWith('/') && <span className="opacity-70">:{run.live_url?.split(':').pop() ?? ''}</span>}
                </a>
                {!run.live_url.startsWith('/') && <button onClick={handleStopDeploy} className="px-3 py-2 bg-red-900/60 hover:bg-red-800 text-red-300 rounded-lg text-xs font-medium transition-colors">Stop</button>}
              </>
            ) : run.status === 'completed' ? (
              <button onClick={handleDeploy} disabled={deploying} className="flex items-center space-x-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-bold rounded-lg transition-colors disabled:opacity-50 text-xs">
                <span>{deploying ? 'Building...' : 'Deploy to localhost'}</span>
              </button>
            ) : null}
            <button onClick={() => navigate(`/portal/${run.run_id || run.id}`)} className="bg-accent hover:bg-accent/90 transition-colors text-white text-xs font-bold px-4 py-2 rounded-lg flex items-center"><ExternalLink className="w-3.5 h-3.5 mr-2" /> VIEW PORTAL</button>
            <button onClick={handleDownload} className="flex items-center space-x-1.5 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-xs font-medium transition-colors" title="Download ZIP"><Download className="w-3.5 h-3.5" /><span>ZIP</span></button>
            <button onClick={() => setShowGitHubModal(true)} className="flex items-center space-x-1.5 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-xs font-medium transition-colors" title="Push to GitHub"><GitBranch className="w-3.5 h-3.5" /><span>GitHub</span></button>
            <button onClick={async () => { try { await api.openInVSCode(id); setToast('Opening in VS Code...'); } catch { setToast('VS Code CLI not found.'); } }} className="flex items-center space-x-1.5 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-xs font-medium transition-colors"><FileCode className="w-3.5 h-3.5" /><span>VS Code</span></button>
            {(run.status === 'completed' || run.status === 'running') && (
              <button onClick={() => setShowAddFeatureModal(true)} className="flex items-center space-x-1.5 px-3 py-2 bg-indigo-700 hover:bg-indigo-600 text-white rounded-lg text-xs font-medium transition-colors"><Zap className="w-3.5 h-3.5" /><span>Add Feature</span></button>
            )}
          </div>
        </header>

        {showGitHubModal && (
          <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" role="dialog" aria-modal="true" aria-labelledby="github-modal-title">
            <div className="bg-panel border border-border rounded-xl p-6 w-96 space-y-4">
              <h3 id="github-modal-title" className="text-base font-bold text-bright">Push to GitHub</h3>
              <div><label className="block text-xs text-muted mb-1">GitHub Personal Access Token</label><input type="password" value={gitHubToken} onChange={e => setGitHubToken(e.target.value)} placeholder="ghp_..." className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" /></div>
              <div><label className="block text-xs text-muted mb-1">New Repo Name</label><input type="text" value={gitHubRepoName} onChange={e => setGitHubRepoName(e.target.value)} placeholder="my-aetheros-app" className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" /></div>
              <div className="flex space-x-3 pt-1">
                <button onClick={() => setShowGitHubModal(false)} className="flex-1 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-bright transition-colors">Cancel</button>
                <button onClick={handlePushGitHub} disabled={gitHubPushing} className="flex-1 py-2 bg-accent hover:bg-accent/90 rounded-lg text-sm text-white font-bold transition-colors disabled:opacity-50">{gitHubPushing ? 'Pushing...' : 'Push'}</button>
              </div>
            </div>
          </div>
        )}

        {showAddFeatureModal && (
          <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" role="dialog" aria-modal="true" aria-labelledby="add-feature-modal-title">
            <div className="bg-panel border border-border rounded-xl p-6 w-[480px] space-y-4">
              <h3 id="add-feature-modal-title" className="text-base font-bold text-bright">Add a Feature</h3>
              <p className="text-xs text-muted">Describe the feature to add. A new run will branch from the backend stage with your existing architecture.</p>
              <textarea value={addFeatureText} onChange={e => setAddFeatureText(e.target.value)} rows={4} placeholder="Add Stripe payments with webhook support..." className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent resize-none" />
              <div className="flex space-x-3">
                <button onClick={() => setShowAddFeatureModal(false)} className="flex-1 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-bright transition-colors">Cancel</button>
                <button onClick={handleAddFeature} disabled={addingFeature} className="flex-1 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm text-white font-bold transition-colors disabled:opacity-50">{addingFeature ? 'Starting...' : 'Add Feature'}</button>
              </div>
            </div>
          </div>
        )}

        <RunControlPanel
          run={run} elapsed={elapsed} eta={eta} artifactCount={artifactCount}
          successRate={successRate} secFindings={secFindings}
          isViewer={isViewer} isRunning={isRunning} isPaused={isPaused} isDone={isDone}
          priority={priority} controlLoading={controlLoading} progressPercent={progressPercent}
          onPause={handlePause} onResume={handleResume} onCancel={handleCancel}
          onRerun={handleRerun} onFullRestart={() => handleRerun('s01_intake')} onEditRestart={handleEditRestart}
        />

        {(qualityData || complianceData) && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <QualityPanel qualityData={qualityData} />
            {complianceData && complianceData !== false && complianceData.status !== 'not_available' && (
              <section className="panel p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2"><ShieldCheck className="w-4 h-4 text-accent" /><span className="text-xs font-bold text-muted uppercase tracking-wider">Compliance Score</span></div>
                  {complianceData.score != null && <div className={`flex items-center justify-center w-14 h-14 rounded-full border-4 font-black text-lg ${complianceData.score >= 80 ? 'border-emerald-500 text-emerald-400 bg-emerald-900/20' : complianceData.score >= 60 ? 'border-yellow-500 text-yellow-400 bg-yellow-900/20' : 'border-red-500 text-red-400 bg-red-900/20'}`}>{complianceData.score}</div>}
                </div>
                <div className="flex flex-wrap gap-2">
                  {['HIPAA', 'GDPR', 'SOC2', 'PCI-DSS'].map(fw => {
                    const fwF = (complianceData.findings || []).filter(f => f.framework === fw);
                    const colorCls = fwF.some(f => f.severity === 'critical') ? 'bg-red-900/40 border-red-700 text-red-300' : fwF.some(f => f.severity === 'high') ? 'bg-yellow-900/40 border-yellow-700 text-yellow-300' : fwF.every(f => f.severity === 'pass') && fwF.length > 0 ? 'bg-emerald-900/40 border-emerald-700 text-emerald-300' : 'bg-slate-800 border-slate-700 text-slate-400';
                    return <span key={fw} className={`text-[10px] font-bold px-2 py-0.5 rounded border ${colorCls}`}>{fw}</span>;
                  })}
                </div>
                {(complianceData.findings || []).filter(f => f.severity !== 'pass').slice(0, 3).map((f, i) => (
                  <div key={i} className="flex items-start space-x-2 text-xs">
                    <span className={`shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${f.severity === 'critical' ? 'bg-red-900/60 text-red-300' : f.severity === 'high' ? 'bg-orange-900/60 text-orange-300' : 'bg-yellow-900/60 text-yellow-300'}`}>{f.severity}</span>
                    <span className="text-muted leading-snug">{f.description?.slice(0, 80) || f.title || 'Unknown finding'}</span>
                  </div>
                ))}
                {(complianceData.findings || []).filter(f => f.severity !== 'pass').length === 0 && <div className="text-xs text-emerald-400 font-medium">All compliance checks passed.</div>}
                <a href={`/api/portal/${id}/download`} className="flex items-center space-x-1.5 text-xs text-accent hover:underline"><Download className="w-3 h-3" /><span>Download Compliance PDF (ZIP)</span></a>
              </section>
            )}
          </div>
        )}

        <FeedbackPanel run={run} />

        {isRunning && (
          <section className="panel p-4 flex items-center space-x-3">
            <Loader2 className="w-4 h-4 text-accent animate-spin shrink-0" />
            <div><span className="text-xs text-muted uppercase font-bold tracking-wider">Currently: </span><span className="text-sm font-bold text-bright">{PHASE_NAMES[run.current_phase] || (run.current_phase ? run.current_phase.replace(/^p\d+[a-z]?_/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'Initializing...')}</span></div>
            <div className="flex-1 max-w-xs ml-auto"><div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden"><div className="h-full bg-accent transition-all duration-1000 ease-out" style={{ width: `${progressPercent}%` }} /></div></div>
            <span className="text-sm font-bold text-accent shrink-0">{Math.round(progressPercent)}%</span>
          </section>
        )}

        {isPaused && <section className="panel p-4 flex items-center space-x-3 border-warning/20"><Pause className="w-4 h-4 text-warning shrink-0" /><span className="text-sm font-bold text-warning">Pipeline paused - click Resume to continue</span></section>}

        {isRunning && specModalOpen && (
          <section className="panel p-4 flex items-center justify-between border-accent/30 bg-accent/5">
            <div className="flex items-center gap-3"><CheckCircle2 className="w-4 h-4 text-accent shrink-0" /><div><p className="text-sm font-bold text-accent">Spec Review Required</p><p className="text-xs text-muted">p01 completed - approve the parsed requirements to start code generation.</p></div></div>
            <button onClick={() => setSpecModalOpen(true)} className="text-xs px-3 py-1.5 bg-accent text-black font-semibold rounded-lg hover:bg-accent/80 transition-colors shrink-0">Review Spec</button>
          </section>
        )}

        {(() => {
          const p02bMeta = phases?.p02b_domain_ir?.metadata || phases?.p02b_domain_ir?.output?.metadata;
          const questions = p02bMeta?.clarifying_questions;
          if (!questions || questions === 0 || !isPaused) return null;
          return (
            <ClarifyingQuestionsPanel runId={run.run_id || run.id} questionCount={questions}
              onAnswered={async (answers) => {
                try { await api.resumeRun(run.run_id || run.id, { clarifying_answers: answers }); showToast('Answers submitted - pipeline resuming'); }
                catch (e) { showToast('Failed to submit answers: ' + (e.message || 'unknown error')); }
              }}
            />
          );
        })()}

        <ProjectLivePreviewPanel runId={run.run_id || run.id} currentPhase={run.current_phase} isRunning={isRunning} isPaused={isPaused} liveUrl={run.live_url} />

        <section>
          <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl overflow-hidden">
            <div className="px-3 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
              <div className="flex gap-1 overflow-x-auto custom-scrollbar pb-0.5">
                {[
                  { id: 'live', label: 'Live', icon: Radio, showDot: isRunning },
                  { id: 'logs', label: 'Logs', icon: List },
                  { id: 'artifacts', label: 'Artifacts', icon: FileCode },
                  { id: 'preview', label: 'Preview', icon: Monitor },
                  ...(run?.live_url ? [{ id: 'iframe', label: 'App Preview', icon: OpenTab }] : []),
                  { id: 'env', label: 'Env Vars', icon: Zap },
                  { id: 'run', label: 'Run App', icon: Play },
                  { id: 'trace', label: 'Trace', icon: ShieldCheck },
                  { id: 'council', label: 'Council', icon: Users },
                  { id: 'decisions', label: 'Decisions', icon: GitPullRequest },
                ].map((tab) => (
                  <button key={tab.id} onClick={() => setActiveArtifactTab(tab.id)}
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium whitespace-nowrap transition-all duration-200 ${activeArtifactTab === tab.id ? 'bg-white/[0.08] text-white shadow-sm' : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]'}`}>
                    <tab.icon className={`w-3.5 h-3.5 ${tab.showDot ? 'text-emerald-400 animate-pulse' : ''}`} />
                    <span>{tab.label}</span>
                    {tab.showDot && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />}
                  </button>
                ))}
              </div>
              {activeArtifactTab === 'preview' && previewHtml && (
                <div className="flex items-center space-x-2 pr-2">
                  <button onClick={() => setViewMode('mobile')} className={`p-1.5 rounded transition-colors ${viewMode === 'mobile' ? 'text-accent bg-accent/10' : 'text-muted hover:text-bright'}`}><Smartphone className="w-3.5 h-3.5" /></button>
                  <button onClick={() => setViewMode('desktop')} className={`p-1.5 rounded transition-colors ${viewMode === 'desktop' ? 'text-accent bg-accent/10' : 'text-muted hover:text-bright'}`}><Monitor className="w-3.5 h-3.5" /></button>
                  <button onClick={openPreviewTab} className="p-1.5 rounded text-muted hover:text-bright transition-colors"><OpenTab className="w-3.5 h-3.5" /></button>
                </div>
              )}
            </div>

            {activeArtifactTab === 'live' && <LiveFeedTab feedLines={feedLines} feedDone={feedDone} isRunning={isRunning} feedContainerRef={feedContainerRef} feedEndRef={feedEndRef} />}
            {activeArtifactTab === 'logs' && <LogViewer run={run} feedLines={feedLines} isRunning={isRunning} />}
            {activeArtifactTab === 'trace' && <TraceTab runId={run.run_id || run.id} />}
            {activeArtifactTab === 'artifacts' && <FileExplorer runId={id} fileTree={fileTree} isViewer={isViewer} onToast={showToast} />}
            {activeArtifactTab === 'preview' && (
              <div className="flex flex-col" style={{ height: '480px' }}>
                <div className="flex items-center space-x-2 px-4 py-2.5 border-b border-border bg-border/10 shrink-0">
                  {run.live_url && <button onClick={() => setPreviewMode('live')} className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${previewMode === 'live' ? 'bg-emerald-500 text-black' : 'bg-white/5 text-muted hover:text-bright'}`}><span className={`w-1.5 h-1.5 rounded-full ${previewMode === 'live' ? 'bg-black' : 'bg-emerald-400'} animate-pulse`} /><span>Live App</span></button>}
                  <button onClick={() => setPreviewMode('static')} className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${previewMode === 'static' ? 'bg-indigo-500 text-white' : 'bg-white/5 text-muted hover:text-bright'}`}><span>Generated UI</span></button>
                </div>
                {previewMode === 'live' && run.live_url && (
                  <div className="flex-1 flex flex-col overflow-hidden">
                    <div className="bg-black/30 px-3 py-1.5 border-b border-border flex items-center justify-between shrink-0"><span className="text-[10px] font-mono text-emerald-400">{run.live_url}</span><a href={run.live_url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-muted hover:text-bright transition-colors">Open tab</a></div>
                    <iframe src={run.live_url} className="flex-1 w-full border-none bg-white" title="Live Application" style={{ minHeight: '360px' }} />
                  </div>
                )}
                {previewMode === 'live' && !run.live_url && <div className="flex items-center justify-center flex-1 text-muted text-sm gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Waiting for live URL...</div>}
                {previewMode === 'static' && (
                  previewLoading ? <div className="flex items-center justify-center flex-1"><Loader2 className="w-8 h-8 text-accent animate-spin" /></div>
                  : !previewHtml ? (
                    fileTree === null ? <div className="flex items-center justify-center flex-1 text-muted text-sm">Loading file tree...</div>
                    : <div className="flex flex-col items-center justify-center flex-1 space-y-4 p-8 text-center"><Monitor className="w-12 h-12 text-muted/40" /><div><div className="text-bright font-bold mb-1">No frontend preview available.</div><div className="text-muted text-sm">The generated project is a backend API. Use the Artifacts tab to view the generated code.</div></div></div>
                  ) : (
                    <div className="flex-1 overflow-hidden flex flex-col bg-white">
                      {previewFile && <div className="bg-border/20 px-3 py-1.5 border-b border-border shrink-0"><span className="text-[10px] font-mono text-muted">{previewFile}</span></div>}
                      <div className="flex-1 flex items-start justify-center overflow-auto bg-[#0a0c10] p-4">
                        <iframe srcDoc={previewHtml} sandbox="allow-scripts allow-same-origin" style={{ width: viewMode === 'mobile' ? '390px' : '100%', height: '100%', minHeight: '320px', border: 'none', borderRadius: '6px', background: 'white', flexShrink: 0 }} title="Project Preview" />
                      </div>
                    </div>
                  )
                )}
              </div>
            )}
            {activeArtifactTab === 'iframe' && <AppPreviewPanel appRunning={appRunning} run={run} iframeDevice={iframeDevice} setIframeDevice={setIframeDevice} iframeKey={iframeKey} setIframeKey={setIframeKey} />}
            {activeArtifactTab === 'env' && <EnvVarsPanel runId={run.run_id || run.id} onToast={showToast} />}
            {activeArtifactTab === 'council' && <CouncilPanel runId={run.run_id || run.id} />}
            {activeArtifactTab === 'decisions' && <DecisionsPanel runId={run.run_id || run.id} />}
            {activeArtifactTab === 'run' && <RunAppPanel runId={run.run_id || run.id} onToast={showToast} onRunningChange={setAppRunning} />}
          </div>
        </section>

        <AgentEventsLog events={events} />

      </div>
    </div>
  );
};

export default ProjectView;
