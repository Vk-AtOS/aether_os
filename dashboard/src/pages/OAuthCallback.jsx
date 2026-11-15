import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { parseCallback } from '../oauthCallback';
import { Loader2, AlertTriangle } from 'lucide-react';

const OAuthCallback = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const result = parseCallback(searchParams);
  const error = result.kind === 'error' ? result.message : '';

  useEffect(() => {
    if (result.kind === 'mfa') {
      // Hand the challenge to the login page's code step (route state keeps it out of history/URL).
      navigate('/login', { replace: true, state: { mfaToken: result.mfaToken } });
    } else if (result.kind === 'session') {
      api.setToken(result.token, result.refreshToken);
      navigate('/', { replace: true });
    }
  }, [result.kind, result.mfaToken, result.token, result.refreshToken, navigate]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface p-4">
        <div className="w-full max-w-md panel p-8 text-center space-y-4">
          <AlertTriangle className="w-12 h-12 text-danger mx-auto" />
          <h2 className="text-xl font-bold text-bright">Sign-in Failed</h2>
          <p className="text-muted text-sm">{error}</p>
          <button
            onClick={() => navigate('/login', { replace: true })}
            className="mt-4 bg-accent hover:bg-accent/90 text-white font-bold px-6 py-2 rounded-lg transition-colors"
          >
            Back to Login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface">
      <div className="text-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin text-accent mx-auto" />
        <p className="text-muted font-medium">Completing sign-in…</p>
      </div>
    </div>
  );
};

export default OAuthCallback;
