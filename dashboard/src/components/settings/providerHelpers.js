// Pure helpers for the model providers panel (KAN-18). No React, so they can be tested.

export const LEVELS = ['public', 'internal', 'restricted'];

export const LEVEL_HELP = {
  public: 'Public material only: docs, research, code drafts.',
  internal: 'Internal company material that is not personal data.',
  restricted: 'Pay, bank, identity, health and candidate data. Only for providers you trust with it.',
};

// What the test button may say. The server sends a fixed code; never the provider's own text.
export const TEST_TEXT = {
  key_rejected: 'The provider rejected the key.',
  timeout: 'The provider did not answer in time.',
  unavailable: 'The provider is not reachable.',
  address_not_allowed: 'This address is not allowed (a local address needs "allow local").',
  no_such_provider: 'This provider no longer exists.',
  failed: 'The test failed.',
};

export const testMessage = (r) => (r.ok ? `Working (${r.models ?? 0} models, ${r.latency_s}s)` : (TEST_TEXT[r.error] || TEST_TEXT.failed));

// A provider's levels, with `restricted` unavailable for a free pool (the server refuses it as well).
export const toggleLevel = (levels, level, freePool) => {
  if (freePool && level === 'restricted') return levels;
  return levels.includes(level) ? levels.filter((l) => l !== level) : [...levels, level];
};

export const keyShown = (p) => (p.has_key ? `••••${p.key_last4}` : 'no key');

// The message of a Velaris error ({error: {code, message}}) or the gateway's {detail}.
export const providerError = (e, fallback) =>
  e?.response?.data?.error?.message || (typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : '') || fallback;

// Cost is an estimate from the catalogue; unknown prices show as "unknown", never as 0.
export const costText = (day) => (day.unpriced_calls > 0 && day.cost_usd === 0 ? 'unknown' : `$${day.cost_usd.toFixed(4)}`);

// AHM / breaker state of a platform provider (GET /settings/provider-status). Fixed sentences, no provider text.
export const HEALTH_TEXT = {
  healthy: 'Healthy',
  degraded: 'Degraded: recent calls are failing, the router tries it last',
  down: 'Circuit breaker open: calls are skipped until it recovers',
  unknown: 'No calls yet',
};
export const healthText = (h) => HEALTH_TEXT[h?.state] || HEALTH_TEXT.unknown;
export const keyStatusText = (p) => {
  if (p.uses_platform_credentials) return "Uses the platform's AWS credentials";
  if (p.has_org_key) return "Your organisation's key is on file";
  return p.platform_key ? 'No key of your own: the platform key is used' : 'No key';
};
