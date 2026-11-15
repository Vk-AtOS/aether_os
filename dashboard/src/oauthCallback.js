// What /auth/callback received from the gateway: an error, an MFA challenge (SSO user with MFA on:
// no token yet, only a short-lived mfa_token to exchange at /auth/mfa/confirm), or a session.
export function parseCallback(params) {
  const err = params.get('error');
  if (err) return { kind: 'error', message: decodeURIComponent(err) };
  if (params.get('mfa_required') === '1' && params.get('mfa_token')) {
    return { kind: 'mfa', mfaToken: params.get('mfa_token') };
  }
  const token = params.get('token');
  if (!token) return { kind: 'error', message: 'No authentication token received.' };
  return { kind: 'session', token, refreshToken: params.get('refresh_token') };
}
