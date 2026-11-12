// One place that turns an API error into something a person can read.
// FastAPI sends `detail` as a string, as a list of validation errors, or (policy
// denials, gateway/policy_guard.py) as {error: <reason>, action, ...facts}.

const ROLE_WORD = { viewer: 'viewer', member: 'member', admin: 'admin', owner: 'owner', superadmin: 'platform operator' };

const POLICY_MESSAGES = {
  trial_limit_reached: (d) =>
    `Your trial has used all its builds${d.limit ? ` (${d.used ?? d.limit} of ${d.limit})` : ''}. Upgrade to keep building.`,
  quota_runs_per_period: (d) =>
    `Your plan allows ${d.limit ?? 'a limited number of'} builds every ${d.period_days ?? 30} days and you have used them. Upgrade or wait for the period to roll over.`,
  quota_concurrent_runs: (d) =>
    `Your plan allows ${d.limit ?? 'a limited number of'} build${d.limit === 1 ? '' : 's'} at a time and ${d.running ?? 'that many'} ${d.running === 1 ? 'is' : 'are'} running. Wait for one to finish or cancel one.`,
  role_insufficient: (d) => (d.required_role === 'superadmin'
    ? 'Only a platform operator can do this.'
    : `This needs the ${ROLE_WORD[d.required_role] || d.required_role || 'a higher'} role in your organisation. Ask an owner or admin.`),
  role_unknown: () => 'Your account has no recognised role in this organisation. Ask an owner to set one.',
  org_inactive: () => 'This organisation has been deactivated, so nothing new can be started.',
  org_not_found: () => 'Your organisation could not be found. Sign out and back in.',
  plan_unknown: () => 'Your organisation has no recognised plan. Contact support.',
  policy_unavailable: () => 'Permission checks are unavailable right now, so the action was refused. Try again shortly.',
  unknown_action: () => 'This action is not allowed.',
};

const humanise = (code) => String(code).replace(/_/g, ' ');

/** Readable message from an axios error; '' when the server sent no detail. */
export const apiError = (err) => {
  const d = err?.response?.data?.detail;
  if (d == null || d === '') return '';
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    // Pydantic validation list: [{loc: [...], msg: '...'}]
    return d.map((v) => {
      const field = Array.isArray(v?.loc) ? v.loc.filter((p) => p !== 'body').join('.') : '';
      return field ? `${field}: ${v?.msg || 'invalid'}` : (v?.msg || String(v));
    }).join('; ');
  }
  if (typeof d === 'object') {
    const code = d.error || d.reason || d.code;
    if (code && POLICY_MESSAGES[code]) return POLICY_MESSAGES[code](d);
    if (typeof d.message === 'string') return d.message;
    if (code) return humanise(code);
    return 'The request was refused.';
  }
  return String(d);
};

/** Upgrade link carried on a 402 policy denial, or null. */
export const apiUpgradeUrl = (err) => {
  const d = err?.response?.data?.detail;
  if (err?.response?.status !== 402) return null;
  return (d && typeof d === 'object' && d.upgrade_url) || '/pricing';
};

/** {message, upgradeUrl} for places that render an upgrade link next to the message (components/ErrorText.jsx). */
export const apiErrorState = (err, fallback) => ({
  message: apiError(err) || err?.message || fallback,
  upgradeUrl: apiUpgradeUrl(err),
});
