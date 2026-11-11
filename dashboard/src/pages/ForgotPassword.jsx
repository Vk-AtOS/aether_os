import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { Shield, Loader2, CheckCircle } from 'lucide-react';

const ForgotPassword = () => {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email.trim()) {
      setError('Please enter your email address');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await api.client.post('/auth/password-reset-request', { email: email.trim() });
      setSubmitted(true);
    } catch {
      // Always show success to prevent email enumeration
      setSubmitted(true);
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
          <p className="text-muted mt-2 font-medium">Reset your password</p>
        </div>

        <div className="panel p-8 shadow-2xl">
          {submitted ? (
            <div className="text-center space-y-4">
              <CheckCircle className="w-12 h-12 text-accent mx-auto" />
              <p className="text-bright font-bold">Check your inbox</p>
              <p className="text-muted text-sm">
                If an account exists for <strong>{email}</strong>, you will receive a password
                reset link shortly. The link expires in 1 hour.
              </p>
              <Link
                to="/login"
                className="block mt-4 text-accent font-semibold hover:underline text-sm"
              >
                Back to login
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-6">
              <div>
                <p className="text-muted text-sm mb-4">
                  Enter the email address for your account and we will send you a password reset link.
                </p>
                <label className="block text-xs font-bold text-muted uppercase tracking-wider mb-2">
                  Email address
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-bright focus:outline-none focus:border-accent transition-colors"
                  placeholder="you@example.com"
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
                disabled={loading}
                className="w-full bg-accent hover:bg-accent/90 disabled:opacity-50 text-white font-bold py-3 rounded-lg transition-all flex items-center justify-center"
              >
                {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : 'SEND RESET LINK'}
              </button>

              <Link
                to="/login"
                className="block text-center text-muted hover:text-bright text-sm transition-colors"
              >
                Back to login
              </Link>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default ForgotPassword;
