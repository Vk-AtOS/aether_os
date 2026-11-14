import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { PREVIEW_SANDBOX, isPreviewUrl, previewErrorMessage, requestPreviewUrl } from '../../previewSession';

// iframe into a run's generated app. A launched app (/app-preview/) is reached through a fresh
// single-use link from the preview-session endpoint (so `refreshKey` re-requests one); a deployed
// container URL is used as is. 503 (preview origin not configured) shows a clear message.
const PreviewFrame = ({ runId, liveUrl, refreshKey = 0, title, style, className = 'bg-white' }) => {
  const viaPreview = !liveUrl || isPreviewUrl(liveUrl);
  const [state, setState] = useState({ key: null, url: null, error: null });
  const wanted = `${runId}:${refreshKey}`;

  useEffect(() => {
    if (!viaPreview || !runId) return undefined;
    let cancelled = false;
    requestPreviewUrl(runId)
      .then((url) => { if (!cancelled) setState({ key: wanted, url, error: null }); })
      .catch((err) => { if (!cancelled) setState({ key: wanted, url: null, error: previewErrorMessage(err) }); });
    return () => { cancelled = true; };
  }, [viaPreview, runId, wanted]);

  const src = viaPreview ? (state.key === wanted ? state.url : null) : liveUrl;
  if (viaPreview && state.key === wanted && state.error) {
    return <div role="alert" className="flex-1 flex items-center justify-center px-6 py-8 text-center text-sm text-red-300">{state.error}</div>;
  }
  if (!src) {
    return <div className="flex-1 flex items-center justify-center gap-2 py-8 text-sm text-muted"><Loader2 className="w-4 h-4 animate-spin" /> Opening preview...</div>;
  }
  // allow-same-origin is only safe on a different origin than the dashboard (JWT in localStorage).
  if (new URL(src, window.location.href).origin === window.location.origin && viaPreview) {
    return <div role="alert" className="flex-1 flex items-center justify-center px-6 py-8 text-center text-sm text-red-300">The preview origin is the same as the dashboard origin, so the app is not shown. Set AETHER_PREVIEW_ORIGIN to a separate host.</div>;
  }
  return <iframe key={src} src={src} title={title} className={className} style={style} sandbox={PREVIEW_SANDBOX} />;
};

export default PreviewFrame;
