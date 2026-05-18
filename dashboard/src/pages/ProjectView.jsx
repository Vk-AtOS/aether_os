import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import Editor from '@monaco-editor/react';
import { useRole } from '../hooks/useRole';
import PhaseBadge from '../components/PhaseBadge';
import RerunDropdown from '../components/RerunDropdown';
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
  Smartphone,
  Monitor,
  ExternalLink as OpenTab,
  Radio,
  Download,
  GitBranch,
  Zap,
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

const PHASE_LABELS = {
  p01_intake_requirements: 'Intake & Requirements',
  p02_architecture:        'Architecture Design',
  p03_scaffolding:         'Project Scaffolding',
  p04_backend:             'Backend Codegen',
  p05_frontend:            'Frontend Codegen',
  p06_review_security:     'Code Review & Security',
  p07_testing:             'Testing Suite',
  p08_cicd_deployment:     'CI/CD & Deployment',
  p09_observability:       'Observability',
  p10_docs_delivery:       'Docs & Delivery',
};

const PRIORITY_CONFIG = {
  high:   { label: 'High',   color: 'text-red-400',   dot: 'bg-red-400'   },
  normal: { label: 'Normal', color: 'text-slate-400', dot: 'bg-slate-400' },
  low:    { label: 'Low',    color: 'text-blue-400',  dot: 'bg-blue-400'  },
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

const getMonacoLanguage = (filename) => {
  if (!filename) return 'plaintext';
  const ext = filename.split('.').pop()?.toLowerCase();
  const map = {
    py: 'python', js: 'javascript', jsx: 'javascript', ts: 'typescript',
    tsx: 'typescript', json: 'json', md: 'markdown', yml: 'yaml',
    yaml: 'yaml', html: 'html', css: 'css', sh: 'shell', txt: 'plaintext',
    toml: 'toml', env: 'plaintext', sql: 'sql', dockerfile: 'dockerfile',
  };
  return map[ext] || 'plaintext';
};

/** Format a pipeline SSE event into a terminal line string. */
const formatEvent = (event) => {
  switch (event.type) {
    case 'phase_start':
      return `\x1b[36m▶ [${event.phase}] ${PHASE_LABELS[event.phase] || event.phase}…\x1b[0m`;
    case 'phase_complete': {
      const dur   = event.duration ? ` in ${event.duration}s` : '';
      const icon  = event.status === 'passed'  ? '✓'
                  : event.status === 'timeout' ? '⏱'
                  : event.status === 'failed'  ? '✗'
                  : '✓';
      const color = event.status === 'passed'  ? '\x1b[32m'
                  : event.status === 'failed'  ? '\x1b[31m'
                  : '\x1b[33m';
      return `${color}${icon} [${event.phase}] ${event.status}${dur}\x1b[0m`;
    }
    case 'file_written': {
      const kb = event.size ? ` (${formatBytes(event.size)})` : '';
      return `\x1b[90m  → wrote ${event.path}${kb}\x1b[0m`;
    }
    case 'llm_chunk':
      return event.text || '';
    case 'pipeline_complete':
      return event.status === 'cancelled'
        ? '\x1b[33m✕ Pipeline cancelled\x1b[0m'
        : '\x1b[32m✓ Build complete\x1b[0m';
    case 'heartbeat':
    case 'no_stream':
      return null;
    default:
      return null;
  }
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
                : <Folder    className="w-3.5 h-3.5 text-accent shrink-0" />}
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

// ── Toast ────────────────────────────────────────────────────────────────────

const Toast = ({ message, onDone }) => {
  useEffect(() => {
    const t = setTimeout(onDone, 2500);
    return () => clearTimeout(t);
  }, [onDone]);
  return (
    <div className="fixed bottom-6 right-6 z-50 bg-panel border border-border rounded-xl px-5 py-3 shadow-2xl text-bright text-sm font-medium animate-fade-in">
      {message}
    </div>
  );
};

// ── TerminalLine — renders ANSI colour codes ────────────────────────────────

const ANSI_MAP = {
  '\x1b[32m': 'text-emerald-400',
  '\x1b[31m': 'text-red-400',
  '\x1b[33m': 'text-yellow-400',
  '\x1b[36m': 'text-indigo-400',
  '\x1b[90m': 'text-slate-500',
  '\x1b[0m':  '',
};

const TerminalLine = ({ text }) => {
  // Split on ANSI codes and render each segment with correct colour class
  const parts = [];
  let currentClass = 'text-emerald-300';
  let remaining = text;
  const re = /(\x1b\[[0-9;]*m)/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      parts.push({ text: text.slice(last, m.index), cls: currentClass });
    }
    currentClass = ANSI_MAP[m[0]] || '';
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), cls: currentClass });
  if (parts.length === 0) parts.push({ text, cls: currentClass });

  return (
    <div className="leading-relaxed whitespace-pre-wrap break-all">
      {parts.map((p, i) => (
        <span key={i} className={p.cls || 'text-emerald-300/70'}>{p.text}</span>
      ))}
    </div>
  );
};

// ── Main component ───────────────────────────────────────────────────────────

