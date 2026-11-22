// Opens a run's app preview in its own tab. The "Live App" button opens this dashboard page (same origin, already
// signed in through localStorage) instead of an about:blank tab that the dashboard later steers: on 22 Nov 2026 the
// owner's Chrome left those tabs blank and spinning although the preview link had been issued. This page asks for the
// single-use preview link itself and replaces its own location with it.
import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { previewErrorMessage, requestPreviewUrl } from '../previewSession';

export default function PreviewOpen() {
  const { runId } = useParams();
  const [error, setError] = useState(null);
  useEffect(() => {
    let cancelled = false;
    requestPreviewUrl(runId)
      .then((url) => { if (!cancelled) window.location.replace(url); })
      .catch((err) => { if (!cancelled) setError(previewErrorMessage(err)); });
    return () => { cancelled = true; };
  }, [runId]);
  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', padding: '48px', color: '#cbd5e1', background: '#0b1020',
                  minHeight: '100vh' }}>
      {error ? <p role="alert">{error}</p> : <p>Opening the app preview…</p>}
    </div>
  );
}
