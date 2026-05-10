import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { User, Key, Lock, Copy, CheckCircle2, Eye, EyeOff } from 'lucide-react';

const Profile = () => {
  const [userData, setUserData] = useState(null);
  const [apiKeys, setApiKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pwForm, setPwForm] = useState({ current: '', next: '', confirm: '' });
  const [pwStatus, setPwStatus] = useState(null); // null | 'saving' | 'ok' | 'error'
  const [pwError, setPwError] = useState('');
  const [copied, setCopied] = useState({});
  const [showPw, setShowPw] = useState({});

  useEffect(() => {
    const load = async () => {
      try {
        // Decode JWT from localStorage for basic profile info
        const token = api.getToken();
        if (token) {
          const parts = token.split('.');
          if (parts.length === 3) {
            const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
            setUserData(payload);
          }
        }
        const usageRes = await api.client.get('/account/usage');
        setUserData(prev => ({ ...prev, ...(usageRes.data ?? {}) }));
        const keysRes = await api.client.get('/settings/api-keys');
        setApiKeys(keysRes.data ? Object.entries(keysRes.data).map(([k, v]) => ({ provider: k, key: v })) : []);
      } catch {
        // non-fatal
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const handleCopy = (text, id) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(prev => ({ ...prev, [id]: true }));
      setTimeout(() => setCopied(prev => ({ ...prev, [id]: false })), 2000);
    });
  };

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    setPwError('');
    if (pwForm.next !== pwForm.confirm) {
      setPwError('New passwords do not match.');
      return;
    }
    if (pwForm.next.length < 10) {
      setPwError('Password must be at least 10 characters.');
      return;
    }
    setPwStatus('saving');
    try {
      await api.client.post('/auth/change-password', {
        current_password: pwForm.current,
        new_password: pwForm.next,
      });
      setPwStatus('ok');
      setPwForm({ current: '', next: '', confirm: '' });
      setTimeout(() => setPwStatus(null), 3000);
    } catch (err) {
      setPwStatus('error');
      setPwError(err.response?.data?.detail || 'Failed to change password.');
    }
  };

  if (loading) return (
    <div className="p-8 flex items-center justify-center">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
    </div>
  );

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-bright">Profile</h1>
        <p className="text-muted mt-1">Manage your account details and security settings.</p>
      </header>

      {/* Account info */}
      <section className="panel overflow-hidden">
        <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
          <User className="w-4 h-4 mr-2 text-accent" />
          <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Account Details</h3>
        </div>
        <div className="p-6 space-y-4">
          {[
            { label: 'Email', value: userData?.sub ?? '—' },
            { label: 'Role', value: userData?.role ?? '—' },
            { label: 'Plan', value: userData?.plan ?? '—' },
            { label: 'Org ID', value: userData?.org_id ?? '—' },
            userData?.plan === 'trial' && { label: 'Trial Runs Used', value: `${userData?.runs_used ?? 0} / ${userData?.runs_limit ?? 3}` },
          ].filter(Boolean).map(({ label, value }) => (
            <div key={label} className="flex justify-between items-center py-2 border-b border-border/30 last:border-0">
              <span className="text-xs font-bold text-muted uppercase tracking-wider">{label}</span>
              <span className="text-sm font-mono text-bright">{value}</span>
            </div>
          ))}
        </div>
      </section>

      {/* API Keys */}
      <section className="panel overflow-hidden">
        <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
          <Key className="w-4 h-4 mr-2 text-accent" />
          <h3 className="text-xs font-bold text-muted uppercase tracking-widest">API Keys</h3>
        </div>
        <div className="p-6 space-y-3">
          {apiKeys.length === 0 ? (
            <p className="text-muted text-sm">No API keys configured.</p>
          ) : apiKeys.map(({ provider, key }) => (
            <div key={provider} className="flex items-center justify-between p-3 bg-surface rounded-lg border border-border">
              <div>
                <div className="text-xs font-bold text-muted uppercase">{provider}</div>
                <div className="font-mono text-xs text-bright mt-1">
                  {showPw[provider] ? key : key.slice(0, 8) + '••••••••'}
                </div>
              </div>
              <div className="flex items-center space-x-2">
                <button onClick={() => setShowPw(p => ({ ...p, [provider]: !p[provider] }))} className="text-muted hover:text-bright transition-colors">
                  {showPw[provider] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
                <button onClick={() => handleCopy(key, provider)} className="text-muted hover:text-bright transition-colors">
                  {copied[provider] ? <CheckCircle2 className="w-4 h-4 text-success" /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Change password */}
      <section className="panel overflow-hidden">
        <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
          <Lock className="w-4 h-4 mr-2 text-accent" />
          <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Change Password</h3>
        </div>
        <form onSubmit={handlePasswordChange} className="p-6 space-y-4">
          {['current', 'next', 'confirm'].map((field) => (
            <div key={field}>
              <label className="block text-xs font-bold text-muted uppercase tracking-wider mb-1">
                {field === 'current' ? 'Current Password' : field === 'next' ? 'New Password' : 'Confirm New Password'}
              </label>
              <input
                type="password"
                value={pwForm[field]}
                onChange={e => setPwForm(p => ({ ...p, [field]: e.target.value }))}
                className="w-full bg-surface border border-border rounded-lg px-4 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                required
              />
            </div>
          ))}
          {pwError && <p className="text-xs text-danger">{pwError}</p>}
          <button
            type="submit"
            disabled={pwStatus === 'saving'}
            className="bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold px-6 py-2 rounded-lg transition-colors uppercase tracking-wider"
          >
            {pwStatus === 'saving' ? 'Saving…' : pwStatus === 'ok' ? '✓ Changed' : 'Change Password'}
          </button>
        </form>
      </section>
    </div>
  );
};

export default Profile;
