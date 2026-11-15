// Turns the answer of GET /readyz ({ready, degraded: [component names]}) into the status pill's label and level.
// A 503 body has the same shape, so callers pass err.response.data for it. Returns null when there is nothing to show.
export function readinessStatus(r) {
  if (!r || typeof r.ready !== 'boolean') return null;
  const names = Array.isArray(r.degraded) ? r.degraded : [];
  if (!r.ready) return { label: `Down: ${names.join(', ') || 'unavailable'}`, level: 'critical' };
  if (names.length) return { label: `Degraded: ${names.join(', ')}`, level: 'warning' };
  return null;
}
