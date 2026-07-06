import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { Link } from 'react-router-dom';
import { Shield, Loader2 } from 'lucide-react';

const GoogleIcon = () => (
  <svg className="w-5 h-5" viewBox="0 0 24 24" aria-hidden="true">
    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
  </svg>
);

const GitHubIcon = () => (
  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
  </svg>
);

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [samlAvailable, setSamlAvailable] = useState(false);
  const [mfaToken, setMfaToken] = useState(null);
  const [mfaCode, setMfaCode] = useState('');
  const [ssoOrgInput, setSsoOrgInput] = useState('');
  const [showSsoOrgInput, setShowSsoOrgInput] = useState(false);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  useEffect(() => {
    // Redirect already-authenticated users to dashboard
    if (api.getToken()) {
      navigate('/', { replace: true });
      return;
    }

    const urlError = searchParams.get('error');
    if (urlError) setError(decodeURIComponent(urlError));

    fetch('/api/auth/saml/metadata', { method: 'GET' })
      .then(r => { if (r.ok || r.status === 200) setSamlAvailable(true); })
      .catch(() => {});
  }, []);

  const handleLogin = async (e) => {
    e.preventDefault();

    if (!email.trim() || !password.trim()) {
      setError('Please enter your email and password');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const res = await api.client.post('/auth/login', { email, password });
      const data = res.data;
      if (data.mfa_required) {
        setMfaToken(data.mfa_token);
      } else {
        api.setToken(data.access_token, data.refresh_token);
        navigate('/');
      }
    } catch (err) {
      if (err.response?.status === 401 || err.response?.status === 422) {
        setError('Invalid email or password. Please try again.');
      } else {
        setError(err.response?.data?.detail || 'An unexpected error occurred. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleMfa = async (e) => {
    e.preventDefault();
    if (!mfaCode.trim()) return;

    setLoading(true);
    setError('');
    try {
      const res = await api.client.post('/auth/mfa/confirm', { mfa_token: mfaToken, code: mfaCode });
      api.setToken(res.data.access_token, res.data.refresh_token);
      navigate('/');
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid MFA code. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-accent/10 border border-accent/20 mb-6">
            <Shield className="w-8 h-8 text-accent" />
          </div>
          <h1 className="text-3xl font-bold text-bright tracking-tight">AetherOS Factory</h1>
          <p className="text-muted mt-2 font-medium">Autonomous Software Factory</p>
        </div>

        <div className="panel p-8 shadow-2xl">
          {mfaToken ? (
            <form onSubmit={handleMfa} className="space-y-6">
              <div className="text-center space-y-1">
                <p className="text-bright font-bold">Two-Factor Authentication</p>
                <p className="text-muted text-sm">Enter the 6-digit code from your authenticator app.</p>
              </div>
              <div>
                <label className="block text-xs font-bold text-muted uppercase tracking-wider mb-2">Authenticator Code</label>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ''))}
                  className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-bright focus:outline-none focus:border-accent transition-colors text-center text-2xl tracking-widest font-mono"
                  autoFocus
                  required
                />
              </div>
              {error && (
                <div className="p-3 rounded-lg bg-danger/10 border border-danger/20 text-danger text-sm font-medium">
                  {error}
                </div>
              )}
              <button
                type="submit"
                disabled={loading || mfaCode.length !== 6}
                className="w-full bg-accent hover:bg-accent/90 disabled:opacity-50 text-white font-bold py-3 rounded-lg transition-all flex items-center justify-center"
              >
                {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : 'VERIFY'}
              </button>
              <button
                type="button"
                onClick={() => { setMfaToken(null); setMfaCode(''); setError(''); }}
                className="w-full text-muted hover:text-bright text-sm transition-colors"
              >
                Back to login
              </button>
            </form>
          ) : (
          <>
          <form onSubmit={handleLogin} className="space-y-6">
            <div>
              <label className="block text-xs font-bold text-muted uppercase tracking-wider mb-2">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-bright focus:outline-none focus:border-accent transition-colors"
                required
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-xs font-bold text-muted uppercase tracking-wider">Password</label>
                <Link to="/forgot-password" className="text-xs text-accent hover:underline">Forgot password?</Link>
              </div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-bright focus:outline-none focus:border-accent transition-colors"
                required
              />
            </div>

            {error && (
              <div className="p-3 rounded-lg bg-danger/10 border border-danger/20 text-danger text-sm font-medium">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-accent hover:bg-accent/90 disabled:opacity-50 text-white font-bold py-3 rounded-lg transition-all transform active:scale-[0.98] flex items-center justify-center"
            >
              {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : 'START FACTORY'}
            </button>
          </form>

          <div className="mt-6">
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-border" />
              </div>
              <div className="relative flex justify-center text-xs">
                <span className="bg-panel px-3 text-muted uppercase tracking-widest">or continue with</span>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3">
              <button
                onClick={() => { window.location.href = '/api/auth/oauth/google'; }}
                className="flex items-center justify-center gap-2 border border-border hover:border-accent/50 text-muted hover:text-bright font-semibold py-2.5 rounded-lg transition-all text-sm"
              >
                <GoogleIcon />
                Google
              </button>
              <button
                onClick={() => { window.location.href = '/api/auth/oauth/github'; }}
                className="flex items-center justify-center gap-2 border border-border hover:border-accent/50 text-muted hover:text-bright font-semibold py-2.5 rounded-lg transition-all text-sm"
              >
                <GitHubIcon />
                GitHub
              </button>
            </div>

            {samlAvailable && (
              <div className="mt-3 space-y-2">
                {showSsoOrgInput ? (
                  <div className="space-y-2">
                    <input
                      type="text"
                      placeholder="Your org slug (e.g. acme-corp)"
                      value={ssoOrgInput}
                      onChange={e => setSsoOrgInput(e.target.value)}
                      className="w-full bg-surface border border-border rounded-lg px-4 py-2 text-sm text-bright focus:outline-none focus:border-accent transition-colors"
                      autoFocus
                    />
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        onClick={() => {
                          const slug = ssoOrgInput.trim();
                          const url = slug ? `/api/auth/saml/login?org=${encodeURIComponent(slug)}` : '/api/auth/saml/login';
                          window.location.href = url;
                        }}
                        className="bg-accent hover:bg-accent/90 text-white font-bold py-2 rounded-lg transition-all text-sm"
                      >
                        Continue
                      </button>
                      <button
                        onClick={() => { setShowSsoOrgInput(false); setSsoOrgInput(''); }}
                        className="border border-border hover:border-accent/50 text-muted hover:text-bright font-bold py-2 rounded-lg transition-all text-sm"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowSsoOrgInput(true)}
                    className="w-full border border-border hover:border-accent/50 text-muted hover:text-bright font-bold py-3 rounded-lg transition-all text-sm"
                  >
                    Sign in with SSO (Azure AD / Okta / Google Workspace)
                  </button>
                )}
              </div>
            )}
          </div>
          </>
          )}
        </div>
        
        <p className="text-center text-sm text-muted mt-6">
          Don't have an account?{' '}
          <Link to="/signup" className="text-accent font-semibold hover:underline">Start free trial →</Link>
        </p>
        <p className="text-center text-[10px] text-muted mt-4 uppercase tracking-[0.2em]">
          Powered by VKatOS • Secure Enterprise Mesh
        </p>
        <div className="flex items-center justify-center gap-4 mt-3">
          <a href="/dashboard/legal?doc=tos" target="_blank" rel="noopener noreferrer" className="text-[10px] text-muted hover:text-accent transition-colors uppercase tracking-wider">Terms of Service</a>
          <span className="text-muted/30">·</span>
          <a href="/dashboard/legal?doc=privacy" target="_blank" rel="noopener noreferrer" className="text-[10px] text-muted hover:text-accent transition-colors uppercase tracking-wider">Privacy Policy</a>
          <span className="text-muted/30">·</span>
          <a href="/dashboard/legal?doc=dpa" target="_blank" rel="noopener noreferrer" className="text-[10px] text-muted hover:text-accent transition-colors uppercase tracking-wider">DPA</a>
        </div>
      </div>
    </div>
  );
};

export default Login;
