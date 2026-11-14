import React, { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { apiError } from '../apiError';
import { Shield, Loader2, CheckCircle } from 'lucide-react';

const ResetPassword = () => {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (pw.length < 8) return setError('Use at least 8 characters.');
    if (pw !== pw2) return setError('The two passwords do not match.');
    setLoading(true);
    setError('');
    try {
      await api.client.post('/auth/password-reset-confirm', { token, new_password: pw });
      setDone(true);
    } catch (err) {
      setError(apiError(err) || 'This reset link is invalid or has expired. Request a new one.');
    } finally {
      setLoading(false);
    }
  };

  const input = 'w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-bright focus:outline-none focus:border-accent transition-colors';
  return (
    <div className="min-h-screen flex items-center justify-center bg-surface p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-accent/10 border border-accent/20 mb-6"><Shield className="w-8 h-8 text-accent" /></div>
          <h1 className="text-3xl font-bold text-bright tracking-tight">AetherOS Factory</h1>
          <p className="text-muted mt-2 font-medium">Choose a new password</p>
        </div>
        <div className="panel p-8 shadow-2xl">
          {done ? (
            <div className="text-center space-y-4">
              <CheckCircle className="w-12 h-12 text-accent mx-auto" />
              <p className="text-bright font-bold">Password changed</p>
              <p className="text-muted text-sm">All your other sessions were signed out. Sign in with the new password.</p>
              <Link to="/login" className="block mt-4 text-accent font-semibold hover:underline text-sm">Go to login</Link>
            </div>
          ) : !token ? (
            <div className="text-center space-y-4">
              <p role="alert" className="text-danger text-sm">This link has no reset token.</p>
              <Link to="/forgot-password" className="block text-accent font-semibold hover:underline text-sm">Request a new link</Link>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-5">
              <label className="block"><span className="block text-xs font-bold text-muted uppercase tracking-wider mb-2">New password</span>
                <input type="password" autoComplete="new-password" aria-label="New password" className={input} value={pw} onChange={(e) => setPw(e.target.value)} required autoFocus /></label>
              <label className="block"><span className="block text-xs font-bold text-muted uppercase tracking-wider mb-2">Repeat password</span>
                <input type="password" autoComplete="new-password" aria-label="Repeat password" className={input} value={pw2} onChange={(e) => setPw2(e.target.value)} required /></label>
              {error && <div role="alert" className="p-3 rounded-lg bg-danger/10 border border-danger/20 text-danger text-sm font-medium">{error}</div>}
              <button type="submit" disabled={loading} className="w-full bg-accent hover:bg-accent/90 disabled:opacity-50 text-white font-bold py-3 rounded-lg transition-all flex items-center justify-center">
                {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : 'SET NEW PASSWORD'}
              </button>
              <Link to="/login" className="block text-center text-muted hover:text-bright text-sm transition-colors">Back to login</Link>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default ResetPassword;
