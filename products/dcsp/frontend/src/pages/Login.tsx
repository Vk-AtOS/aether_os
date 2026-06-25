import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Zap, ShieldCheck, GitBranch, Mail, ArrowRight, Eye, EyeOff } from 'lucide-react';
import api from '../lib/api';

type Mode = 'login' | 'signup';

const Login = () => {
  const [mode, setMode] = useState<Mode>('login');
  const [username, setUsername] = useState('');
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw]     = useState(false);
  const [error, setError]       = useState('');
  const [loading, setLoading]   = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    // Pre-flight: verify GitHub App is configured (used to show proper error if not)
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (mode === 'login') {
        await api.post('/auth/login-api', { username, password });
      } else {
        if (password.length < 8) { setError('Password must be at least 8 characters'); setLoading(false); return; }
        await api.post('/auth/signup', { username, email, password });
      }
      navigate('/feed');
    } catch (err: any) {
      const msg = err?.response?.data?.detail || (mode === 'login' ? 'Invalid username or password' : 'Sign-up failed — try a different username or email');
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleGithubOAuth = async () => {
    try {
      const r = await api.get('/github/oauth/start');
      if (r.data?.url) {
        window.location.href = r.data.url;
      } else {
        setError('GitHub OAuth not configured — please contact your administrator.');
      }
    } catch {
      setError('GitHub OAuth unavailable.');
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-4">
      <div className="flex items-center gap-3 mb-8">
        <Zap className="text-accent fill-accent" size={40} />
        <h1 className="text-4xl font-bold text-white tracking-tighter">DCSP</h1>
      </div>

      <div className="w-full max-w-md bg-surface border border-border rounded-lg p-8 shadow-2xl">
        {/* Tab switcher */}
        <div className="flex gap-1 border-b border-border mb-6">
          {(['login', 'signup'] as Mode[]).map(m => (
            <button
              key={m}
              onClick={() => { setMode(m); setError(''); }}
              className={`flex-1 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${
                mode === m ? 'border-accent text-accent' : 'border-transparent text-slate-500 hover:text-white'
              }`}
            >
              {m === 'login' ? 'Sign In' : 'Create Account'}
            </button>
          ))}
        </div>

        <h2 className="text-xl font-semibold text-white mb-6 flex items-center gap-2">
          <ShieldCheck className="text-success" size={20} />
          {mode === 'login' ? 'Welcome back' : 'New account'}
        </h2>

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-sm p-3 rounded-md mb-5">
            {error}
          </div>
        )}

        {/* GitHub OAuth */}
        <button
          onClick={handleGithubOAuth}
          type="button"
          className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 border border-border text-white font-medium py-2.5 px-4 rounded-md transition-colors mb-4"
        >
          <GitBranch size={18} />
          Continue with GitHub
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1 h-px bg-border" />
          <span className="text-xs text-slate-500">or</span>
          <div className="flex-1 h-px bg-border" />
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="w-full bg-background border border-border rounded-md px-4 py-2 text-white focus:ring-2 focus:ring-accent focus:border-transparent transition-all outline-none"
              placeholder={mode === 'login' ? 'admin' : 'yourname'}
              required
            />
          </div>

          {mode === 'signup' && (
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Email</label>
              <div className="relative">
                <Mail size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  className="w-full bg-background border border-border rounded-md pl-9 pr-4 py-2 text-white focus:ring-2 focus:ring-accent focus:border-transparent transition-all outline-none"
                  placeholder="you@example.com"
                  required
                />
              </div>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Password</label>
            <div className="relative">
              <input
                type={showPw ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full bg-background border border-border rounded-md px-4 pr-10 py-2 text-white focus:ring-2 focus:ring-accent focus:border-transparent transition-all outline-none"
                placeholder="••••••••"
                required
              />
              <button type="button" onClick={() => setShowPw(p => !p)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white transition-colors">
                {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-accent hover:bg-accent/90 disabled:opacity-60 text-white font-bold py-2.5 px-4 rounded-md transition-colors mt-2 shadow-lg shadow-accent/10"
          >
            {loading ? 'Please wait…' : mode === 'login' ? (
              <><ShieldCheck size={16} /> Sign In</>
            ) : (
              <><ArrowRight size={16} /> Create Account</>
            )}
          </button>
        </form>

        {mode === 'login' && (
          <div className="mt-6 pt-5 border-t border-border">
            <p className="text-center text-xs text-slate-500">
              Forgot your password? Contact your administrator.
            </p>
          </div>
        )}
      </div>

      <p className="mt-8 text-slate-600 text-xs">
        &copy; 2026 DCSP — Autonomous CI/CD Repair Platform
      </p>
    </div>
  );
};

export default Login;
