/**
 * useProjectView — all state, effects, and handlers for the ProjectView page.
 * Extracted so ProjectView.jsx stays under 600 lines (pure JSX composition).
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { PHASES, countFiles, findIndexHtml, formatEvent } from '../components/project/projectConstants';
import { confirmAction } from '../components/confirmAction';

export function useProjectView(id) {
  const navigate = useNavigate();

  const [run, setRun]                   = useState(null);
  const [elapsed, setElapsed]           = useState(0);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState(null);
  const [fileTree, setFileTree]         = useState(null);
  const [toast, setToast]               = useState(null);
  const [controlLoading, setControlLoading] = useState(null);
  const [priority, setPriority]             = useState('normal');
  const [deploying, setDeploying]           = useState(false);

  const [activeArtifactTab, setActiveArtifactTab] = useState('artifacts');
  const [viewMode, setViewMode]     = useState('desktop');
  const [previewMode, setPreviewMode] = useState('static');
  const [previewHtml, setPreviewHtml] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewFile, setPreviewFile] = useState(null);
  const [iframeDevice, setIframeDevice] = useState('desktop');
  const [iframeKey, setIframeKey]       = useState(0);

  const [feedLines, setFeedLines] = useState([]);
  const [feedDone, setFeedDone]   = useState(false);
  const feedEndRef         = useRef(null);
  const feedContainerRef   = useRef(null);
  const esRef              = useRef(null);
  const llmLineRef         = useRef('');
  const reconnectAttempts  = useRef(0);

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

  // ── Data fetching ──────────────────────────────────────────────────────────

  const fetchRunDetail = useCallback(async () => {
    try {
      const res = await api.getRun(id);
      if (!res.data) throw new Error('Empty response from server');
      setRun(res.data);
      setPriority(res.data.priority || 'normal');
    } catch (err) {
      setError(err.response?.status === 404
        ? 'Project not found (404). It may have been archived or deleted.'
        : err.message || 'Failed to fetch project details.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const fetchFileTree = useCallback(async () => {
    try { const res = await api.getRunFiles(id); setFileTree(res.data?.tree || []); }
    catch { setFileTree([]); }
  }, [id]);

  const loadPreview = useCallback(async () => {
    if (!fileTree) return;
    const indexFile = findIndexHtml(fileTree);
    if (!indexFile) { setPreviewHtml(null); setPreviewFile(null); return; }
    setPreviewFile(indexFile.path);
    setPreviewLoading(true);
    try { const res = await api.getFileContent(id, indexFile.path); setPreviewHtml(res.data?.content || ''); }
    catch { setPreviewHtml(null); }
    finally { setPreviewLoading(false); }
  }, [fileTree, id]);

  // ── Effects ────────────────────────────────────────────────────────────────

  useEffect(() => {
    fetchRunDetail();
    fetchFileTree();
    const interval = setInterval(() => {
      if (!error && (!run || run.status === 'running' || run.status === 'paused')) fetchRunDetail();
    }, 4000);
    return () => clearInterval(interval);
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!run?.started_at) return;
    const isDone = ['completed', 'failed', 'cancelled', 'interrupted'].includes(run.status);
    if (isDone && run.finished_at) { setElapsed(Math.floor((run.finished_at - run.started_at) / 1000)); return; }
    const tick = () => setElapsed(Math.floor((Date.now() - run.started_at) / 1000));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [run?.started_at, run?.finished_at, run?.status]);

  useEffect(() => {
    if (activeArtifactTab === 'preview' && fileTree && previewHtml === null && !previewLoading) loadPreview();
  }, [activeArtifactTab, fileTree, previewHtml, previewLoading, loadPreview]);

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

  useEffect(() => {
    if (!run || run.status !== 'running') return;
    if (esRef.current) return;

    let cancelled = false;
    let done = false;

    const scheduleReconnect = () => {
      if (cancelled || done) return;
      const delay = Math.min(1000 * 2 ** reconnectAttempts.current, 30000);
      reconnectAttempts.current += 1;
      setTimeout(() => { if (!cancelled && !done) connectSSE(); }, delay);
    };

    const connectSSE = async () => {
      try {
        const exchRes = await fetch(`/api/factory/runs/${id}/sse-token`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${api.getToken()}`, 'Content-Type': 'application/json' },
        });
        if (!exchRes.ok || cancelled) { if (!exchRes.ok) scheduleReconnect(); return; }
        const { sse_token } = await exchRes.json();
        if (cancelled) return;

        const es = new EventSource(`/api/factory/runs/${id}/stream?sse_token=${encodeURIComponent(sse_token)}`);
        esRef.current = es;

        es.onmessage = (e) => {
          let event;
          try { event = JSON.parse(e.data); } catch { return; }

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
            done = true; setFeedDone(true); es.close(); esRef.current = null;
            fetchRunDetail(); fetchFileTree();
          }
        };

        es.onerror = () => { es.close(); esRef.current = null; scheduleReconnect(); };
      } catch (err) {
        if (import.meta.env.DEV) console.error('SSE connect failed:', err);
        scheduleReconnect();
      }
    };

    reconnectAttempts.current = 0;
    connectSSE();
    return () => { cancelled = true; if (esRef.current) { esRef.current.close(); esRef.current = null; } };
  }, [run?.status, id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (run?.status === 'running' && activeArtifactTab !== 'live') setActiveArtifactTab('live');
  }, [run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (run?.live_url) setPreviewMode('live'); }, [run?.live_url]);

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
    catch (e) { showToast('Failed to start rerun: ' + (e.message || 'unknown error')); }
  }, [id, navigate, showToast]);

  const handleEditRestart = useCallback(async (editedReq) => {
    try {
      const res = await api.startPipeline({ raw_input: editedReq, project_name: run?.project_name, domain: run?.domain || 'general', client_id: run?.client_id || 'client-001' });
      navigate(`/project/${res.data.run_id}`);
    } catch (e) { showToast('Failed to start run: ' + (e.message || 'unknown error')); }
  }, [id, run, navigate, showToast]);

  const handleDeploy = useCallback(async () => {
    setDeploying(true);
    try {
      const res = await api.deployRun(id);
      if (res.data?.live_url) { setRun((p) => p ? { ...p, live_url: res.data.live_url } : p); setPreviewMode('live'); showToast('App is live at ' + res.data.live_url); }
      else showToast('Deploy failed: ' + (res.data?.error || 'unknown error'));
    } catch (e) { showToast('Deploy error: ' + (e.message || 'unknown')); }
    finally { setDeploying(false); }
  }, [id, showToast]);

  const handleStopDeploy = useCallback(async () => {
    try { await api.stopDeploy(id); setRun((p) => p ? { ...p, live_url: null } : p); setPreviewMode('static'); showToast('Container stopped'); }
    catch (e) { showToast('Stop failed: ' + (e.message || 'unknown')); }
  }, [id, showToast]);

  const handleDownload = useCallback(async () => {
    try {
      const res = await api.downloadRunZip(id);
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/zip' }));
      const a = document.createElement('a'); a.href = url; a.download = `${run?.project_name || id}.zip`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { showToast('Download failed: ' + (e.message || 'unknown')); }
  }, [id, run, showToast]);

  const handlePushGitHub = useCallback(async () => {
    if (!gitHubToken || !gitHubRepoName) return showToast('GitHub token and repo name required');
    setGitHubPushing(true);
    try {
      const res = await api.pushToGitHub(id, { github_token: gitHubToken, repo_name: gitHubRepoName });
      showToast('Pushed to GitHub: ' + (res.data?.html_url || gitHubRepoName));
      setShowGitHubModal(false);
    } catch (e) { showToast('Push failed: ' + (e.response?.data?.detail || e.message)); }
    finally { setGitHubPushing(false); }
  }, [id, gitHubToken, gitHubRepoName, showToast]);

  const handleAddFeature = useCallback(async () => {
    if (!addFeatureText.trim()) return showToast('Describe the feature to add');
    setAddingFeature(true);
    try {
      const res = await api.branchRun(id, branchPhaseState || 's03_backend', addFeatureText.trim());
      showToast('Branch run started'); setShowAddFeatureModal(false); navigate(`/project/${res.data?.run_id}`);
    } catch (e) { showToast('Failed: ' + (e.response?.data?.detail || e.message)); }
    finally { setAddingFeature(false); }
  }, [id, addFeatureText, branchPhaseState, navigate, showToast]);

  // ── Derived state ──────────────────────────────────────────────────────────

  const getPhaseStatus = useCallback((phaseId) => {
    if (run?.phases?.[phaseId]) return run.phases[phaseId].status;
    if (['completed', 'passed'].includes(run?.status) && !Object.keys(run?.phases || {}).length) return 'passed';
    if (run?.current_phase === phaseId) return 'running';
    const currentIdx = PHASES.indexOf(run?.current_phase);
    const thisIdx    = PHASES.indexOf(phaseId);
    if (currentIdx > 0 && thisIdx < currentIdx) return 'passed';
    return 'pending';
  }, [run]);

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
    getPhaseStatus, completedPhases, progressPercent, phasesCompleted, totalPhases, eta, artifactCount,
    // handlers
    fetchRunDetail, fetchFileTree, showToast,
    handlePause, handleResume, handleCancel, handlePriorityCycle, handleRerun, handleEditRestart,
    handleDeploy, handleStopDeploy, handleDownload, handlePushGitHub, handleAddFeature,
    navigate,
  };
}
