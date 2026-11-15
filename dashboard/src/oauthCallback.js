// What /auth/callback received from the gateway: an error, or a one-time code (never a token: URLs are logged).
// The page trades the code once at POST /auth/oauth/exchange, which answers {kind: 'session', token} or, for an SSO
// user with MFA on, {kind: 'mfa', mfa_token} (no token yet, only a short-lived challenge for /auth/mfa/confirm).
export function parseCallback(params) {
  const err = params.get('error');
  if (err) return { kind: 'error', message: decodeURIComponent(err) };
  const code = params.get('code');
  if (!code) return { kind: 'error', message: 'No sign-in code received.' };
  return { kind: 'code', code };
}

export const fromExchange = (data) => {
  if (data?.kind === 'mfa' && data.mfa_token) return { kind: 'mfa', mfaToken: data.mfa_token };
  if (data?.kind === 'session' && data.token) return { kind: 'session', token: data.token, refreshToken: data.refresh_token || null };
  return { kind: 'error', message: 'The sign-in could not be completed.' };
};
