import axios from 'axios';

const BASE = ""; // Use relative paths to stay on same origin

// Module-level navigate reference — set by App.jsx on mount so we can
// use React Router navigation from outside React components.
let _navigate = null;
export const setNavigate = (fn) => { _navigate = fn; };

const client = axios.create({
  baseURL: BASE,
});

client.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('aether_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      sessionStorage.removeItem('aether_token');
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
  setToken: (newToken) => { 
    sessionStorage.setItem('aether_token', newToken); 
  },
  getToken: () => sessionStorage.getItem('aether_token'),
  clearToken: () => { 
    sessionStorage.removeItem('aether_token'); 
  },
  
  // Auth
  login: async (email, password) => {
    const res = await client.post('/auth/login', { email, password });
    sessionStorage.setItem('aether_token', res.data.access_token);
    return res.data;
  },
  logout: () => { 
    sessionStorage.removeItem('aether_token'); 
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

  // Portal (Public)
  getPortalStatus: (projectId) => axios.get(`${BASE}/portal/${projectId}/status`),
  getPortalPhase: (projectId, phase) => axios.get(`${BASE}/portal/${projectId}/phase/${phase}`),
  approvePortalPhase: (projectId, approved, comment) => 
    axios.post(`${BASE}/portal/${projectId}/approve`, { approved, comment }),
  sendPortalFeedback: (projectId, feedback, phase) => 
    axios.post(`${BASE}/portal/${projectId}/feedback`, { feedback, phase }),

  // System
  getHealth: () => client.get('/system/health'),
  getCosts: () => client.get('/system/costs'),

  // Settings
  getApiKeys: () => client.get('/settings/api-keys'),
  saveApiKeys: (provider, key) => client.post('/settings/api-keys', { provider, key }),
  testProvider: (provider) => client.post('/settings/test-provider', { provider }),
  getPhaseConfigs: () => client.get('/settings/phases/config'),
  savePhaseConfig: (phase, config) => client.post(`/settings/phases/${phase}/config`, config),
};
