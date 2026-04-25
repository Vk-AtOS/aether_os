import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import PhaseBadge from '../components/PhaseBadge';
import {
  Terminal,
  ExternalLink,
  FileCode,
  ChevronLeft,
  ChevronDown,
  Loader2,
  AlertTriangle,
  Folder,
  FolderOpen,
  File,
  Pause,
  Play,
  X,
  RotateCcw,
  Smartphone,
  Monitor,
  ExternalLink as OpenTab,
} from 'lucide-react';

// ── Constants ────────────────────────────────────────────────────────────────

const PHASES = [
  'p01_intake_requirements',
  'p02_architecture',
  'p03_scaffolding',
  'p04_backend',
  'p05_frontend',
  'p06_review_security',
  'p07_testing',
  'p08_cicd_deployment',
  'p09_observability',
  'p10_docs_delivery',
];

const PHASE_NAMES = {
  p01_intake_requirements: 'Intake',
  p02_architecture:        'Architecture',
  p03_scaffolding:         'Scaffolding',
  p04_backend:             'Backend',
  p05_frontend:            'Frontend',
  p06_review_security:     'Review',
  p07_testing:             'Testing',
  p08_cicd_deployment:     'CI/CD',
  p09_observability:       'Observability',
  p10_docs_delivery:       'Delivery',
};

const PRIORITY_CONFIG = {
  high:   { label: 'High',   color: 'text-red-400',     dot: 'bg-red-400'   },
  normal: { label: 'Normal', color: 'text-slate-400',   dot: 'bg-slate-400' },
  low:    { label: 'Low',    color: 'text-blue-400',    dot: 'bg-blue-400'  },
};
const PRIORITY_CYCLE = ['high', 'normal', 'low'];

// ── Helpers ──────────────────────────────────────────────────────────────────

const formatBytes = (bytes) => {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}K`;
  return `${(bytes / 1024 / 1024).toFixed(1)}M`;
};

const countFiles = (items) => {
  let n = 0;
  for (const item of items) {
    if (item.type === 'file') n++;
    else if (item.children) n += countFiles(item.children);
  }
  return n;
};

const formatTime = (seconds) => {
  if (!seconds || seconds < 0) return '0m 00s';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s.toString().padStart(2, '0')}s`;
};

// Recursively find first index.html in tree
const findIndexHtml = (items) => {
  for (const item of items) {
    if (item.type === 'file' && item.name === 'index.html') return item;
    if (item.children) {
      const found = findIndexHtml(item.children);
      if (found) return found;
    }
  }
  return null;
};

// ── FileTree component ───────────────────────────────────────────────────────

const FileTree = ({ items, level = 0, onFileClick, selectedPath }) => {
  const [openDirs, setOpenDirs] = useState({});
  const toggle = (path) =>
    setOpenDirs((prev) => ({ ...prev, [path]: !prev[path] }));

  return (
    <div className={level > 0 ? 'ml-3 border-l border-border/30 pl-2' : ''}>
      {items.map((item) =>
        item.type === 'directory' ? (
          <div key={item.path}>
            <button
              onClick={() => toggle(item.path)}
              className="w-full flex items-center space-x-1.5 py-1 px-2 rounded hover:bg-border/20 text-left text-xs"
            >
              {openDirs[item.path]
                ? <FolderOpen className="w-3.5 h-3.5 text-accent shrink-0" />
                : <Folder className="w-3.5 h-3.5 text-accent shrink-0" />}
              <span className="text-bright font-medium truncate">{item.name}</span>
              <ChevronDown className={`w-3 h-3 text-muted ml-auto transition-transform shrink-0 ${openDirs[item.path] ? '' : '-rotate-90'}`} />
            </button>
            {openDirs[item.path] && item.children && (
              <FileTree items={item.children} level={level + 1} onFileClick={onFileClick} selectedPath={selectedPath} />
            )}
          </div>
        ) : (
          <button
            key={item.path}
            onClick={() => onFileClick(item)}
            className={`w-full flex items-center space-x-1.5 py-1 px-2 rounded text-left text-xs transition-colors ${
              selectedPath === item.path
                ? 'bg-accent/20 text-accent'
                : 'hover:bg-border/20 text-muted hover:text-bright'
            }`}
          >
            <File className="w-3 h-3 shrink-0" />
            <span className="truncate">{item.name}</span>
            <span className="ml-auto text-[9px] text-muted shrink-0">{formatBytes(item.size_bytes)}</span>
          </button>
        )
      )}
    </div>
  );
};

