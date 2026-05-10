import axios from 'axios';

// /api prefix required — nginx proxies /api/* → uvicorn. Bare paths return index.html.
const BASE = "/api";

// Module-level navigate reference — set by App.jsx on mount so we can
// use React Router navigation from outside React components.
let _navigate = null;
export const setNavigate = (fn) => { _navigate = fn; };

const client = axios.create({
  baseURL: BASE,
});

client.interceptors.request.use((config) => {
  // Use localStorage so the session persists across tab closes/reopens.
  // sessionStorage was clearing auth state on every new tab, forcing re-login.
  const token = localStorage.getItem('aether_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('aether_token');
      if (_navigate) {
        // React Router navigation — no hard reload, SPA stays alive
        _navigate('/login', { replace: true });
      }
      // (no window.location fallback — hard reloads break SPA routing)
    }
    return Promise.reject(error);
  }
);

export const api = {
  // Expose the raw axios instance so pages can call api.client.get/post directly
  client,

  setToken: (newToken) => {
    localStorage.setItem('aether_token', newToken);
  },
  getToken: () => localStorage.getItem('aether_token'),
  clearToken: () => {
    localStorage.removeItem('aether_token');
  },

  // Auth
  login: async (email, password) => {
    const res = await client.post('/auth/login', { email, password });
    localStorage.setItem('aether_token', res.data.access_token);
    return res.data;
  },
  logout: () => {
    localStorage.removeItem('aether_token');
  },

  // Factory
  startPipeline: (data) => client.post('/factory/start', data),
  listRuns: () => client.get('/factory/runs'),
  getRun: (runId) => client.get(`/factory/runs/${runId}`),
  getRunFiles: (runId) => client.get(`/factory/runs/${runId}/files`),
  getFileContent: (runId, path) => client.get(`/factory/runs/${runId}/file-content`, { params: { path } }),
  approveAction: (ticketId, decision, reason) =>
    client.post(`/pipeline/approve/${ticketId}`, { ticket_id: ticketId, decision, reason }),

  // Run controls
  pauseRun: (runId) => client.post(`/factory/runs/${runId}/pause`),
  resumeRun: (runId) => client.post(`/factory/runs/${runId}/resume`),
  cancelRun: (runId) => client.post(`/factory/runs/${runId}/cancel`),
  setRunPriority: (runId, priority) =>
    client.post(`/factory/runs/${runId}/priority`, { priority }),
  rerunFromPhase: (runId, fromPhase) =>
    client.post(`/factory/runs/${runId}/rerun`, { from_phase: fromPhase }),

  // Deployment
  deployRun:       (runId) => client.post(`/factory/runs/${runId}/deploy`),
  stopDeploy:      (runId) => client.delete(`/factory/runs/${runId}/deploy`),
  listDeployments: ()      => client.get('/factory/deployments'),

  // Portal (Public — uses client so auth token is included if present)
  getPortalStatus: (projectId) => client.get(`/portal/${projectId}/status`),
  getPortalPhase: (projectId, phase) => client.get(`/portal/${projectId}/phase/${phase}`),
  approvePortalPhase: (projectId, approved, comment) =>
    client.post(`/portal/${projectId}/approve`, { approved, comment }),
  sendPortalFeedback: (projectId, feedback, phase) =>
    client.post(`/portal/${projectId}/feedback`, { feedback, phase }),

  // Compliance
  getComplianceReport: () => client.get('/compliance/org-report'),
  getAuditLogs: () => client.get('/audit/logs'),

  // Marketplace
  getMarketplaceProfiles: () => client.get('/marketplace/profiles'),
  installMarketplaceProfile: (profileId) => client.post(`/marketplace/install/${profileId}`),

  // System
  getHealth: () => client.get('/system/health'),
  getCosts: () => client.get('/system/costs'),

  // Settings
  getApiKeys: () => client.get('/settings/api-keys'),
  saveApiKeys: (provider, key) => client.post('/settings/api-keys', { provider, key }),
  testProvider: (provider) => client.post('/settings/test-provider', { provider }),
  getPhaseConfigs: () => client.get('/settings/phases/config'),
  savePhaseConfig: (phase, config) => client.post(`/settings/phases/${phase}/config`, config),

  // Memory
  searchMemory: (query, top_k = 5) => client.post('/memory/search', { query, top_k }),
  getPreferences: () => client.get('/settings/preferences'),
  updatePreferences: (prefs) => client.put('/settings/preferences', prefs),
};

// Default export so pages can do: import api from '../api'
export default api;
