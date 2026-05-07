import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { Shield, Loader2 } from 'lucide-react';

const Login = () => {
  const [email, setEmail] = useState('verify@test.com');
  const [password, setPassword] = useState('Dom@0104!');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    
    if (!email.trim() || !password.trim()) {
      setError('Please enter your email and password');
      return;
    }

    setLoading(true);
    setError('');
    try {
      await api.login(email, password);
      navigate('/');
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
              <label className="block text-xs font-bold text-muted uppercase tracking-wider mb-2">Password</label>
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
        </div>
        
        <p className="text-center text-[10px] text-muted mt-8 uppercase tracking-[0.2em]">
          Powered by VKatOS • Secure Enterprise Mesh
        </p>
      </div>
    </div>
  );
};

export default Login;
