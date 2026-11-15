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
      // If server explicitly requests re-authentication, skip refresh and redirect immediately.
      const forceReauth = error.response?.data?.action === 're_authenticate';
      const refreshToken = localStorage.getItem('aether_refresh_token');
      if (!forceReauth && refreshToken) {
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
        } catch {
          // Refresh tokens are single-use. If another tab refreshed first, it has already
          // stored a newer pair: use that instead of signing this tab out.
          const latest = localStorage.getItem('aether_token');
          if (localStorage.getItem('aether_refresh_token') !== refreshToken && latest) {
            original.headers.Authorization = `Bearer ${latest}`;
            return client(original);
          }
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

// Client portal calls. The portal token comes from the link fragment (#t=...), is
// held in memory only (never localStorage) and is sent as X-Portal-Token. Without one,
// a signed-in member of the owning org is sent with their session. A separate axios
// instance: a 401 here means "this link is not valid", not "sign in again", so the
// refresh-and-redirect interceptor above must not run.
let _portalToken = null;
export const setPortalToken = (token) => { _portalToken = token || null; };
const portalClient = axios.create({ baseURL: BASE });
portalClient.interceptors.request.use((config) => {
  if (_portalToken) {
    config.headers['X-Portal-Token'] = _portalToken;
  } else {
    const token = localStorage.getItem('aether_token');
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

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
  // Revoke the session server-side first (best effort), then drop the local tokens.
  logout: async () => {
    try { await client.post('/auth/logout'); } catch { /* already signed out */ }
    localStorage.removeItem('aether_token');
    localStorage.removeItem('aether_refresh_token');
  },
  getMyOrgs: () => client.get('/auth/my-orgs'),
  switchOrg: (orgId) => client.post('/auth/switch-org', { org_id: orgId }),

  // Org settings
  getOrgSettings: () => client.get('/account/settings'),
  updateOrgSettings: (data) => client.post('/account/settings', data),
  // FE-C1: corrected URL — backend soft-deletes the current org (no path param).
  // The caller is identified from the JWT, not from the URL.
  deleteOrg: () => client.delete('/org'),

  // Organisation API keys (owner/admin). Not the LLM provider keys below.
  listOrgApiKeys: () => client.get('/auth/api-keys'),
  createOrgApiKey: (name) => client.post('/auth/api-keys', { name }),
  revokeOrgApiKey: (id) => client.delete(`/auth/api-keys/${id}`),

  // SCIM
  getScimConfig: () => client.get('/settings/scim'),
  rotateScimToken: () => client.post('/settings/scim/rotate'),

  // Factory
  startPipeline: (data) => client.post('/factory/start', data),
  listRuns: (page = 1, limit = 50) => client.get('/factory/runs', { params: { page, limit } }),
  getRun: (runId) => client.get(`/factory/runs/${runId}`),
  // Streamed model output (llm_chunk) is most of the rows and none of what the views read.
  getRunEvents: (runId) => client.get(`/factory/runs/${runId}/events`, { params: { exclude: 'llm_chunk' } }),
  getRunFiles: (runId) => client.get(`/factory/runs/${runId}/files`),
  getFileContent: (runId, path) => client.get(`/factory/runs/${runId}/file-content`, { params: { path } }),
  patchFileContent: (runId, path, content) => client.patch(`/factory/runs/${runId}/file-content`, { path, content }),
  openInVSCode: (runId) => client.post(`/factory/runs/${runId}/open-in-vscode`),
  getEnvVars: (runId) => client.get(`/factory/runs/${runId}/envvars`),
  patchEnvVars: (runId, vars) => client.patch(`/factory/runs/${runId}/envvars`, { vars }),
  startRunApp: (runId) => client.post(`/factory/runs/${runId}/run-app`),
  stopRunApp: (runId) => client.delete(`/factory/runs/${runId}/run-app`),
  getRunAppStatus: (runId) => client.get(`/factory/runs/${runId}/run-app/status`),
  createPreviewSession: (runId) => client.post(`/factory/runs/${runId}/preview-session`),
  getClarifyingAnswers: (runId) => client.get(`/factory/runs/${runId}/clarifying-answers`),
  submitClarifyingAnswers: (runId, answers, restart = false) => client.post(`/factory/runs/${runId}/clarifying-answers`, { answers, restart }),
  getPreviewCredentials: (runId) => client.get(`/factory/runs/${runId}/preview-credentials`),
  approveAction: (ticketId, decision, reason) =>
    client.post(`/pipeline/approve/${ticketId}`, { ticket_id: ticketId, decision, reason }),
  listDecisions: (runId, status) => client.get(`/factory/runs/${runId}/decisions`, { params: status ? { status } : {} }),
  approveDecision: (runId, decisionId, approved, reason) =>
    client.post(`/factory/runs/${runId}/decisions/${decisionId}/decide`, { approved, reason }),

  // Spec review gate
  getRunSpec: (runId) => client.get(`/factory/runs/${runId}/spec`),
  approveSpec: (runId, action = 'approve') => client.post(`/factory/runs/${runId}/approve-spec`, { action }),

  // Run controls
  pauseRun: (runId) => client.post(`/factory/runs/${runId}/pause`),
  resumeRun: (runId, extraInput) => client.post(`/factory/runs/${runId}/resume`, extraInput || {}),
  cancelRun: (runId) => client.post(`/factory/runs/${runId}/cancel`),
  setRunPriority: (runId, priority) =>
    client.post(`/factory/runs/${runId}/priority`, { priority }),
  // Resume a failed/cancelled run in place from its checkpoint (the blocked stage).
  restartRun: (runId) => client.post(`/factory/runs/${runId}/restart`),
  rerunFromPhase: (runId, fromPhase, extraInput) =>
    client.post(`/factory/runs/${runId}/rerun`, { from_phase: fromPhase, extra_input: extraInput }),
  branchRun: (runId, branchPhase, extraInput) =>
    client.post(`/factory/runs/${runId}/branch`, { branch_phase: branchPhase, extra_input: extraInput }),

  // Deployment
  deployRun:       (runId) => client.post(`/factory/runs/${runId}/deploy`),
  stopDeploy:      (runId) => client.delete(`/factory/runs/${runId}/deploy`),
  listDeployments: ()      => client.get('/factory/deployments'),

  // Client portal: see portalClient below.
  getPortalStatus: (projectId) => portalClient.get(`/portal/${projectId}/status`),
  approvePortal: (projectId, approved, comment) =>
    portalClient.post(`/portal/${projectId}/approve`, { approved, comment }),

  // Client access (owning org, owner/admin)
  listPortalTokens: (runId) => client.get(`/factory/runs/${runId}/portal-tokens`),
  issuePortalToken: (runId, label, expiresInDays) =>
    client.post(`/factory/runs/${runId}/portal-tokens`, { label, expires_in_days: expiresInDays }),
  revokePortalToken: (runId, tokenId) => client.delete(`/factory/runs/${runId}/portal-tokens/${tokenId}`),
  listPortalApprovals: (runId) => client.get(`/factory/runs/${runId}/portal-approvals`),

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

  // Quality & Compliance
  getRunQuality: (runId) => client.get(`/factory/runs/${runId}/quality`),
  getRunCompliance: (runId) => client.get(`/factory/runs/${runId}/compliance`),
  getQualityTrend: (limit = 50) => client.get('/factory/analytics/quality-trend', { params: { limit } }),

  // Webhooks
  getWebhooks: () => client.get('/webhooks'),
  createWebhook: (data) => client.post('/webhooks', data),
  deleteWebhook: (id) => client.delete(`/webhooks/${id}`),

  // Webhooks (extended)
  updateWebhook: (id, data) => client.put(`/webhooks/${id}`, data),
  testWebhook: (id) => client.post(`/webhooks/${id}/test`),

  // Workspaces (extended)
  updateWorkspace: (id, data) => client.put(`/workspaces/${id}`, data),

  // Marketplace (extended)
  uninstallMarketplaceProfile: (profileId) => client.delete(`/marketplace/profiles/${profileId}`),
  getInstalledProfiles: () => client.get('/marketplace/installed'),

  // Admin users (extended)
  reactivateUser: (userId) => client.post(`/admin/users/${userId}/reactivate`),
  resetUserPassword: (userId) => client.post(`/admin/users/${userId}/reset-password`),

  // Billing (extended)
  getBillingStatus: () => client.get('/billing/status'),
  getInvoices: () => client.get('/billing/invoices'),
  cancelSubscription: () => client.post('/billing/cancel'),

  // Workspaces
  getWorkspaces: () => client.get('/workspaces'),
  createWorkspace: (data) => client.post('/workspaces', data),
  deleteWorkspace: (id) => client.delete(`/workspaces/${id}`),

  // LLM Traces
  getRunTraces: (runId) => client.get(`/factory/runs/${runId}/traces`),
  getRunTraceDetail: (runId, traceId) => client.get(`/factory/runs/${runId}/traces/${traceId}`),

  // Operations (Velaris)
  getVelarisInventory: () => client.get('/velaris/inventory'),
  getVelarisAgents: () => client.get('/velaris/agents'),
  callVelarisAgent: (agent, method, args) => client.post(`/velaris/agents/${agent}/${method}`, args),

  // Prime
  getPrimeMeta: () => client.get('/prime/meta'),
  listDelegations: () => client.get('/prime/delegations'),
  createDelegation: (data) => client.post('/prime/delegations', data),
  revokeDelegation: (id) => client.post(`/prime/delegations/${id}/revoke`),
  checkPrimeAction: (data) => client.post('/prime/check', data),
  getPrimeActivity: () => client.get('/prime/activity'),
  verifyLedger: () => client.get('/prime/ledger/verify'),
};

// Default export so pages can do: import api from '../api'
export default api;
