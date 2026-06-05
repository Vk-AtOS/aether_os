import React from 'react';
import { Smartphone, Monitor, ExternalLink as OpenTab } from 'lucide-react';

const DEVICES = [
  { id: 'mobile', label: 'Mobile', icon: Smartphone },
  { id: 'tablet', label: 'Tablet', icon: Monitor },
  { id: 'desktop', label: 'Desktop', icon: Monitor },
];

const iframeWidth = (device) => {
  if (device === 'mobile') return '390px';
  if (device === 'tablet') return '768px';
  return '100%';
};

const AppPreviewPanel = ({ appRunning, run, iframeDevice, setIframeDevice, iframeKey, setIframeKey }) => (
  <div className="flex flex-col" style={{ height: '480px' }}>
    <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-border/10 shrink-0">
      <span className="text-[10px] font-mono text-muted truncate">
        {appRunning ? 'Generated app running — live preview' : (run?.live_url || 'Start the app to see live preview')}
      </span>
      <div className="flex items-center gap-2">
        {/* Device size toggle */}
        <div className="flex items-center gap-1">
          {DEVICES.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setIframeDevice(id)}
              className={`p-1 rounded text-xs ${iframeDevice === id ? 'text-accent bg-accent/10' : 'text-muted hover:text-bright'}`}
              title={label}
            >
              <Icon className="w-3.5 h-3.5" />
            </button>
          ))}
        </div>
        {/* Refresh button */}
        {(appRunning || run?.live_url) && (
          <button
            onClick={() => setIframeKey(k => k + 1)}
            className="p-1 rounded text-muted hover:text-bright text-[10px]"
            title="Refresh preview"
          >
            ↺
          </button>
        )}
        {appRunning && (
          <a href="/app-preview/" target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1 text-[10px] text-accent hover:underline shrink-0">
            <OpenTab className="w-3 h-3" /> Open in tab
          </a>
        )}
        {!appRunning && run?.live_url && (
          <a href={run.live_url} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1 text-[10px] text-accent hover:underline shrink-0 ml-2">
            <OpenTab className="w-3 h-3" /> Open
          </a>
        )}
      </div>
    </div>
    {appRunning ? (
      <iframe
        key={`app-preview-live-${iframeKey}`}
        src="/app-preview/"
        style={{
          width: iframeWidth(iframeDevice),
          maxWidth: '100%',
          margin: '0 auto',
          display: 'block',
          flex: 1,
          border: 'none',
        }}
        className="bg-white"
        title="Live App Preview"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
      />
    ) : run?.live_url ? (
      <iframe
        key={`app-preview-url-${iframeKey}`}
        src={run.live_url}
        style={{
          width: iframeWidth(iframeDevice),
          maxWidth: '100%',
          margin: '0 auto',
          display: 'block',
          flex: 1,
          border: 'none',
        }}
        className="bg-white"
        title="Deployed App Preview"
        sandbox="allow-scripts allow-same-origin allow-forms"
      />
    ) : (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted text-sm">
        <span className="text-4xl opacity-30">▶</span>
        <p>Click <strong className="text-bright">RUN APP</strong> to start the generated app and see a live preview here.</p>
      </div>
    )}
  </div>
);

export default AppPreviewPanel;
