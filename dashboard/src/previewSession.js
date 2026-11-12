// Generated apps are served from a per-run origin by the preview server, never from the
// dashboard. A link into one is a single-use token from POST /factory/runs/{id}/preview-session,
// so every iframe and "open" link asks for a fresh one.
import { api } from './api';
import { apiError } from './apiError';

// Same-origin is the PREVIEW origin (the app's own cookie/storage); it cannot reach the dashboard.
// No top-level navigation flag on purpose: the app must not navigate the dashboard.
export const PREVIEW_SANDBOX = 'allow-scripts allow-same-origin allow-forms allow-popups allow-modals';

// run.live_url is "/app-preview/..." for a launched app; anything else is a deployed container URL.
export const isPreviewUrl = (url) => typeof url === 'string' && url.includes('/app-preview/');

export const previewErrorMessage = (err) => {
  if (err?.response?.status === 503) {
    return 'App preview is not configured on this server (the preview origin is not set). Ask an administrator to set AETHER_PREVIEW_ORIGIN and AETHER_PREVIEW_SECRET.';
  }
  if (err?.response?.status === 403) return 'Sign in as a user (not an API key) to open previews.';
  if (err?.response?.status === 404) return 'This run was not found.';
  return `Could not open the preview: ${apiError(err) || err?.message || 'unknown error'}`;
};

// Resolves to the single-use enter URL on the run's own preview origin.
export const requestPreviewUrl = async (runId) => (await api.createPreviewSession(runId)).data.url;

// Open the preview in a new tab. The tab is opened first (inside the click) so popup blockers
// allow it, then pointed at the one-time link. Resolves to an error message or null.
export const openPreviewInTab = async (runId) => {
  const tab = window.open('about:blank', '_blank');
  if (tab) tab.opener = null;
  try {
    const url = await requestPreviewUrl(runId);
    if (tab) tab.location.href = url; else window.location.assign(url);
    return null;
  } catch (err) {
    if (tab) tab.close();
    return previewErrorMessage(err);
  }
};
