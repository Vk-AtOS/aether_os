/**
 * useProjectView — all state, effects, and handlers for the ProjectView page.
 * Extracted so ProjectView.jsx stays under 600 lines (pure JSX composition).
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useRunStream } from './useRunStream';
import {
  PHASES, countFiles, findIndexHtml, formatEvent, stageStates, summariseRunEvents,
} from '../components/project/projectConstants';
import { confirmAction } from '../components/confirmAction';
import { apiError } from '../apiError';

export function useProjectView(id) {
  const navigate = useNavigate();

  const [run, setRun]                   = useState(null);
  const [nowMs, setNowMs]               = useState(0); // ticks while a run is live
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState(null);
  const [fileTree, setFileTree]         = useState(null);
  const [toast, setToast]               = useState(null);
  const [controlLoading, setControlLoading] = useState(null);
  const [priority, setPriority]             = useState('normal');
  const [deploying, setDeploying]           = useState(false);

  // Tabs follow the run (live while running, live preview once deployed) until the user picks one.
  const [pickedTab, setActiveArtifactTab] = useState(null);
  const [viewMode, setViewMode]     = useState('desktop');
  const [pickedPreviewMode, setPreviewMode] = useState(null);
  const [previewHtml, setPreviewHtml] = useState(null);
  const [previewDoneFor, setPreviewDoneFor] = useState(null); // the file tree the preview was loaded from
  const [previewFile, setPreviewFile] = useState(null);
  const [iframeDevice, setIframeDevice] = useState('desktop');
  const [iframeKey, setIframeKey]       = useState(0);

  const [feedLines, setFeedLines] = useState([]);
  const [feedDone, setFeedDone]   = useState(false);
  const feedEndRef         = useRef(null);
  const feedContainerRef   = useRef(null);
  const llmLineRef         = useRef('');

  const [appRunning, setAppRunning]         = useState(false);
  const [qualityData, setQualityData]       = useState(null);
  const [complianceData, setComplianceData] = useState(null);
  const [specReview, setSpecReview]         = useState(null);
  const [specModalOpen, setSpecModalOpen]   = useState(false);
  const [specApproving, setSpecApproving]   = useState(false);

  const [showGitHubModal, setShowGitHubModal]         = useState(false);
  const [showAddFeatureModal, setShowAddFeatureModal] = useState(false);
  const [gitHubToken, setGitHubToken]                 = useState('');
  const [gitHubRepoName, setGitHubRepoName]           = useState('');
  const [gitHubPushing, setGitHubPushing]             = useState(false);
  const [addFeatureText, setAddFeatureText]           = useState('');
  const [addingFeature, setAddingFeature]             = useState(false);
  const [branchPhaseState, setBranchPhaseState]       = useState('s03_backend');
  const [eventSummary, setEventSummary]               = useState({});

  // Skip reasons and the stopping stage are only in the event log; reload it when the status changes.
  useEffect(() => {
    if (!run?.status) return undefined;
    let alive = true;
    api.getRunEvents(id)
      .then((r) => { if (alive) setEventSummary(summariseRunEvents(r.data?.events)); })
      .catch((e) => console.warn('Could not load run events', e));
    return () => { alive = false; };
  }, [id, run?.status]);

  // ── Data fetching ──────────────────────────────────────────────────────────

  // Promise chains with no state set before the request: these run from effects.
  const fetchRunDetail = useCallback(() => api.getRun(id)
    .then((res) => {
      if (!res.data) throw new Error('Empty response from server');
      setRun(res.data);
      setPriority(res.data.priority || 'normal');
    })
    .catch((err) => setError(err.response?.status === 404
      ? 'Project not found (404). It may have been archived or deleted.'
      : apiError(err) || err.message || 'Failed to fetch project details.'))
    .finally(() => setLoading(false)), [id]);

  const fetchFileTree = useCallback(() => api.getRunFiles(id)
    .then((res) => setFileTree(res.data?.tree || []))
    .catch(() => setFileTree([])), [id]);

  // previewTried stops the effect below from asking again for a tree with no index.html.
  const previewTried = useRef(null);
  const loadPreview = useCallback(() => {
    const indexFile = fileTree && findIndexHtml(fileTree);
    previewTried.current = fileTree;
    if (!indexFile) return;
    const tree = fileTree;
    api.getFileContent(id, indexFile.path)
      .then((res) => { setPreviewFile(indexFile.path); setPreviewHtml(res.data?.content || ''); })
      .catch(() => setPreviewHtml(null))
      .finally(() => setPreviewDoneFor(tree));
  }, [fileTree, id]);

  // ── Effects ────────────────────────────────────────────────────────────────

  // Poll while the run is live (or not loaded yet); the timer reads the latest status from a ref.
  const pollRef = useRef(true);
  useEffect(() => {
    pollRef.current = !error && (!run || run.status === 'running' || run.status === 'paused');
  }, [error, run]);
  useEffect(() => {
    fetchRunDetail();
    fetchFileTree();
    const interval = setInterval(() => { if (pollRef.current) fetchRunDetail(); }, 4000);
    return () => clearInterval(interval);
  }, [fetchRunDetail, fetchFileTree]);

  const runIsDone = ['completed', 'failed', 'cancelled', 'interrupted'].includes(run?.status);
  useEffect(() => {
    if (!run?.started_at || (runIsDone && run.finished_at)) return undefined;
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [run?.started_at, run?.finished_at, runIsDone]);
  const elapsed = !run?.started_at ? 0
    : runIsDone && run.finished_at ? Math.floor((run.finished_at - run.started_at) / 1000)
      : nowMs ? Math.max(0, Math.floor((nowMs - run.started_at) / 1000)) : 0;

  const activeArtifactTab = pickedTab ?? (run?.status === 'running' ? 'live' : 'artifacts');
  const previewMode = pickedPreviewMode ?? (run?.live_url ? 'live' : 'static');
  const previewLoading = activeArtifactTab === 'preview' && Boolean(fileTree && findIndexHtml(fileTree))
    && previewDoneFor !== fileTree;

  useEffect(() => {
    if (activeArtifactTab === 'preview' && fileTree && previewTried.current !== fileTree) loadPreview();
  }, [activeArtifactTab, fileTree, loadPreview]);

  useEffect(() => {
    if (!run) return;
    if (!['completed', 'passed'].includes(run.status)) return;
    if (qualityData === null) api.getRunQuality(id).then(r => setQualityData(r.data?.quality || null)).catch(() => setQualityData(false));
    if (complianceData === null) api.getRunCompliance(id).then(r => setComplianceData(r.data || null)).catch(() => setComplianceData(false));
  }, [run?.status, id]); // eslint-disable-line react-hooks/exhaustive-deps

  // SSE live feed
  const appendLine = useCallback((line) => {
    if (!line) return;
    setFeedLines((prev) => [...prev.slice(-300), line]);
  }, []);

  const handleStreamEvent = useCallback((event) => {
    if (event.type === 'llm_chunk') {
      llmLineRef.current += event.text || '';
      const nl = llmLineRef.current.lastIndexOf('\n');
      if (nl !== -1) {
        const flushed = llmLineRef.current.slice(0, nl);
        llmLineRef.current = llmLineRef.current.slice(nl + 1);
        flushed.split('\n').forEach((l) => appendLine(l));
      }
    } else {
      if (llmLineRef.current) { appendLine(llmLineRef.current); llmLineRef.current = ''; }
      const line = formatEvent(event);
      if (line) appendLine(line);
    }
    if (event.type === 'spec_review_ready') {
      api.getRunSpec(id).then(r => { setSpecReview(r.data?.spec || {}); setSpecModalOpen(true); }).catch(() => setSpecModalOpen(true));
    }
    if (event.type === 'app_started') setAppRunning(true);
    if (event.type === 'pipeline_complete') {
      if (llmLineRef.current) { appendLine(llmLineRef.current); llmLineRef.current = ''; }
      setFeedDone(true);
      fetchRunDetail(); fetchFileTree();
    }
  }, [id, appendLine, fetchRunDetail, fetchFileTree]);

  useRunStream(id, { enabled: !!run && run.status === 'running', onEvent: handleStreamEvent });

  useEffect(() => {
    if (activeArtifactTab === 'live' && feedContainerRef.current) {
      feedContainerRef.current.scrollTop = feedContainerRef.current.scrollHeight;
    }
  }, [feedLines, activeArtifactTab]);

  // ── Controls ───────────────────────────────────────────────────────────────

  const showToast = useCallback((msg) => setToast(msg), []);

  const handlePause = useCallback(async () => {
    setControlLoading('pause');
    try { await api.pauseRun(id); setRun((p) => p ? { ...p, status: 'paused' } : p); showToast('Pipeline paused'); setTimeout(fetchRunDetail, 2000); }
    catch (e) { showToast('Failed to pause: ' + (e.message || 'error')); }
    finally { setControlLoading(null); }
  }, [id, fetchRunDetail, showToast]);

  const handleResume = useCallback(async () => {
    setControlLoading('resume');
    try { await api.resumeRun(id); setRun((p) => p ? { ...p, status: 'running' } : p); showToast('Pipeline resumed'); setTimeout(fetchRunDetail, 2000); }
    catch (e) { showToast('Failed to resume: ' + (e.message || 'error')); }
    finally { setControlLoading(null); }
  }, [id, fetchRunDetail, showToast]);

  const handleCancel = useCallback(async () => {
    if (!(await confirmAction('Cancel this run? This cannot be undone.'))) return;
    setControlLoading('cancel');
    try { await api.cancelRun(id); setRun((p) => p ? { ...p, status: 'cancelled' } : p); showToast('Pipeline cancelled'); setTimeout(fetchRunDetail, 2000); }
    catch (e) { showToast('Failed to cancel: ' + (e.message || 'error')); }
    finally { setControlLoading(null); }
  }, [id, fetchRunDetail, showToast]);

  const handlePriorityCycle = useCallback(async (priority, PRIORITY_CYCLE) => {
    const next = PRIORITY_CYCLE[(PRIORITY_CYCLE.indexOf(priority) + 1) % PRIORITY_CYCLE.length];
    setPriority(next);
    try { await api.setRunPriority(id, next); } catch { setPriority(priority); }
  }, [id]);

  const handleRerun = useCallback(async (fromPhase) => {
    try { const res = await api.rerunFromPhase(id, fromPhase); navigate(`/project/${res.data.run_id}`); }
    catch (e) { showToast('Failed to start rerun: ' + (apiError(e) || e.message || 'unknown error')); }
  }, [id, navigate, showToast]);

  // Failed/cancelled: continue this same run from its checkpoint (the stage that stopped it).
  const handleRestart = useCallback(async () => {
    try { await api.restartRun(id); showToast('Run restarted'); fetchRunDetail(); }
    catch (e) { showToast('Restart failed: ' + (apiError(e) || e.message || 'unknown error')); }
  }, [id, showToast, fetchRunDetail]);

  const handleEditRestart = useCallback(async (editedReq) => {
    try {
      const res = await api.startPipeline({ raw_input: editedReq, project_name: run?.project_name, domain: run?.domain || 'general', client_id: run?.client_id || 'client-001' });
      navigate(`/project/${res.data.run_id}`);
    } catch (e) { showToast('Failed to start run: ' + (apiError(e) || e.message || 'unknown error')); }
  }, [run, navigate, showToast]);

  const handleDeploy = useCallback(async () => {
    setDeploying(true);
    try {
      const res = await api.deployRun(id);
      if (res.data?.live_url) { setRun((p) => p ? { ...p, live_url: res.data.live_url } : p); setPreviewMode('live'); showToast('App is live at ' + res.data.live_url); }
      else showToast('Deploy failed: ' + (res.data?.error || 'unknown error'));
    } catch (e) { showToast('Deploy error: ' + (apiError(e) || e.message || 'unknown')); }
    finally { setDeploying(false); }
  }, [id, showToast]);

  const handleStopDeploy = useCallback(async () => {
    try { await api.stopDeploy(id); setRun((p) => p ? { ...p, live_url: null } : p); setPreviewMode('static'); showToast('Container stopped'); }
    catch (e) { showToast('Stop failed: ' + (apiError(e) || e.message || 'unknown')); }
  }, [id, showToast]);

  const handleDownload = useCallback(async () => {
    try {
      const res = await api.downloadRunZip(id);
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/zip' }));
      const a = document.createElement('a'); a.href = url; a.download = `${run?.project_name || id}.zip`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { showToast('Download failed: ' + (apiError(e) || e.message || 'unknown')); }
  }, [id, run, showToast]);

  const handlePushGitHub = useCallback(async () => {
    if (!gitHubToken || !gitHubRepoName) return showToast('GitHub token and repo name required');
    setGitHubPushing(true);
    try {
      const res = await api.pushToGitHub(id, { github_token: gitHubToken, repo_name: gitHubRepoName });
      showToast('Pushed to GitHub: ' + (res.data?.html_url || gitHubRepoName));
      setShowGitHubModal(false);
    } catch (e) { showToast('Push failed: ' + (apiError(e) || e.message)); }
    finally { setGitHubPushing(false); }
  }, [id, gitHubToken, gitHubRepoName, showToast]);

  const handleAddFeature = useCallback(async () => {
    if (!addFeatureText.trim()) return showToast('Describe the feature to add');
    setAddingFeature(true);
    try {
      const res = await api.branchRun(id, branchPhaseState || 's03_backend', addFeatureText.trim());
      showToast('Branch run started'); setShowAddFeatureModal(false); navigate(`/project/${res.data?.run_id}`);
    } catch (e) { showToast('Failed: ' + (apiError(e) || e.message)); }
    finally { setAddingFeature(false); }
  }, [id, addFeatureText, branchPhaseState, navigate, showToast]);

  // ── Derived state ──────────────────────────────────────────────────────────

  const stages = useMemo(() => stageStates(run, eventSummary), [run, eventSummary]);
  const getPhaseStatus = useCallback((phaseId) => stages[phaseId]?.status || 'pending', [stages]);

  const completedPhases = useMemo(() =>
    PHASES.filter((p) => ['passed', 'completed'].includes(getPhaseStatus(p))).length,
    [getPhaseStatus]
  );
  const progressPercent = (completedPhases / PHASES.length) * 100;

  const phasesCompleted = useMemo(() =>
    Object.values(run?.phases || {}).filter(p => p.status === 'completed' || p.status === 'pass').length,
    [run?.phases]
  );
  const totalPhases = useMemo(() => Object.keys(run?.phases || {}).length || PHASES.length, [run?.phases]);
  const eta = useMemo(() => {
    if (run?.status !== 'running' || phasesCompleted <= 0 || elapsed <= 0) return null;
    return Math.max(0, (elapsed / phasesCompleted) * totalPhases - elapsed);
  }, [run?.status, phasesCompleted, totalPhases, elapsed]);

  const artifactCount = useMemo(() => fileTree ? countFiles(fileTree) : 0, [fileTree]);

  return {
    // state
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
    // derived
    getPhaseStatus, stages, completedPhases, progressPercent, phasesCompleted, totalPhases, eta, artifactCount,
    // handlers
    fetchRunDetail, fetchFileTree, showToast,
    handlePause, handleResume, handleCancel, handlePriorityCycle, handleRerun, handleEditRestart, handleRestart,
    handleDeploy, handleStopDeploy, handleDownload, handlePushGitHub, handleAddFeature,
    navigate,
  };
}
