/**
 * ProjectLivePreviewPanel — tracks frontend build progress and shows artifact list + iframe.
 * Renamed from the inline LivePreviewPanel in ProjectView to avoid collision with the
 * existing LiveFeed.jsx component in this directory.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { ChevronDown, Loader2, Monitor, ExternalLink } from 'lucide-react';
import { PHASES, formatBytes } from './projectConstants';
import { api } from '../../api';

const FRONTEND_STAGE = 's04_frontend';
// Ids from before the 12-stage pipeline, kept so older runs still get the panel.
const LEGACY_FRONTEND_PHASE = 'p05_frontend';
const LEGACY_AFTER_FRONTEND = new Set([
  'p06_review_security', 'p07_testing',
  'p08_cicd_deployment', 'p09_observability', 'p10_docs_delivery',
]);

const FILE_ICON = (path) => {
  const ext = path.split('.').pop()?.toLowerCase();
  const icons = {
    jsx: 'x', tsx: 'x', js: 'j', ts: 'j',
    css: 'c', scss: 'c', html: 'h',
    py: 'p', json: '{}', md: 'm',
    svg: 'i', png: 'i', jpg: 'i', gif: 'i',
    sh: 's', env: 'e', yml: 'y', yaml: 'y',
    toml: 'y', txt: 't', sql: 'd',
    dockerfile: 'D',
  };
  return icons[ext] || 'f';
};

const ProjectLivePreviewPanel = ({ runId, currentPhase, runStatus, isRunning, isPaused, liveUrl, appRunning }) => {
  const [artifacts, setArtifacts] = useState([]);
  const [expanded, setExpanded]   = useState(true);
  const [showIframe, setShowIframe] = useState(false);
  const [prevCount, setPrevCount] = useState(0);
  const [newPaths, setNewPaths]   = useState(new Set());
  const timerRef                  = useRef(null);

  const atFrontend      = currentPhase === FRONTEND_STAGE || currentPhase === LEGACY_FRONTEND_PHASE;
  // indexOf is -1 for an unknown stage, so compare against a stage that is known to be in PHASES.
  const pastFrontend    = PHASES.indexOf(currentPhase) > PHASES.indexOf(FRONTEND_STAGE) || LEGACY_AFTER_FRONTEND.has(currentPhase);
  const isFrontendPhase = atFrontend || pastFrontend;
  const isBuildingNow   = atFrontend && isRunning;
  // A run that stopped early has no finished frontend to claim, unless an app is actually up.
  const stoppedEarly    = ['failed', 'cancelled', 'interrupted'].includes(runStatus);
  const frontendReady   = !isRunning && (Boolean(liveUrl) || appRunning || (pastFrontend && !stoppedEarly));
  const shouldShow      = isFrontendPhase || artifacts.length > 0;

  // Promise chain with no state set before the request: this runs from an effect.
  const fetchArtifacts = useCallback(() => {
    if (!runId) return Promise.resolve();
    return api.getRunArtifacts(runId)
      .then((res) => {
        const list = Array.isArray(res.data) ? res.data : [];
        if (list.length > prevCount) {
          setNewPaths(new Set(list.slice(prevCount).map(f => f.path)));
          setPrevCount(list.length);
          setTimeout(() => setNewPaths(new Set()), 2000);
        }
        setArtifacts(list);
      })
      .catch((e) => console.debug('No artifacts yet', e));
  }, [runId, prevCount]);

  useEffect(() => {
    if (!runId || (!isFrontendPhase && !pastFrontend)) return;
    fetchArtifacts();
    if (isRunning || isPaused) {
      timerRef.current = setInterval(fetchArtifacts, 5000);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [runId, currentPhase, isRunning, isPaused]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!shouldShow) return null;

  const frontendFiles = artifacts.filter(f =>
    f.path.startsWith('p05_frontend/') || f.path.startsWith('frontend/')
  );
  const displayFiles = frontendFiles.length > 0 ? frontendFiles : artifacts;

  return (
    <section className="rounded-xl border border-indigo-500/20 bg-[#0d0f18] overflow-hidden shadow-lg">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06] bg-indigo-950/30">
        <div className="flex items-center gap-2.5">
          <span className="text-sm font-bold text-white tracking-tight">Live Preview</span>
          {isBuildingNow && (
            <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] bg-blue-500/15 text-blue-400 border border-blue-500/20 animate-pulse">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-ping inline-block" />
              Building frontend
            </span>
          )}
          {frontendReady && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
              Frontend ready
            </span>
          )}
          {artifacts.length > 0 && (
            <span className="text-[11px] text-slate-500">{artifacts.length} file{artifacts.length !== 1 ? 's' : ''}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {(pastFrontend || (!isRunning && isFrontendPhase)) && (
            <button
              onClick={() => setShowIframe(p => !p)}
              className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-[11px] font-bold bg-indigo-600/80 hover:bg-indigo-500 text-white transition-colors"
            >
              <Monitor className="w-3 h-3" />
              {showIframe ? 'Hide Preview' : 'Open Preview'}
            </button>
          )}
          <button
            onClick={() => setExpanded(p => !p)}
            className="text-slate-500 hover:text-slate-300 transition-colors p-1"
            title={expanded ? 'Collapse' : 'Expand'}
          >
            <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? '' : '-rotate-90'}`} />
          </button>
        </div>
      </div>

      {expanded && (
        <>
          <div className="p-3 max-h-52 overflow-y-auto custom-scrollbar">
            {displayFiles.length === 0 ? (
              <div className="flex items-center gap-2 py-4 justify-center text-slate-600 text-xs italic">
                {isRunning || isPaused ? (
                  <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Files will appear here as the frontend is generated</>
                ) : 'No frontend files were generated'}
              </div>
            ) : (
              <div className="space-y-0.5">
                {displayFiles.map((f) => {
                  const isNew = newPaths.has(f.path);
                  const nameParts = f.path.split('/');
                  const displayName = nameParts[nameParts.length - 1];
                  const dirPath = nameParts.slice(0, -1).join('/');
                  return (
                    <div
                      key={f.path}
                      className={`flex items-center gap-2 py-0.5 px-2 rounded text-[11px] transition-all duration-500 ${
                        isNew ? 'bg-blue-500/10 text-blue-300 border border-blue-500/20' : 'text-slate-400 hover:bg-white/[0.03]'
                      }`}
                    >
                      <span className="text-[10px] shrink-0">{FILE_ICON(f.path)}</span>
                      {dirPath && <span className="text-slate-600 truncate">{dirPath}/</span>}
                      <span className={`font-mono truncate ${isNew ? 'text-blue-300' : 'text-slate-300'}`}>{displayName}</span>
                      {f.size_bytes > 0 && <span className="ml-auto text-slate-600 shrink-0">{formatBytes(f.size_bytes)}</span>}
                      {isNew && <span className="shrink-0 text-[9px] font-bold text-blue-400 uppercase tracking-wider">new</span>}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {showIframe && (
            <div className="border-t border-white/[0.06]">
              {liveUrl ? (
                <div className="flex flex-col">
                  <div className="flex items-center justify-between px-4 py-2 bg-black/30 border-b border-white/[0.04]">
                    <span className="text-[10px] font-mono text-emerald-400">{liveUrl}</span>
                    <a href={liveUrl} target="_blank" rel="noopener noreferrer"
                       className="text-[10px] text-slate-500 hover:text-slate-300 flex items-center gap-1">
                      <ExternalLink className="w-3 h-3" /> Open tab
                    </a>
                  </div>
                  <iframe
                    src={liveUrl}
                    className="w-full bg-white border-none"
                    style={{ height: '320px' }}
                    title="Live App Preview"
                    sandbox="allow-scripts allow-same-origin allow-forms"
                  />
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-10 gap-3 text-center px-8">
                  <Monitor className="w-10 h-10 text-slate-700" />
                  <p className="text-sm font-medium text-slate-400">No live app yet</p>
                  <p className="text-xs text-slate-600 max-w-xs">
                    Deploy the run using the "Deploy to localhost" button above to launch a live preview.
                  </p>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
};

export default ProjectLivePreviewPanel;