// ── Main component ───────────────────────────────────────────────────────────

const ProjectView = () => {
  const { id } = useParams();
  const navigate = useNavigate();

  const [run, setRun]                   = useState(null);
  const [elapsed, setElapsed]           = useState(0);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState(null);
  const [fileTree, setFileTree]         = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent]   = useState(null);
  const [fileLoading, setFileLoading]   = useState(false);
  const [curlCopied, setCurlCopied]     = useState(false);

  // Controls
  const [controlLoading, setControlLoading] = useState(null); // 'pause'|'resume'|'cancel'|null
  const [priority, setPriority]             = useState('normal');

  // ARTIFACTS / PREVIEW tabs
  const [activeArtifactTab, setActiveArtifactTab] = useState('artifacts');
  const [viewMode, setViewMode]                   = useState('desktop'); // 'mobile'|'desktop'
  const [previewHtml, setPreviewHtml]             = useState(null);
  const [previewLoading, setPreviewLoading]       = useState(false);
  const [previewFile, setPreviewFile]             = useState(null);

  // Re-run dropdown
  const [rerunOpen, setRerunOpen] = useState(false);
  const rerunRef = useRef(null);

  const logEndRef = useRef(null);

  // ── Data fetching ──────────────────────────────────────────────────────────

  const fetchRunDetail = async () => {
    try {
      const res = await api.getRun(id);
      if (!res.data) throw new Error('Empty response from server');
      setRun(res.data);
      setPriority(res.data.priority || 'normal');
      if (res.data.status === 'failed') {
        setError(res.data.message || 'The pipeline failed to complete.');
      }
    } catch (err) {
      if (err.response?.status === 404) {
        setError('Project not found (404). It may have been archived or deleted.');
      } else {
        setError(err.message || 'Failed to fetch project details.');
      }
    } finally {
      setLoading(false);
    }
  };

  const fetchFileTree = async () => {
    try {
      const res = await api.getRunFiles(id);
      setFileTree(res.data?.tree || []);
    } catch {
      setFileTree([]);
    }
  };

  const handleFileClick = async (file) => {
    setSelectedFile(file);
    setFileLoading(true);
    setFileContent(null);
    try {
      const res = await api.getFileContent(id, file.path);
      setFileContent(res.data);
    } catch {
      setFileContent({ error: 'Failed to load file content.' });
    } finally {
      setFileLoading(false);
    }
  };

  // ── Preview tab ────────────────────────────────────────────────────────────

  const loadPreview = useCallback(async () => {
    if (!fileTree) return;
    const indexFile = findIndexHtml(fileTree);
    if (!indexFile) {
      setPreviewHtml(null);
      setPreviewFile(null);
      return;
    }
    setPreviewFile(indexFile.path);
    setPreviewLoading(true);
    try {
      const res = await api.getFileContent(id, indexFile.path);
      setPreviewHtml(res.data?.content || '');
    } catch {
      setPreviewHtml(null);
    } finally {
      setPreviewLoading(false);
    }
  }, [fileTree, id]);

  useEffect(() => {
    if (activeArtifactTab === 'preview' && fileTree && previewHtml === null && !previewLoading) {
      loadPreview();
    }
  }, [activeArtifactTab, fileTree, previewHtml, previewLoading, loadPreview]);

  // ── Controls ───────────────────────────────────────────────────────────────

  const handlePause = async () => {
    setControlLoading('pause');
    try { await api.pauseRun(id); await fetchRunDetail(); } finally { setControlLoading(null); }
  };
  const handleResume = async () => {
    setControlLoading('resume');
    try { await api.resumeRun(id); await fetchRunDetail(); } finally { setControlLoading(null); }
  };
  const handleCancel = async () => {
    if (!window.confirm('Cancel this run? This cannot be undone.')) return;
    setControlLoading('cancel');
    try { await api.cancelRun(id); await fetchRunDetail(); } finally { setControlLoading(null); }
  };
  const handlePriorityCycle = async () => {
    const next = PRIORITY_CYCLE[(PRIORITY_CYCLE.indexOf(priority) + 1) % PRIORITY_CYCLE.length];
    setPriority(next);
    try { await api.setRunPriority(id, next); } catch { setPriority(priority); }
  };
  const handleRerun = async (fromPhase) => {
    setRerunOpen(false);
    try {
      const res = await api.rerunFromPhase(id, fromPhase);
      navigate(`/project/${res.data.run_id}`);
    } catch (e) {
      alert('Failed to start rerun: ' + (e.message || 'unknown error'));
    }
  };

  // Close rerun dropdown on outside click
  useEffect(() => {
    const handler = (e) => { if (rerunRef.current && !rerunRef.current.contains(e.target)) setRerunOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // ── Effects ────────────────────────────────────────────────────────────────

  useEffect(() => {
    fetchRunDetail();
    fetchFileTree();
    const interval = setInterval(() => {
      if (!error && (!run || run.status === 'running')) fetchRunDetail();
    }, 4000);
    return () => clearInterval(interval);
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!run?.started_at) return;
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - run.started_at) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [run?.started_at]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [run?.events]);

  // ── Derived state ──────────────────────────────────────────────────────────

  const getPhaseStatus = (phaseId) => {
    if (run?.phases?.[phaseId]) return run.phases[phaseId].status;
    if (run?.current_phase === phaseId) return 'running';
    const currentIdx = PHASES.indexOf(run?.current_phase);
    const thisIdx    = PHASES.indexOf(phaseId);
    if (currentIdx > 0 && thisIdx < currentIdx) return 'passed';
    return 'pending';
  };

  const completedPhases = PHASES.filter((p) =>
    ['passed', 'completed', 'timeout'].includes(getPhaseStatus(p))
  ).length;
  const progressPercent = (completedPhases / PHASES.length) * 100;

  // ── Loading / error states ─────────────────────────────────────────────────

  if (loading && !run) {
    return (
      <div className="flex flex-col items-center justify-center h-full space-y-4">
        <Loader2 className="w-12 h-12 text-accent animate-spin" />
        <p className="text-muted font-medium">Loading project details...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full p-6">
        <div className="text-center panel p-12 max-w-lg border-danger/20 shadow-2xl">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-danger/10 mb-6">
            <AlertTriangle className="w-8 h-8 text-danger" />
          </div>
          <h2 className="text-danger text-2xl font-bold mb-4">Pipeline Error</h2>
          <div className="text-bright font-mono text-sm bg-black/40 p-4 rounded-lg border border-border mb-6 break-words">
            {error}
          </div>
          <div className="flex flex-col space-y-3">
            <button onClick={() => navigate('/new')} className="w-full py-3 bg-indigo-600 text-white rounded-lg font-bold hover:bg-indigo-700 transition-colors">
              START NEW PIPELINE
            </button>
            <button onClick={() => { setError(null); setLoading(true); fetchRunDetail(); }} className="w-full py-3 bg-border/50 text-bright rounded-lg font-bold hover:bg-border transition-colors border border-border">
              RETRY FETCH
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex flex-col items-center justify-center h-full space-y-4">
        <AlertTriangle className="w-12 h-12 text-warning" />
        <p className="text-muted font-medium">Project not found.</p>
        <button onClick={() => navigate('/projects')} className="text-accent hover:underline">Back to Projects</button>
      </div>
    );
  }

  const events = run.events || [];
  const phases = run.phases || {};

  const passedCount = PHASES.filter((p) => ['passed', 'completed'].includes(getPhaseStatus(p))).length;
  const successRate = completedPhases > 0 ? Math.round((passedCount / completedPhases) * 100) : 0;
  const artifactCount = fileTree ? countFiles(fileTree) : 0;

  const curlCmd = `curl -s http://localhost:8000/health`;
  const copyCurl = () => {
    navigator.clipboard.writeText(curlCmd);
    setCurlCopied(true);
    setTimeout(() => setCurlCopied(false), 2000);
  };

  const runStatus = run.status;
  const isRunning = runStatus === 'running';
  const isPaused  = runStatus === 'paused';
  const isDone    = ['completed', 'failed', 'cancelled'].includes(runStatus);
  const priConf   = PRIORITY_CONFIG[priority] || PRIORITY_CONFIG.normal;

  // Open preview in new tab
  const openPreviewTab = () => {
    if (!previewHtml) return;
    const blob = new Blob([previewHtml], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden -m-6">

      {/* ── LEFT: Phase sidebar ──────────────────────────────────────────────── */}
      <div className="w-52 bg-panel border-r border-border flex flex-col shrink-0 overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <button
            onClick={() => navigate('/projects')}
            className="flex items-center space-x-1.5 text-xs text-muted hover:text-bright transition-colors"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            <span>All Projects</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto py-2 custom-scrollbar">
          {PHASES.map((p) => {
            const st = getPhaseStatus(p);
            const pData = phases[p] || {};
            const dur = pData.duration_s != null
              ? pData.duration_s < 60 ? `${pData.duration_s}s` : `${Math.round(pData.duration_s / 60)}m`
              : null;
            const isActive = st === 'running' || run.current_phase === p;
            const isDone2  = st === 'passed' || st === 'completed' || st === 'timeout';
            const isFailed = st === 'failed';

            return (
              <button
                key={p}
                onClick={() => navigate(`/project/${id}/phase/${p}`)}
                className={`w-full flex items-center px-4 py-2.5 text-xs transition-colors group text-left ${
                  isActive ? 'bg-accent/10 border-r-2 border-accent text-accent' : 'hover:bg-white/[0.03] text-muted hover:text-bright'
                }`}
              >
                <span className={`w-2 h-2 rounded-full shrink-0 mr-2.5 ${
                  isDone2 ? 'bg-emerald-500' : isActive ? 'bg-accent animate-pulse' : isFailed ? 'bg-danger' : 'bg-slate-700'
                }`} />
                <span className="flex-1 truncate font-medium">{PHASE_NAMES[p]}</span>
                {dur && <span className="text-[9px] text-muted ml-1 shrink-0 font-mono">{dur}</span>}
              </button>
            );
          })}
        </div>

        <div className="px-4 py-3 border-t border-border">
          <div className="flex justify-between text-[9px] font-bold text-muted uppercase mb-1.5">
            <span>Progress</span>
            <span>{completedPhases}/10</span>
          </div>
          <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div className="h-full bg-accent transition-all duration-1000" style={{ width: `${progressPercent}%` }} />
          </div>
        </div>
      </div>

      {/* ── RIGHT: Main scrollable area ─────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">

        {/* Header */}
        <header className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <h1 className="text-xl font-bold text-bright truncate max-w-sm">
              {run.project_name || 'Untitled Project'}
            </h1>
            <PhaseBadge status={run.status} size="md" />

            {/* Priority badge — click to cycle */}
            <button
              onClick={handlePriorityCycle}
              className={`flex items-center space-x-1.5 text-xs font-bold px-2.5 py-1 rounded-full border border-border/50 hover:bg-border/30 transition-colors ${priConf.color}`}
              title="Click to change priority"
            >
              <span className={`w-1.5 h-1.5 rounded-full ${priConf.dot}`} />
              <span>{priConf.label}</span>
            </button>
          </div>
          <button
            onClick={() => navigate(`/portal/${run.run_id || run.id}`)}
            className="bg-accent hover:bg-accent/90 transition-colors text-white text-xs font-bold px-4 py-2 rounded-lg flex items-center"
          >
            <ExternalLink className="w-3.5 h-3.5 mr-2" /> VIEW PORTAL
          </button>
        </header>

        {/* Run Summary card */}
        <section className="panel p-5 space-y-4">
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            <div>
              <div className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Duration</div>
              <div className="text-lg font-bold text-bright font-mono">{formatTime(elapsed)}</div>
            </div>
            <div>
              <div className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Artifacts</div>
              <div className="text-lg font-bold text-bright">{artifactCount}</div>
            </div>
            <div>
              <div className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Phase Pass Rate</div>
              <div className={`text-lg font-bold ${successRate >= 80 ? 'text-emerald-400' : successRate >= 50 ? 'text-warning' : 'text-danger'}`}>
                {successRate}%
              </div>
            </div>
            <div>
              <div className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Health Check</div>
              <button
                onClick={copyCurl}
                className="flex items-center space-x-1.5 text-xs font-mono text-accent hover:text-accent/80 transition-colors bg-accent/10 border border-accent/20 rounded px-2 py-1"
                title="Copy curl command"
              >
                <Terminal className="w-3 h-3 shrink-0" />
                <span>{curlCopied ? '✓ Copied!' : 'Copy curl'}</span>
              </button>
            </div>
          </div>

          {/* Controls row */}
          <div className="flex items-center space-x-2 pt-2 border-t border-border/50">
            {isRunning && (
              <>
                <button
                  onClick={handlePause}
                  disabled={!!controlLoading}
                  className="flex items-center space-x-1.5 px-3 py-1.5 bg-border/40 hover:bg-border/70 text-bright text-xs font-bold rounded-lg transition-colors disabled:opacity-50"
                >
                  {controlLoading === 'pause' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Pause className="w-3.5 h-3.5" />}
                  <span>Pause</span>
                </button>
                <button
                  onClick={handleCancel}
                  disabled={!!controlLoading}
                  className="flex items-center space-x-1.5 px-3 py-1.5 bg-danger/10 hover:bg-danger/20 text-danger text-xs font-bold rounded-lg transition-colors disabled:opacity-50"
                >
                  {controlLoading === 'cancel' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <X className="w-3.5 h-3.5" />}
                  <span>Cancel</span>
                </button>
              </>
            )}
            {isPaused && (
              <>
                <button
                  onClick={handleResume}
                  disabled={!!controlLoading}
                  className="flex items-center space-x-1.5 px-3 py-1.5 bg-accent/15 hover:bg-accent/25 text-accent text-xs font-bold rounded-lg transition-colors disabled:opacity-50"
                >
                  {controlLoading === 'resume' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                  <span>Resume</span>
                </button>
                <button
                  onClick={handleCancel}
                  disabled={!!controlLoading}
                  className="flex items-center space-x-1.5 px-3 py-1.5 bg-danger/10 hover:bg-danger/20 text-danger text-xs font-bold rounded-lg transition-colors disabled:opacity-50"
                >
                  {controlLoading === 'cancel' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <X className="w-3.5 h-3.5" />}
                  <span>Cancel</span>
                </button>
              </>
            )}
            {isDone && (
              <div className="relative" ref={rerunRef}>
                <button
                  onClick={() => setRerunOpen((v) => !v)}
                  className="flex items-center space-x-1.5 px-3 py-1.5 bg-border/40 hover:bg-border/70 text-bright text-xs font-bold rounded-lg transition-colors"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>Re-run from phase</span>
                  <ChevronDown className={`w-3.5 h-3.5 transition-transform ${rerunOpen ? 'rotate-180' : ''}`} />
                </button>
                {rerunOpen && (
                  <div className="absolute top-full left-0 mt-1 z-50 w-52 bg-panel border border-border rounded-xl shadow-2xl overflow-hidden">
                    {PHASES.map((p) => (
                      <button
                        key={p}
                        onClick={() => handleRerun(p)}
                        className="w-full flex items-center space-x-2 px-3 py-2 text-xs text-muted hover:bg-border/30 hover:text-bright transition-colors text-left"
                      >
                        <RotateCcw className="w-3 h-3 shrink-0" />
                        <span>{PHASE_NAMES[p]}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        {/* Currently running indicator */}
        {run.status === 'running' && (
          <section className="panel p-4 flex items-center space-x-3">
            <Loader2 className="w-4 h-4 text-accent animate-spin shrink-0" />
            <div>
              <span className="text-xs text-muted uppercase font-bold tracking-wider">Currently: </span>
              <span className="text-sm font-bold text-bright">{PHASE_NAMES[run.current_phase] || 'Initializing…'}</span>
            </div>
            <div className="flex-1 max-w-xs ml-auto">
              <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div className="h-full bg-accent transition-all duration-1000 ease-out" style={{ width: `${progressPercent}%` }} />
              </div>
            </div>
            <span className="text-sm font-bold text-accent shrink-0">{Math.round(progressPercent)}%</span>
          </section>
        )}

        {run.status === 'paused' && (
          <section className="panel p-4 flex items-center space-x-3 border-warning/20">
            <Pause className="w-4 h-4 text-warning shrink-0" />
            <span className="text-sm font-bold text-warning">Pipeline paused — will resume after current phase</span>
          </section>
        )}

        {/* Artifacts / Preview tabs */}
        <section>
          <div className="panel overflow-hidden">
            {/* Tab header */}
            <div className="bg-border/20 px-4 py-0 border-b border-border flex items-center justify-between">
              <div className="flex">
                {[
                  { id: 'artifacts', label: 'Artifacts', icon: FileCode },
                  { id: 'preview',   label: 'Preview',   icon: Monitor },
                ].map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveArtifactTab(tab.id)}
                    className={`flex items-center space-x-2 px-4 py-3 text-xs font-bold uppercase tracking-wider border-b-2 transition-all ${
                      activeArtifactTab === tab.id
                        ? 'border-accent text-accent'
                        : 'border-transparent text-muted hover:text-bright'
                    }`}
                  >
                    <tab.icon className="w-3.5 h-3.5" />
                    <span>{tab.label}</span>
                  </button>
                ))}
              </div>
              {activeArtifactTab === 'artifacts' && fileTree && (
                <span className="text-[10px] text-muted pr-2">{countFiles(fileTree)} files</span>
              )}
              {activeArtifactTab === 'preview' && previewHtml && (
                <div className="flex items-center space-x-2 pr-2">
                  <button
                    onClick={() => setViewMode('mobile')}
                    className={`p-1.5 rounded transition-colors ${viewMode === 'mobile' ? 'text-accent bg-accent/10' : 'text-muted hover:text-bright'}`}
                    title="Mobile view (390px)"
                  >
                    <Smartphone className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setViewMode('desktop')}
                    className={`p-1.5 rounded transition-colors ${viewMode === 'desktop' ? 'text-accent bg-accent/10' : 'text-muted hover:text-bright'}`}
                    title="Desktop view (100%)"
                  >
                    <Monitor className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={openPreviewTab}
                    className="p-1.5 rounded text-muted hover:text-bright transition-colors"
                    title="Open in new tab"
                  >
                    <OpenTab className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </div>

            {/* Artifacts tab content */}
            {activeArtifactTab === 'artifacts' && (
              <div className="flex h-[420px]">
                <div className="w-64 border-r border-border overflow-y-auto p-2 custom-scrollbar shrink-0">
                  {fileTree === null ? (
                    <div className="flex items-center justify-center h-full text-muted text-xs">
                      <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> Loading...
                    </div>
                  ) : fileTree.length === 0 ? (
                    <div className="flex items-center justify-center h-full text-muted text-xs italic">No artifacts yet.</div>
                  ) : (
                    <FileTree items={fileTree} onFileClick={handleFileClick} selectedPath={selectedFile?.path} />
                  )}
                </div>
                <div className="flex-1 overflow-hidden flex flex-col">
                  {!selectedFile ? (
                    <div className="flex items-center justify-center h-full text-muted text-sm italic">Select a file to preview.</div>
                  ) : fileLoading ? (
                    <div className="flex items-center justify-center h-full"><Loader2 className="w-6 h-6 text-accent animate-spin" /></div>
                  ) : fileContent?.error ? (
                    <div className="p-4 text-danger text-sm">{fileContent.error}</div>
                  ) : (
                    <>
                      <div className="bg-border/20 px-4 py-2 border-b border-border flex items-center justify-between shrink-0">
                        <span className="text-xs font-mono text-muted truncate">{selectedFile.path}</span>
                        <div className="flex items-center space-x-3 shrink-0 ml-4">
                          {fileContent?.truncated && <span className="text-[10px] text-warning">Truncated (50K)</span>}
                          <span className="text-[10px] text-muted">{formatBytes(fileContent?.size_bytes)}</span>
                        </div>
                      </div>
                      <div className="flex-1 overflow-auto bg-[#0a0c10]">
                        <pre className="p-4 font-mono text-[11px] text-bright/90 leading-relaxed whitespace-pre-wrap break-words">
                          {fileContent?.content || '(empty file)'}
                        </pre>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* Preview tab content */}
            {activeArtifactTab === 'preview' && (
              <div className="flex flex-col" style={{ height: '420px' }}>
                {previewLoading ? (
                  <div className="flex items-center justify-center h-full">
                    <Loader2 className="w-8 h-8 text-accent animate-spin" />
                  </div>
                ) : !previewHtml ? (
                  // Attempt to load if not yet loaded
                  fileTree === null ? (
                    <div className="flex items-center justify-center h-full text-muted text-sm">Loading file tree…</div>
                  ) : (
                    <div className="flex flex-col items-center justify-center h-full space-y-4 p-8 text-center">
                      <Monitor className="w-12 h-12 text-muted/40" />
                      <div>
                        <div className="text-bright font-bold mb-1">No frontend preview available.</div>
                        <div className="text-muted text-sm">The generated project is a backend API.</div>
                        <div className="text-muted text-sm">Use the Artifacts tab to view the generated code.</div>
                      </div>
                    </div>
                  )
                ) : (
                  <div className="flex-1 overflow-hidden flex flex-col bg-white">
                    {previewFile && (
                      <div className="bg-border/20 px-3 py-1.5 border-b border-border flex items-center justify-between shrink-0">
                        <span className="text-[10px] font-mono text-muted">{previewFile}</span>
                      </div>
                    )}
                    <div className="flex-1 flex items-start justify-center overflow-auto bg-[#0a0c10] p-4">
                      <iframe
                        srcDoc={previewHtml}
                        sandbox="allow-scripts allow-same-origin"
                        style={{
                          width: viewMode === 'mobile' ? '390px' : '100%',
                          height: '100%',
                          minHeight: '320px',
                          border: 'none',
                          borderRadius: '6px',
                          background: 'white',
                          flexShrink: 0,
                        }}
                        title="Project Preview"
                      />
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        {/* Agent Events Log */}
        <section>
          <div className="panel overflow-hidden flex flex-col h-[280px]">
            <div className="bg-border/20 px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
              <div className="flex items-center text-xs font-bold text-muted uppercase tracking-wider">
                <Terminal className="w-4 h-4 mr-2 text-accent" /> Agent Events
              </div>
              <span className="text-[10px] font-mono text-muted">{events.length} entries</span>
            </div>
            <div className="flex-1 overflow-y-auto p-4 font-mono text-[11px] space-y-1 custom-scrollbar bg-[#0a0c10]">
              {events.length > 0 ? (
                events.map((ev, i) => (
                  <div key={i} className="flex space-x-3 leading-relaxed">
                    <span className="text-muted shrink-0 w-20 text-[10px]">
                      {ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : '—'}
                    </span>
                    <span className="text-accent shrink-0 w-24 uppercase font-bold text-[10px] truncate">{ev.agent}</span>
                    <span className="text-bright/90 truncate">
                      {ev.action}
                      {ev.detail ? ` — ${typeof ev.detail === 'string' ? ev.detail.slice(0, 100) : JSON.stringify(ev.detail).slice(0, 100)}` : ''}
                    </span>
                  </div>
                ))
              ) : (
                <div className="h-full flex items-center justify-center text-muted italic">
                  No events recorded for this run.
                </div>
              )}
              <div ref={logEndRef} />
            </div>
          </div>
        </section>

      </div>
    </div>
  );
};

export default ProjectView;
