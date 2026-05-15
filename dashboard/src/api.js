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

// Track in-flight refresh to avoid stampede — multiple 401s share one refresh attempt.
let _refreshPromise = null;

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
  async (error) => {
    const original = error.config;
    if (
      error.response?.status === 401 &&
      !original._retried &&
      !original.url?.includes('/auth/refresh') &&
      !original.url?.includes('/auth/login')
    ) {
      const refreshToken = localStorage.getItem('aether_refresh_token');
      if (refreshToken) {
        original._retried = true;
        try {
          if (!_refreshPromise) {
            _refreshPromise = axios
              .post(`${BASE}/auth/refresh`, { refresh_token: refreshToken })
              .finally(() => { _refreshPromise = null; });
          }
          const res = await _refreshPromise;
          localStorage.setItem('aether_token', res.data.access_token);
          if (res.data.refresh_token) {
            localStorage.setItem('aether_refresh_token', res.data.refresh_token);
          }
          original.headers.Authorization = `Bearer ${res.data.access_token}`;
          return client(original);
        } catch (_) {
          // Refresh failed — fall through to logout
        }
      }
      localStorage.removeItem('aether_token');
      localStorage.removeItem('aether_refresh_token');
      if (_navigate) {
        _navigate('/login', { replace: true });
      }
    }
    return Promise.reject(error);
  }
);

export const api = {
  // Expose the raw axios instance so pages can call api.client.get/post directly
  client,

  setToken: (newToken, refreshToken) => {
    localStorage.setItem('aether_token', newToken);
    if (refreshToken) localStorage.setItem('aether_refresh_token', refreshToken);
  },
  getToken: () => localStorage.getItem('aether_token'),
  clearToken: () => {
    localStorage.removeItem('aether_token');
    localStorage.removeItem('aether_refresh_token');
  },

  // Auth
  login: async (email, password) => {
    const res = await client.post('/auth/login', { email, password });
    localStorage.setItem('aether_token', res.data.access_token);
    if (res.data.refresh_token) localStorage.setItem('aether_refresh_token', res.data.refresh_token);
    return res.data;
  },
  logout: () => {
    localStorage.removeItem('aether_token');
    localStorage.removeItem('aether_refresh_token');
  },

  // Factory
  startPipeline: (data) => client.post('/factory/start', data),
  listRuns: (page = 1, limit = 50) => client.get('/factory/runs', { params: { page, limit } }),
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
  rerunFromPhase: (runId, fromPhase, extraInput) =>
    client.post(`/factory/runs/${runId}/rerun`, { from_phase: fromPhase, extra_input: extraInput }),
  branchRun: (runId, branchPhase, extraInput) =>
    client.post(`/factory/runs/${runId}/branch`, { branch_phase: branchPhase, extra_input: extraInput }),

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
  getLlmConfig: () => client.get('/settings/llm-config'),
  updateLlmConfig: (cfg) => client.put('/settings/llm-config', cfg),
  getAvailableModels: () => client.get('/settings/models'),
  testModel: (model) => client.post('/settings/models/test', { model }),
  getCouncilConfig: () => client.get('/settings/council-config'),
  updateCouncilConfig: (cfg) => client.put('/settings/council-config', cfg),

  // Artifacts & Download
  getRunArtifacts: (runId) => client.get(`/factory/runs/${runId}/artifacts`),
  downloadRunZip: (runId) => client.get(`/factory/runs/${runId}/download`, { responseType: 'blob' }),

  // GitHub push
  pushToGitHub: (runId, data) => client.post(`/factory/runs/${runId}/push-github`, data),

  // Cost estimate
  estimateCost: (data) => client.post('/factory/estimate', data),

  // Templates
  getTemplates: () => client.get('/templates'),

  // File upload for requirements
  uploadRequirementFile: (formData) => client.post('/factory/upload-requirement', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),

  // GitHub repo fetch
  fetchGitHubRepo: (data) => client.post('/factory/fetch-github-repo', data),

  // Memory
  searchMemory: (query, top_k = 5) => client.post('/memory/search', { query, top_k }),
  getPreferences: () => client.get('/settings/preferences'),
  updatePreferences: (prefs) => client.put('/settings/preferences', prefs),
};

// Default export so pages can do: import api from '../api'
export default api;