const ProjectView = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const { isViewer } = useRole();

  const [run, setRun]                   = useState(null);
  const [elapsed, setElapsed]           = useState(0);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState(null);
  const [fileTree, setFileTree]         = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent]   = useState(null);
  const [fileLoading, setFileLoading]   = useState(false);
  const [curlCopied, setCurlCopied]     = useState(false);
  const [toast, setToast]               = useState(null);

  // Controls
  const [controlLoading, setControlLoading] = useState(null);
  const [priority, setPriority]             = useState('normal');

  // Deployment
  const [deploying, setDeploying] = useState(false);

  // Artifact / Preview / Live tabs
  const [activeArtifactTab, setActiveArtifactTab] = useState('artifacts');
  const [viewMode, setViewMode]                   = useState('desktop');
  const [previewMode, setPreviewMode]             = useState('static'); // 'live' | 'static'
  const [previewHtml, setPreviewHtml]             = useState(null);
  const [previewLoading, setPreviewLoading]       = useState(false);
  const [previewFile, setPreviewFile]             = useState(null);

  // Live feed
  const [feedLines, setFeedLines]   = useState([]);
  const [feedDone, setFeedDone]     = useState(false);
  const feedEndRef                  = useRef(null);
  const esRef                       = useRef(null);   // EventSource ref
  const llmLineRef                  = useRef('');     // accumulate llm_chunk tokens
  const reconnectAttempts           = useRef(0);

  // Edit mode for file viewer
  const [editContent, setEditContent]   = useState(null);  // null = view mode
  const [editSaving, setEditSaving]     = useState(false);

  // Env vars tab
  const [envVars, setEnvVars]       = useState(null);
  const [envSaving, setEnvSaving]   = useState(false);
  const [appRunning, setAppRunning] = useState(false);
  const [appOutput, setAppOutput]   = useState([]);

  // Re-run dropdown (managed inside RerunDropdown component)

  const logEndRef = useRef(null);

  // ── Data fetching ──────────────────────────────────────────────────────────

  const fetchRunDetail = useCallback(async () => {
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
  }, [id]);

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
    if (!indexFile) { setPreviewHtml(null); setPreviewFile(null); return; }
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

  useEffect(() => {
    if (activeArtifactTab === 'env' && envVars === null) {
      api.getEnvVars(id).then(r => setEnvVars(r.data?.vars || [])).catch(() => setEnvVars([]));
    }
  }, [activeArtifactTab, envVars, id]);

  // ── SSE live feed ─────────────────────────────────────────────────────────

  const appendLine = useCallback((line) => {
    if (!line) return;
    setFeedLines((prev) => [...prev.slice(-300), line]);
  }, []);

  useEffect(() => {
    // Only open SSE when run is running and no active connection already
    if (!run || run.status !== 'running') return;
    if (esRef.current) return; // already connected

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
        // Exchange the bearer token for a short-lived SSE-only token.
        // This keeps the full JWT out of the URL (server logs, browser history, Referer headers).
        const exchRes = await fetch(`/api/factory/runs/${id}/sse-token`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${api.getToken()}`,
            'Content-Type': 'application/json',
          },
        });
        if (!exchRes.ok || cancelled) { if (!exchRes.ok) scheduleReconnect(); return; }
        const { sse_token } = await exchRes.json();
        if (cancelled) return;

        const url = `/api/factory/runs/${id}/stream?sse_token=${encodeURIComponent(sse_token)}`;
        const es = new EventSource(url);
        esRef.current = es;

        es.onmessage = (e) => {
          let event;
          try { event = JSON.parse(e.data); } catch { return; }

          if (event.type === 'llm_chunk') {
            // Accumulate tokens until we see a newline, then flush as one line
            llmLineRef.current += event.text || '';
            const nl = llmLineRef.current.lastIndexOf('\n');
            if (nl !== -1) {
              const flushed = llmLineRef.current.slice(0, nl);
              llmLineRef.current = llmLineRef.current.slice(nl + 1);
              flushed.split('\n').forEach((l) => appendLine(l));
            }
          } else {
            // Flush any pending LLM line before a structural event
            if (llmLineRef.current) {
              appendLine(llmLineRef.current);
              llmLineRef.current = '';
            }
            const line = formatEvent(event);
            if (line) appendLine(line);
          }

          if (event.type === 'pipeline_complete') {
            // Flush remainder
            if (llmLineRef.current) {
              appendLine(llmLineRef.current);
              llmLineRef.current = '';
            }
            done = true;
            setFeedDone(true);
            es.close();
            esRef.current = null;
            fetchRunDetail();
            fetchFileTree();
          }
        };

        es.onerror = () => {
          es.close();
          esRef.current = null;
          scheduleReconnect();
        };
      } catch (err) {
        console.error('SSE connect failed:', err);
        scheduleReconnect();
      }
    };

    reconnectAttempts.current = 0;
    connectSSE();

    return () => {
      cancelled = true;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [run?.status, id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Switch to LIVE tab automatically when run starts
  useEffect(() => {
    if (run?.status === 'running' && activeArtifactTab !== 'live') {
      setActiveArtifactTab('live');
    }
  }, [run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // When live_url appears, default preview mode to 'live'
  useEffect(() => {
    if (run?.live_url) setPreviewMode('live');
  }, [run?.live_url]);

  // Auto-scroll live feed
  useEffect(() => {
    if (activeArtifactTab === 'live') {
      feedEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [feedLines, activeArtifactTab]);

  // ── Controls ───────────────────────────────────────────────────────────────

  const showToast = (msg) => setToast(msg);

  const handlePause = async () => {
    setControlLoading('pause');
    try {
      await api.pauseRun(id);
      setRun((prev) => prev ? { ...prev, status: 'paused' } : prev);
      showToast('⏸ Pipeline paused');
      setTimeout(fetchRunDetail, 2000);
    } catch (e) {
      showToast('Failed to pause: ' + (e.message || 'error'));
    } finally {
      setControlLoading(null);
    }
  };

  const handleResume = async () => {
    setControlLoading('resume');
    try {
      await api.resumeRun(id);
      setRun((prev) => prev ? { ...prev, status: 'running' } : prev);
      showToast('▶ Pipeline resumed');
      setTimeout(fetchRunDetail, 2000);
    } catch (e) {
      showToast('Failed to resume: ' + (e.message || 'error'));
    } finally {
      setControlLoading(null);
    }
  };

  const handleCancel = async () => {
    if (!window.confirm('Cancel this run? This cannot be undone.')) return;
    setControlLoading('cancel');
    try {
      await api.cancelRun(id);
      setRun((prev) => prev ? { ...prev, status: 'cancelled' } : prev);
      showToast('✕ Pipeline cancelled');
      setTimeout(fetchRunDetail, 2000);
    } catch (e) {
      showToast('Failed to cancel: ' + (e.message || 'error'));
    } finally {
      setControlLoading(null);
    }
  };

  const handlePriorityCycle = async () => {
    const next = PRIORITY_CYCLE[(PRIORITY_CYCLE.indexOf(priority) + 1) % PRIORITY_CYCLE.length];
    setPriority(next);
    try { await api.setRunPriority(id, next); } catch { setPriority(priority); }
  };

  const handleRerun = async (fromPhase) => {
    try {
      const res = await api.rerunFromPhase(id, fromPhase);
      navigate(`/project/${res.data.run_id}`);
    } catch (e) {
      showToast('Failed to start rerun: ' + (e.message || 'unknown error'));
    }
  };

  const handleEditRestart = async (editedReq) => {
    try {
      const res = await api.startPipeline({
        raw_input: editedReq,
        project_name: run?.project_name,
        domain: run?.domain || 'general',
        client_id: run?.client_id || 'client-001',
      });
      navigate(`/project/${res.data.run_id}`);
    } catch (e) {
      showToast('Failed to start run: ' + (e.message || 'unknown error'));
    }
  };

  const handleDeploy = async () => {
    setDeploying(true);
    try {
      const res = await api.deployRun(id);
      if (res.data?.live_url) {
        setRun((prev) => prev ? { ...prev, live_url: res.data.live_url } : prev);
        setPreviewMode('live');
        showToast('🚀 App is live at ' + res.data.live_url);
      } else {
        showToast('Deploy failed: ' + (res.data?.error || 'unknown error'));
      }
    } catch (e) {
      showToast('Deploy error: ' + (e.message || 'unknown'));
    } finally {
      setDeploying(false);
    }
  };

  const handleStopDeploy = async () => {
    try {
      await api.stopDeploy(id);
      setRun((prev) => prev ? { ...prev, live_url: null } : prev);
      setPreviewMode('static');
      showToast('Container stopped');
    } catch (e) {
      showToast('Stop failed: ' + (e.message || 'unknown'));
    }
  };

  const handleDownload = async () => {
    try {
      const res = await api.downloadRunZip(id);
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/zip' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${run?.project_name || id}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      showToast('Download failed: ' + (e.message || 'unknown'));
    }
  };

  const [showGitHubModal, setShowGitHubModal] = useState(false);
  const [showAddFeatureModal, setShowAddFeatureModal] = useState(false);
  const [gitHubToken, setGitHubToken] = useState('');
  const [gitHubRepoName, setGitHubRepoName] = useState('');
  const [gitHubPushing, setGitHubPushing] = useState(false);
  const [addFeatureText, setAddFeatureText] = useState('');
  const [addingFeature, setAddingFeature] = useState(false);

  const handlePushGitHub = async () => {
    if (!gitHubToken || !gitHubRepoName) return showToast('GitHub token and repo name required');
    setGitHubPushing(true);
    try {
      const res = await api.pushToGitHub(id, { github_token: gitHubToken, repo_name: gitHubRepoName });
      showToast('✅ Pushed to GitHub: ' + (res.data?.html_url || gitHubRepoName));
      setShowGitHubModal(false);
    } catch (e) {
      showToast('Push failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setGitHubPushing(false);
    }
  };

  const handleAddFeature = async () => {
    if (!addFeatureText.trim()) return showToast('Describe the feature to add');
    setAddingFeature(true);
    const branchPhase = window._branchPhase || 'p04_backend';
    delete window._branchPhase;
    try {
      const res = await api.branchRun(id, branchPhase, addFeatureText.trim());
      showToast('🚀 Branch run started');
      setShowAddFeatureModal(false);
      navigate(`/project/${res.data?.run_id}`);
    } catch (e) {
      showToast('Failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setAddingFeature(false);
    }
  };

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
    // For finished runs show the actual duration; for active runs count up live
    const isDone = ['completed', 'failed', 'cancelled', 'interrupted'].includes(run.status);
    if (isDone && run.finished_at) {
      setElapsed(Math.floor((run.finished_at - run.started_at) / 1000));
      return;
    }
    const tick = () => setElapsed(Math.floor((Date.now() - run.started_at) / 1000));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [run?.started_at, run?.finished_at, run?.status]);

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

  const completedPhases  = PHASES.filter((p) =>
    ['passed', 'completed', 'timeout'].includes(getPhaseStatus(p))
  ).length;
  const progressPercent  = (completedPhases / PHASES.length) * 100;

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

  const events       = run.events || [];
  const phases       = run.phases || {};
  const passedCount  = PHASES.filter((p) => ['passed', 'completed'].includes(getPhaseStatus(p))).length;
  const successRate  = completedPhases > 0 ? Math.round((passedCount / completedPhases) * 100) : 0;
  const artifactCount = fileTree ? countFiles(fileTree) : 0;

  // Security findings count from p06 output
  const secFindings = (() => {
    const p06 = phases?.p06_review_security?.output;
    if (!p06) return null;
    // security_total is injected by the API from security_report.json
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

  const curlCmd = `curl -s http://localhost:8000/health`;
  const copyCurl = () => {
    navigator.clipboard.writeText(curlCmd);
    setCurlCopied(true);
    setTimeout(() => setCurlCopied(false), 2000);
  };

  const runStatus = run.status;
  const isRunning = runStatus === 'running';
  const isPaused  = runStatus === 'paused';
  const isDone    = ['completed', 'failed', 'cancelled', 'interrupted'].includes(runStatus);
  const priConf   = PRIORITY_CONFIG[priority] || PRIORITY_CONFIG.normal;

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

      {/* Toast notification */}
      {toast && <Toast message={toast} onDone={() => setToast(null)} />}

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
            const st      = getPhaseStatus(p);
            const pData   = phases[p] || {};
            const dur     = pData.duration_s != null
              ? pData.duration_s < 60 ? `${pData.duration_s}s` : `${Math.round(pData.duration_s / 60)}m`
              : null;
            const isActive = st === 'running' || run.current_phase === p;
            const isDone2  = st === 'passed' || st === 'completed' || st === 'timeout';
            const isFailed = st === 'failed';

            return (
              <div key={p} className="relative group/phase">
                <button
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
                {(isDone2 || isFailed) && (
                  <button
                    onClick={() => {
                      setShowAddFeatureModal(true);
                      setAddFeatureText('');
                      // Store branch phase for the modal
                      window._branchPhase = p;
                    }}
                    className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover/phase:opacity-100 p-1 rounded hover:bg-accent/20 text-muted hover:text-accent transition-all"
                    title={`Branch from ${PHASE_NAMES[p]}`}
                  >
                    <GitBranch className="w-3 h-3" />
                  </button>
                )}
              </div>
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

            {/* Priority badge — interactive for non-viewers */}
            {isViewer ? (
              <span className={`flex items-center space-x-1.5 text-xs font-bold px-2.5 py-1 rounded-full border border-border/50 ${priConf.color}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${priConf.dot}`} />
                <span>{priConf.label}</span>
              </span>
            ) : (
              <button
                onClick={handlePriorityCycle}
                className={`flex items-center space-x-1.5 text-xs font-bold px-2.5 py-1 rounded-full border border-border/50 hover:bg-border/30 transition-colors ${priConf.color}`}
                title="Click to change priority"
              >
                <span className={`w-1.5 h-1.5 rounded-full ${priConf.dot}`} />
                <span>{priConf.label}</span>
              </button>
            )}
          </div>

          {/* Security grade badge */}
          {secGrade && (
            <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-bold ${secGrade.color}`} title={`Security grade: ${secFindings} findings`}>
              <span>🔒</span><span>{secGrade.grade}</span>
            </div>
          )}

          <div className="flex items-center space-x-2">
            {/* Live App — shown when container is running */}
            {run.live_url ? (
              <>
                <a
                  href={run.live_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center space-x-2 px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-black font-bold rounded-lg transition-colors text-xs animate-pulse"
                >
                  <span>🚀</span>
                  <span>LAUNCH APP</span>
                  {/* Guard: live_url may be a bare hostname without a port */}
                  <span className="opacity-70">:{run.live_url?.split(':').pop() ?? ''}</span>
                </a>
                <button
                  onClick={handleStopDeploy}
                  className="px-3 py-2 bg-red-900/60 hover:bg-red-800 text-red-300 rounded-lg text-xs font-medium transition-colors"
                  title="Stop container"
                >
                  Stop
                </button>
              </>
            ) : run.status === 'completed' ? (
              <button
                onClick={handleDeploy}
                disabled={deploying}
                className="flex items-center space-x-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-bold rounded-lg transition-colors disabled:opacity-50 text-xs"
              >
                <span>{deploying ? '⏳' : '🐳'}</span>
                <span>{deploying ? 'Building…' : 'Deploy to localhost'}</span>
              </button>
            ) : null}

            <button
              onClick={() => navigate(`/portal/${run.run_id || run.id}`)}
              className="bg-accent hover:bg-accent/90 transition-colors text-white text-xs font-bold px-4 py-2 rounded-lg flex items-center"
            >
              <ExternalLink className="w-3.5 h-3.5 mr-2" /> VIEW PORTAL
            </button>
            <button
              onClick={handleDownload}
              className="flex items-center space-x-1.5 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-xs font-medium transition-colors"
              title="Download project as ZIP"
            >
              <Download className="w-3.5 h-3.5" /><span>ZIP</span>
            </button>
            <button
              onClick={() => setShowGitHubModal(true)}
              className="flex items-center space-x-1.5 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-xs font-medium transition-colors"
              title="Push to GitHub"
            >
              <GitBranch className="w-3.5 h-3.5" /><span>GitHub</span>
            </button>
            <button
              onClick={async () => {
                try {
                  await api.openInVSCode(id);
                  setToast('Opening in VS Code…');
                } catch {
                  setToast('VS Code CLI not found. Check that "code" is in your PATH.');
                }
              }}
              className="flex items-center space-x-1.5 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-xs font-medium transition-colors"
              title="Open project folder in VS Code"
            >
              <FileCode className="w-3.5 h-3.5" /><span>VS Code</span>
            </button>
            {(run.status === 'completed' || run.status === 'running') && (
              <button
                onClick={() => setShowAddFeatureModal(true)}
                className="flex items-center space-x-1.5 px-3 py-2 bg-indigo-700 hover:bg-indigo-600 text-white rounded-lg text-xs font-medium transition-colors"
                title="Add a feature to this project"
              >
                <Zap className="w-3.5 h-3.5" /><span>Add Feature</span>
              </button>
            )}
          </div>
        </header>

        {/* GitHub Push Modal */}
        {showGitHubModal && (
          <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
            <div className="bg-panel border border-border rounded-xl p-6 w-96 space-y-4">
              <h3 className="text-base font-bold text-bright">Push to GitHub</h3>
              <div>
                <label className="block text-xs text-muted mb-1">GitHub Personal Access Token</label>
                <input type="password" value={gitHubToken} onChange={e => setGitHubToken(e.target.value)}
                  placeholder="ghp_..." className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">New Repo Name</label>
                <input type="text" value={gitHubRepoName} onChange={e => setGitHubRepoName(e.target.value)}
                  placeholder="my-aetheros-app" className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent" />
              </div>
              <div className="flex space-x-3 pt-1">
                <button onClick={() => setShowGitHubModal(false)} className="flex-1 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-bright transition-colors">Cancel</button>
                <button onClick={handlePushGitHub} disabled={gitHubPushing} className="flex-1 py-2 bg-accent hover:bg-accent/90 rounded-lg text-sm text-white font-bold transition-colors disabled:opacity-50">
                  {gitHubPushing ? 'Pushing…' : 'Push'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Add Feature Modal */}
        {showAddFeatureModal && (
          <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
            <div className="bg-panel border border-border rounded-xl p-6 w-[480px] space-y-4">
              <h3 className="text-base font-bold text-bright">Add a Feature</h3>
              <p className="text-xs text-muted">Describe the feature to add. A new run will branch from p04_backend with your existing architecture.</p>
              <textarea
                value={addFeatureText} onChange={e => setAddFeatureText(e.target.value)}
                rows={4} placeholder="Add Stripe payments with webhook support..."
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent resize-none"
              />
              <div className="flex space-x-3">
                <button onClick={() => setShowAddFeatureModal(false)} className="flex-1 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-bright transition-colors">Cancel</button>
                <button onClick={handleAddFeature} disabled={addingFeature} className="flex-1 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm text-white font-bold transition-colors disabled:opacity-50">
                  {addingFeature ? 'Starting…' : 'Add Feature'}
                </button>
              </div>
            </div>
          </div>
        )}

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
              <div className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Security</div>
              {secFindings === null ? (
                <div className="text-lg font-bold text-muted">—</div>
              ) : secFindings === 0 ? (
                <div className="text-lg font-bold text-emerald-400">✓ Clean</div>
              ) : (
                <div className={`text-lg font-bold ${secFindings >= 5 ? 'text-danger' : 'text-warning'}`}>
                  {secFindings} finding{secFindings !== 1 ? 's' : ''}
                </div>
              )}
            </div>
          </div>

          {/* Controls row — large prominent buttons */}
          {!isViewer && (isRunning || isPaused || isDone) && (
            <div className="flex flex-wrap items-center gap-3 pt-3 border-t border-border/50">
              {isRunning && (
                <>
                  <button
                    onClick={handlePause}
                    disabled={!!controlLoading}
                    className="flex items-center space-x-2 px-4 py-2 bg-yellow-500 hover:bg-yellow-400 text-black font-bold rounded-lg transition-colors disabled:opacity-50 text-sm"
                  >
                    {controlLoading === 'pause'
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : <Pause className="w-4 h-4" />}
                    <span>Pause</span>
                  </button>
                  <button
                    onClick={handleCancel}
                    disabled={!!controlLoading}
                    className="flex items-center space-x-2 px-4 py-2 bg-red-600 hover:bg-red-500 text-white font-bold rounded-lg transition-colors disabled:opacity-50 text-sm"
                  >
                    {controlLoading === 'cancel'
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : <X className="w-4 h-4" />}
                    <span>Cancel</span>
                  </button>
                </>
              )}
              {isPaused && (
                <>
                  <button
                    onClick={handleResume}
                    disabled={!!controlLoading}
                    className="flex items-center space-x-2 px-4 py-2 bg-green-600 hover:bg-green-500 text-white font-bold rounded-lg transition-colors disabled:opacity-50 text-sm"
                  >
                    {controlLoading === 'resume'
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : <Play className="w-4 h-4" />}
                    <span>Resume</span>
                  </button>
                  <button
                    onClick={handleCancel}
                    disabled={!!controlLoading}
                    className="flex items-center space-x-2 px-4 py-2 bg-red-600 hover:bg-red-500 text-white font-bold rounded-lg transition-colors disabled:opacity-50 text-sm"
                  >
                    {controlLoading === 'cancel'
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : <X className="w-4 h-4" />}
                    <span>Cancel</span>
                  </button>
                </>
              )}
              {isDone && (
                <RerunDropdown
                  status={runStatus}
                  rawInput={run.raw_input || run.requirement || ''}
                  variant="button"
                  onContinue={handleResume}
                  onRerunPhase={handleRerun}
                  onFullRestart={() => handleRerun('p01_intake_requirements')}
                  onEditRestart={handleEditRestart}
                />
              )}
            </div>
          )}
        </section>

        {/* Currently running indicator */}
        {isRunning && (
          <section className="panel p-4 flex items-center space-x-3">
            <Loader2 className="w-4 h-4 text-accent animate-spin shrink-0" />
            <div>
              <span className="text-xs text-muted uppercase font-bold tracking-wider">Currently: </span>
              <span className="text-sm font-bold text-bright">
                {PHASE_NAMES[run.current_phase] ||
                  (run.current_phase
                    ? run.current_phase.replace(/^p\d+[a-z]?_/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
                    : 'Initializing…')}
              </span>
            </div>
            <div className="flex-1 max-w-xs ml-auto">
              <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div className="h-full bg-accent transition-all duration-1000 ease-out" style={{ width: `${progressPercent}%` }} />
              </div>
            </div>
            <span className="text-sm font-bold text-accent shrink-0">{Math.round(progressPercent)}%</span>
          </section>
        )}

        {isPaused && (
          <section className="panel p-4 flex items-center space-x-3 border-warning/20">
            <Pause className="w-4 h-4 text-warning shrink-0" />
            <span className="text-sm font-bold text-warning">Pipeline paused — click Resume to continue</span>
          </section>
        )}

        {/* ── Artifacts / Preview / Live tabs ───────────────────────────────── */}
        <section>
          <div className="panel overflow-hidden">
            {/* Tab header */}
            <div className="bg-border/20 px-4 py-0 border-b border-border flex items-center justify-between">
              <div className="flex">
                {[
                  { id: 'live',      label: 'Live',      icon: Radio,    showDot: isRunning },
                  { id: 'artifacts', label: 'Artifacts', icon: FileCode  },
                  { id: 'preview',   label: 'Preview',   icon: Monitor   },
                  ...(run?.live_url ? [{ id: 'iframe', label: 'App Preview', icon: OpenTab }] : []),
                  { id: 'env',       label: 'Env Vars',  icon: Zap       },
                  { id: 'run',       label: 'Run App',   icon: Play      },
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
                    <tab.icon className={`w-3.5 h-3.5 ${tab.showDot ? 'text-emerald-400 animate-pulse' : ''}`} />
                    <span>{tab.label}</span>
                    {tab.showDot && (
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    )}
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
                  >
                    <Smartphone className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setViewMode('desktop')}
                    className={`p-1.5 rounded transition-colors ${viewMode === 'desktop' ? 'text-accent bg-accent/10' : 'text-muted hover:text-bright'}`}
                  >
                    <Monitor className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={openPreviewTab} className="p-1.5 rounded text-muted hover:text-bright transition-colors">
                    <OpenTab className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </div>

            {/* ── LIVE tab ──────────────────────────────────────────────────── */}
            {activeArtifactTab === 'live' && (
              <div className="flex flex-col" style={{ height: '420px', background: '#0a0a0f' }}>
                {/* Header bar */}
                <div className="flex items-center justify-between px-4 py-2 border-b border-white/5 shrink-0">
                  <div className="flex items-center space-x-2">
                    {isRunning
                      ? <><span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" /><span className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest">LIVE</span></>
                      : <><span className="w-2 h-2 rounded-full bg-slate-600" /><span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">{feedDone ? 'COMPLETE' : 'IDLE'}</span></>
                    }
                    <span className="text-[10px] text-slate-600 ml-2">
                      {isRunning ? 'AetherOS is building your project…' : feedDone ? 'Build finished.' : 'Waiting for pipeline…'}
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-700">{feedLines.length} lines</span>
                </div>

                {/* Terminal body */}
                <div className="flex-1 overflow-y-auto p-4 font-mono text-[11px] space-y-0.5 custom-scrollbar">
                  {feedLines.length === 0 && (
                    <div className="text-slate-600 italic">
                      {isRunning ? 'Connecting to pipeline stream…' : 'No events yet. Start a run to see live output.'}
                    </div>
                  )}
                  {feedLines.map((line, i) => (
                    <TerminalLine key={i} text={line} />
                  ))}
                  {/* Blinking cursor */}
                  {isRunning && (
                    <div className="flex items-center">
                      <span className="text-emerald-400 animate-pulse">█</span>
                    </div>
                  )}
                  {feedDone && (
                    <div className="mt-3 text-emerald-400 font-bold">✓ Build complete</div>
                  )}
                  <div ref={feedEndRef} />
                </div>
              </div>
            )}

            {/* ── Artifacts tab ─────────────────────────────────────────────── */}
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
                          {!isViewer && editContent === null ? (
                            <button
                              onClick={() => setEditContent(fileContent?.content || '')}
                              className="text-[10px] px-2 py-0.5 bg-indigo-700 hover:bg-indigo-600 text-white rounded transition-colors"
                            >Edit</button>
                          ) : editContent !== null ? (
                            <div className="flex items-center space-x-2">
                              <button
                                onClick={() => setEditContent(null)}
                                className="text-[10px] px-2 py-0.5 bg-slate-700 hover:bg-slate-600 text-white rounded transition-colors"
                              >Cancel</button>
                              <button
                                disabled={editSaving}
                                onClick={async () => {
                                  setEditSaving(true);
                                  try {
                                    await api.patchFileContent(id, selectedFile.path, editContent);
                                    setFileContent(prev => ({ ...prev, content: editContent }));
                                    setEditContent(null);
                                    setToast('File saved.');
                                  } catch {
                                    setToast('Save failed.');
                                  } finally {
                                    setEditSaving(false);
                                  }
                                }}
                                className="text-[10px] px-2 py-0.5 bg-emerald-700 hover:bg-emerald-600 text-white rounded transition-colors disabled:opacity-50"
                              >{editSaving ? 'Saving…' : 'Save'}</button>
                            </div>
                          ) : null}
                        </div>
                      </div>
                      <div className="flex-1 overflow-hidden" style={{ minHeight: 0 }}>
                        <Editor
                          height="100%"
                          defaultLanguage={getMonacoLanguage(selectedFile?.name)}
                          value={editContent !== null ? editContent : (fileContent?.content || '')}
                          onChange={editContent !== null ? (v) => setEditContent(v || '') : undefined}
                          options={{
                            readOnly: editContent === null,
                            minimap: { enabled: false },
                            fontSize: 11,
                            lineNumbers: 'on',
                            scrollBeyondLastLine: false,
                            wordWrap: 'on',
                            theme: 'vs-dark',
                            padding: { top: 8 },
                          }}
                          theme="vs-dark"
                        />
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* ── Preview tab ───────────────────────────────────────────────── */}
            {activeArtifactTab === 'preview' && (
              <div className="flex flex-col" style={{ height: '480px' }}>
                {/* Mode toggle bar */}
                <div className="flex items-center space-x-2 px-4 py-2.5 border-b border-border bg-border/10 shrink-0">
                  {run.live_url && (
                    <button
                      onClick={() => setPreviewMode('live')}
                      className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${
                        previewMode === 'live'
                          ? 'bg-emerald-500 text-black'
                          : 'bg-white/5 text-muted hover:text-bright'
                      }`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${previewMode === 'live' ? 'bg-black' : 'bg-emerald-400'} animate-pulse`} />
                      <span>Live App</span>
                    </button>
                  )}
                  <button
                    onClick={() => setPreviewMode('static')}
                    className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${
                      previewMode === 'static'
                        ? 'bg-indigo-500 text-white'
                        : 'bg-white/5 text-muted hover:text-bright'
                    }`}
                  >
                    <span>📄</span>
                    <span>Generated UI</span>
                  </button>
                </div>

                {/* ── Live App iframe ── */}
                {previewMode === 'live' && run.live_url && (
                  <div className="flex-1 flex flex-col overflow-hidden">
                    <div className="bg-black/30 px-3 py-1.5 border-b border-border flex items-center justify-between shrink-0">
                      <span className="text-[10px] font-mono text-emerald-400">{run.live_url}</span>
                      <a
                        href={run.live_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[10px] text-muted hover:text-bright transition-colors"
                      >
                        Open tab ↗
                      </a>
                    </div>
                    <iframe
                      src={run.live_url}
                      className="flex-1 w-full border-none bg-white"
                      title="Live Application"
                      style={{ minHeight: '360px' }}
                    />
                  </div>
                )}

                {/* ── Static / Generated UI ── */}
                {previewMode === 'static' && (
                  previewLoading ? (
                    <div className="flex items-center justify-center flex-1">
                      <Loader2 className="w-8 h-8 text-accent animate-spin" />
                    </div>
                  ) : !previewHtml ? (
                    fileTree === null ? (
                      <div className="flex items-center justify-center flex-1 text-muted text-sm">Loading file tree…</div>
                    ) : (
                      <div className="flex flex-col items-center justify-center flex-1 space-y-4 p-8 text-center">
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
                  )
                )}
              </div>
            )}
          {/* ── App Preview (iframe of live_url) ──────────────────────────── */}
          {activeArtifactTab === 'iframe' && run?.live_url && (
            <div className="flex flex-col" style={{ height: '480px' }}>
              <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-border/10 shrink-0">
                <span className="text-[10px] font-mono text-muted truncate">{run.live_url}</span>
                <a href={run.live_url} target="_blank" rel="noopener noreferrer"
                  className="flex items-center gap-1 text-[10px] text-accent hover:underline shrink-0 ml-2">
                  <OpenTab className="w-3 h-3" /> Open in tab
                </a>
              </div>
              <iframe
                src={run.live_url}
                className="flex-1 w-full border-0 bg-white"
                title="Live App Preview"
                sandbox="allow-scripts allow-same-origin allow-forms"
              />
            </div>
          )}

          {/* ── Env Vars tab ─────────────────────────────────────────────── */}
          {activeArtifactTab === 'env' && (
            <div className="p-4 space-y-3 h-[420px] overflow-y-auto custom-scrollbar">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-muted uppercase tracking-wider">Environment Variables</span>
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => setEnvVars(prev => [...(prev || []), { key: '', value: '' }])}
                    className="text-[10px] px-2 py-1 bg-indigo-700 hover:bg-indigo-600 text-white rounded"
                  >+ Add</button>
                  <button
                    disabled={envSaving}
                    onClick={async () => {
                      setEnvSaving(true);
                      try {
                        await api.patchEnvVars(id, envVars.filter(v => v.key.trim()));
                        setToast('Environment saved.');
                      } catch { setToast('Save failed.'); }
                      finally { setEnvSaving(false); }
                    }}
                    className="text-[10px] px-2 py-1 bg-emerald-700 hover:bg-emerald-600 text-white rounded disabled:opacity-50"
                  >{envSaving ? 'Saving…' : 'Save .env'}</button>
                </div>
              </div>
              {envVars === null ? (
                <div className="flex items-center justify-center h-32"><Loader2 className="w-5 h-5 text-accent animate-spin" /></div>
              ) : envVars.length === 0 ? (
                <div className="text-muted text-xs italic text-center py-8">No .env file found. Add variables above.</div>
              ) : (
                envVars.map((v, i) => (
                  <div key={i} className="flex items-center space-x-2">
                    <input
                      value={v.key}
                      onChange={e => setEnvVars(prev => prev.map((x, j) => j === i ? { ...x, key: e.target.value } : x))}
                      placeholder="KEY"
                      className="w-40 bg-bg border border-border rounded px-2 py-1 text-xs font-mono text-bright focus:outline-none focus:border-accent"
                    />
                    <span className="text-muted text-xs">=</span>
                    <input
                      value={v.value}
                      onChange={e => setEnvVars(prev => prev.map((x, j) => j === i ? { ...x, value: e.target.value } : x))}
                      placeholder="value"
                      className="flex-1 bg-bg border border-border rounded px-2 py-1 text-xs font-mono text-bright focus:outline-none focus:border-accent"
                    />
                    <button
                      onClick={() => setEnvVars(prev => prev.filter((_, j) => j !== i))}
                      className="text-danger hover:text-red-400 text-xs px-1"
                    >✕</button>
                  </div>
                ))
              )}
            </div>
          )}

          {/* ── Run App tab ───────────────────────────────────────────────── */}
          {activeArtifactTab === 'run' && (
            <div className="flex flex-col h-[420px]">
              <div className="flex items-center space-x-3 px-4 py-2.5 border-b border-border bg-border/10 shrink-0">
                <span className="text-xs font-bold text-muted uppercase tracking-wider">App Runner</span>
                <div className="flex items-center space-x-2 ml-auto">
                  {!appRunning ? (
                    <button
                      onClick={async () => {
                        try {
                          await api.startRunApp(id);
                          setAppRunning(true);
                          setAppOutput(['[AetherOS] Starting app on port 8001…', '[AetherOS] Open http://localhost:8001 to view it.']);
                          setToast('App starting on port 8001…');
                        } catch (e) {
                          setToast('Failed to start app: ' + (e.response?.data?.detail || e.message));
                        }
                      }}
                      className="flex items-center space-x-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition-colors"
                    >
                      <Play className="w-3.5 h-3.5" /><span>Run App</span>
                    </button>
                  ) : (
                    <button
                      onClick={async () => {
                        try {
                          await api.stopRunApp(id);
                          setAppRunning(false);
                          setAppOutput(prev => [...prev, '[AetherOS] App stopped.']);
                        } catch { setAppRunning(false); }
                      }}
                      className="flex items-center space-x-1.5 px-3 py-1.5 bg-red-700 hover:bg-red-600 text-white rounded-lg text-xs font-bold transition-colors"
                    >
                      <Pause className="w-3.5 h-3.5" /><span>Stop App</span>
                    </button>
                  )}
                  {appRunning && (
                    <a
                      href="http://localhost:8001"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center space-x-1 text-xs text-emerald-400 hover:text-emerald-300"
                    >
                      <ExternalLink className="w-3 h-3" /> localhost:8001
                    </a>
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-4 bg-[#0a0c10] font-mono text-[11px] text-emerald-300 custom-scrollbar space-y-0.5">
                {appOutput.length === 0 ? (
                  <div className="text-muted italic">Press "Run App" to start the generated backend on port 8001.</div>
                ) : (
                  appOutput.map((line, i) => <div key={i} className="leading-relaxed">{line}</div>)
                )}
              </div>
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
