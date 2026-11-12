import React, { useState, useEffect } from 'react';
import { Play, Pause, ExternalLink, Copy, Check } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';
import { openPreviewInTab } from '../../previewSession';

const RunAppPanel = ({ runId, onToast, onRunningChange }) => {
  const [appRunning, setAppRunning] = useState(false);

  // Keep parent ProjectView in sync so AppPreviewPanel shows correctly
  const setRunning = (val) => { setAppRunning(val); onRunningChange?.(val); };
  const [appOutput, setAppOutput] = useState([]);
  const [previewCreds, setPreviewCreds] = useState(null);
  const [credsCopied, setCredsCopied] = useState(false);

  // Restore running state on mount
  useEffect(() => {
    api.getRunAppStatus(runId)
      .then(r => {
        if (r.data?.running) {
          setAppRunning(true);
          onRunningChange?.(true);
          setAppOutput(['[AetherOS] App is already running — preview available.']);
        }
      })
      .catch(() => {});
    api.getPreviewCredentials(runId)
      .then(r => setPreviewCreds(r.data))
      .catch(() => {});
  }, [runId, onRunningChange]);

  const handleStart = async () => {
    try {
      const res = await api.startRunApp(runId);
      setRunning(true);
      const email = res.data?.preview_email || null;
      const pw    = res.data?.preview_password || null;
      setPreviewCreds(email ? { email, password: pw } : null);
      const credLine = email
        ? `[AetherOS] Demo login → ${email} / ${pw}`
        : "[AetherOS] Check your generated app's seed data for login credentials";
      setAppOutput([
        '[AetherOS] Starting app… (builds frontend + installs deps ~15s)',
        credLine,
        '[AetherOS] Preview available in the APP PREVIEW tab (opens on its own origin).',
      ]);
      onToast('App starting — demo credentials shown below.');
    } catch (e) {
      onToast('Failed to start app: ' + (apiError(e) || e.message));
    }
  };

  const handleStop = async () => {
    try {
      await api.stopRunApp(runId);
      setRunning(false);
      setAppOutput(prev => [...prev, '[AetherOS] App stopped.']);
    } catch {
      setRunning(false);
    }
  };

  const copyCreds = () => {
    if (!previewCreds) return;
    navigator.clipboard.writeText(`${previewCreds.email}\n${previewCreds.password}`);
    setCredsCopied(true);
    setTimeout(() => setCredsCopied(false), 1800);
  };

  return (
    <div className="flex flex-col h-[420px]">
      <div className="flex items-center space-x-3 px-4 py-2.5 border-b border-border bg-border/10 shrink-0">
        <span className="text-xs font-bold text-muted uppercase tracking-wider">App Runner</span>
        <div className="flex items-center space-x-2 ml-auto">
          {!appRunning ? (
            <button
              onClick={handleStart}
              className="flex items-center space-x-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition-colors"
            >
              <Play className="w-3.5 h-3.5" /><span>Run App</span>
            </button>
          ) : (
            <button
              onClick={handleStop}
              className="flex items-center space-x-1.5 px-3 py-1.5 bg-red-700 hover:bg-red-600 text-white rounded-lg text-xs font-bold transition-colors"
            >
              <Pause className="w-3.5 h-3.5" /><span>Stop App</span>
            </button>
          )}
          {appRunning && (
            <button
              onClick={async () => { const err = await openPreviewInTab(runId); if (err) onToast(err); }}
              className="flex items-center space-x-1 text-xs text-emerald-400 hover:text-emerald-300"
            >
              <ExternalLink className="w-3 h-3" /> Open App Preview
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 bg-[#0a0c10] font-mono text-[11px] text-emerald-300 custom-scrollbar space-y-0.5">
        {appOutput.length === 0 ? (
          <div className="text-muted italic">Press "Run App" to start the generated app. A live preview will appear in the APP PREVIEW tab.</div>
        ) : (
          appOutput.map((line, i) => <div key={i} className="leading-relaxed">{line}</div>)
        )}
      </div>

      {previewCreds && (
        <div className="border-t border-border px-4 py-3 bg-emerald-950/30 flex items-center justify-between gap-4 shrink-0">
          <div className="flex items-center gap-3 text-[11px]">
            <span className="text-emerald-400 font-bold uppercase tracking-wider text-[10px]">Demo Login</span>
            <span className="font-mono text-emerald-300">{previewCreds.email}</span>
            <span className="text-muted">·</span>
            <span className="font-mono text-emerald-300 tracking-wider">{previewCreds.password}</span>
          </div>
          <button
            onClick={copyCreds}
            className="flex items-center gap-1 px-2 py-1 bg-emerald-800/40 hover:bg-emerald-700/50 text-emerald-300 rounded text-[10px] font-bold transition-colors shrink-0"
          >
            {credsCopied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            {credsCopied ? 'Copied' : 'Copy'}
          </button>
        </div>
      )}
    </div>
  );
};

export default RunAppPanel;
