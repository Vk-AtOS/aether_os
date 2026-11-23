// Shared by the Playwright specs: a signed-in browser and a stubbed API.
export const jwt = (payload) => `h.${Buffer.from(JSON.stringify(payload)).toString('base64url')}.s`;

export const signIn = async (page, role = 'owner') => {
  const token = jwt({ sub: 'u@example.com', user_id: 'u1', org_id: 'org1', role });
  await page.addInitScript((t) => { localStorage.setItem('aether_token', t); }, token);
};

// Stub every /api call. `routes` maps "METHOD /path" to a body (or a function (request) => body | {status, body}).
// Unknown GETs answer {}; unknown writes answer {} too. Returns the list of calls made, for assertions.
// Answers shaped like the real API for list endpoints, so a screen is judged on real shapes, not on {}.
const DEFAULTS = {
  'GET /factory/runs': { items: [], runs: [], total: 0 },
  'GET /settings/models': [],
  'GET /settings/phases/config': [],
  'GET /workspaces': [],
  'GET /webhooks': [],
  'GET /marketplace/profiles': [],
  'GET /marketplace/installed': [],
  'GET /v2/plugins/catalog': [],
  'GET /v2/plugins/installed': [],
  'GET /guardian/status': { status: 'ok', checks: [] },
  'GET /guardian/stats': { total: 0, unresolved: 0, by_type: {}, by_severity: {} },
  'GET /guardian/events': { events: [], items: [], total: 0 },
  'GET /velaris/inventory': { departments: [], totals: {}, total: 0 },
  'GET /velaris/agents': { agents: [], failed: [] },
  'GET /prime/meta': { never: [], payment_ceiling: 500000, currency: 'INR', action_types: [], autonomy_levels: [], max_delegation_days: 30 },
  'GET /prime/delegations': { delegations: [], items: [] },
  'GET /prime/activity': { entries: [], items: [] },
  'GET /prime/ledger/verify': { ok: true, entries_checked: 0 },
  'GET /prime/inbox/count': { pending: 0, urgent: 0 },
  'GET /mail/mailboxes': { mailboxes: [] },
  'GET /control/tasks': { tasks: [] },
  'GET /memory/graph': { nodes: [], edges: [], stats: {} },
  'GET /admin/users': { items: [], page: 1, limit: 50, total: 0 },
  'GET /prime/data/me': {
    notice: 'Prime can learn how you work.', notice_version: 'v1', retention_days: 365, newest: [],
    counts: { git: 0, jira: 0, calendar: 0, attendance: 0 },
    switches: ['all', 'git', 'jira', 'calendar', 'attendance'].map((source) => (
      { source, enabled: false, purpose: `${source} purpose`, enabled_at: null, changed_at: null, notice_version: null })),
  },
};

export const stubApi = async (page, routes = {}) => {
  const calls = [];
  await page.route('**/api/**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace(/^.*?\/api/, '');
    const key = `${req.method()} ${path}`;
    calls.push({ key, body: req.postDataJSON?.() ?? null });
    const hit = routes[key] ?? routes[`${req.method()} *`] ?? DEFAULTS[key];
    let out = typeof hit === 'function' ? hit(req) : hit;
    const status = out && typeof out === 'object' && 'status' in out && 'body' in out ? out.status : 200;
    if (status !== 200 && out) out = out.body;
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(out ?? {}) });
  });
  return calls;
};

// Every route the app declares (App.jsx), reachable by an owner. :params get stub values.
export const ROUTES = [
  '/', '/new', '/projects', '/project/r1', '/settings', '/compliance', '/marketplace', '/connectors', '/skills',
  '/memory', '/costs', '/admin/users', '/admin/billing', '/admin/intelligence', '/profile', '/settings/webhooks',
  '/settings/api-keys', '/decisions', '/frontend-builder', '/backend-builder', '/prompt', '/audit', '/learning',
  '/intelligence', '/search', '/deployments', '/health', '/guardian', '/agents', '/designer', '/workspaces',
  '/operations', '/prime', '/prime/data', '/chat', '/mail', '/control', '/hr', '/runs/r1',
];
