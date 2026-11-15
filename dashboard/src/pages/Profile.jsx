import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { appPath } from '../appUrl';
import { User, Key, Lock, Copy, CheckCircle2, Eye, EyeOff, ShieldCheck, QrCode, Trash2, AlertTriangle } from 'lucide-react';
import { PageLoader } from '../components/PageLoader';
import { apiError } from '../apiError';
import NotificationPrefs from '../components/settings/NotificationPrefs';

const Profile = () => {
  const [userData, setUserData] = useState(null);
  const [apiKeys, setApiKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pwForm, setPwForm] = useState({ current: '', next: '', confirm: '' });
  const [pwStatus, setPwStatus] = useState(null); // null | 'saving' | 'ok' | 'error'
  const [pwError, setPwError] = useState('');
  const [exportError, setExportError] = useState('');
  const [copied, setCopied] = useState({});
  const [showPw, setShowPw] = useState({});
  // MFA state
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [mfaSetup, setMfaSetup] = useState(null); // { secret, provisioning_uri }
  const [mfaCode, setMfaCode] = useState('');
  const [mfaStatus, setMfaStatus] = useState(null); // null | 'loading' | 'verifying' | 'ok' | 'error' | 'disabling'
  const [mfaError, setMfaError] = useState('');
  const [eraseConfirm, setEraseConfirm] = useState('');
  const [erasing, setErasing] = useState(false);
  const [eraseError, setEraseError] = useState('');
  const [exporting, setExporting] = useState(false);

  const handleExportData = async () => {
    setExporting(true);
    setExportError('');
    try {
      const res = await api.client.get('/account/data-export', { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'aetheros-data-export.json';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError('Export failed: ' + (apiError(e) || e.message));
    } finally {
      setExporting(false);
    }
  };

  const handleEraseAccount = async () => {
    if (eraseConfirm !== 'DELETE') return;
    setErasing(true);
    setEraseError('');
    try {
      await api.client.delete('/account');
      api.clearToken();
      window.location.href = appPath('/login');
    } catch (e) {
      setEraseError(apiError(e) || 'Erasure failed. Please try again.');
      setErasing(false);
    }
  };

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
        const _nonKeyFields = new Set(['primary_llm', 'ollama_model', 'org_keys', 'ollama_timeout', 'openrouter_timeout']);
        setApiKeys(keysRes.data
          ? Object.entries(keysRes.data)
              .filter(([k, v]) => !_nonKeyFields.has(k) && typeof v === 'string' && v.length > 0)
              .map(([k, v]) => ({ provider: k, key: String(v) }))
          : []);
        // Fetch MFA status from dedicated endpoint
        try {
          const mfaRes = await api.client.get('/auth/mfa/status');
          if (mfaRes.data?.enabled !== undefined) {
            setMfaEnabled(!!mfaRes.data.enabled);
          }
        } catch {
          // MFA status endpoint may not exist — keep default false
        }
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
      setPwError(apiError(err) || 'Failed to change password.');
    }
  };

  const handleMfaSetup = async () => {
    setMfaStatus('loading');
    setMfaError('');
    try {
      const res = await api.client.post('/auth/mfa/setup');
      setMfaSetup(res.data);
      setMfaStatus(null);
    } catch (err) {
      setMfaError(apiError(err) || 'Failed to initiate MFA setup.');
      setMfaStatus('error');
    }
  };

  const handleMfaVerify = async (e) => {
    e.preventDefault();
    setMfaStatus('verifying');
    setMfaError('');
    try {
      await api.client.post('/auth/mfa/verify-setup', { code: mfaCode });
      setMfaEnabled(true);
      setMfaSetup(null);
      setMfaCode('');
      setMfaStatus('ok');
      setTimeout(() => setMfaStatus(null), 3000);
    } catch (err) {
      setMfaError(apiError(err) || 'Invalid code. Try again.');
      setMfaStatus('error');
    }
  };

  const handleMfaDisable = async (e) => {
    e.preventDefault();
    setMfaStatus('disabling');
    setMfaError('');
    try {
      await api.client.post('/auth/mfa/disable', { code: mfaCode });
      setMfaEnabled(false);
      setMfaCode('');
      setMfaStatus(null);
    } catch (err) {
      setMfaError(apiError(err) || 'Invalid code. Try again.');
      setMfaStatus('error');
    }
  };

  if (loading) return (
    <div className="p-6 max-w-3xl mx-auto">
      <PageLoader />
    </div>
  );

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-bright">Profile</h1>
        <p className="text-muted mt-1">Manage your account details and security settings.</p>
      </header>

      {/* Account info */}
      <NotificationPrefs />

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
                  {showPw[provider] ? key : String(key ?? '').slice(0, 8) + '••••••••'}
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

      {/* MFA Setup */}
      <section className="panel overflow-hidden">
        <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center">
            <ShieldCheck className="w-4 h-4 mr-2 text-accent" />
            <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Two-Factor Authentication</h3>
          </div>
          {mfaEnabled && (
            <span className="text-[10px] font-bold bg-success/20 text-success border border-success/30 px-2 py-0.5 rounded uppercase tracking-wider">Enabled</span>
          )}
        </div>
        <div className="p-6 space-y-4">
          {mfaStatus === 'ok' && <p className="text-xs text-success font-medium">MFA {mfaEnabled ? 'enabled' : 'disabled'} successfully.</p>}
          {mfaError && <p className="text-xs text-danger">{mfaError}</p>}

          {!mfaEnabled && !mfaSetup && (
            <div className="space-y-3">
              <p className="text-xs text-muted">Protect your account with a time-based one-time password (TOTP) authenticator app such as Google Authenticator or Authy.</p>
              <button
                onClick={handleMfaSetup}
                disabled={mfaStatus === 'loading'}
                className="bg-accent/20 text-accent border border-accent/30 hover:bg-accent/30 disabled:opacity-50 text-xs font-bold px-4 py-2 rounded-lg transition-colors uppercase tracking-wider"
              >
                {mfaStatus === 'loading' ? 'Loading…' : 'Set Up MFA'}
              </button>
            </div>
          )}

          {mfaSetup && !mfaEnabled && (
            <div className="space-y-4">
              <div className="p-4 bg-surface border border-border rounded-lg space-y-3">
                <div className="flex items-center gap-2">
                  <QrCode className="w-4 h-4 text-accent shrink-0" />
                  <p className="text-xs font-bold text-muted uppercase tracking-wider">1. Add to your authenticator app</p>
                </div>
                {/* Mobile tap-to-open link */}
                <a
                  href={mfaSetup.provisioning_uri}
                  className="flex items-center gap-2 w-full px-4 py-3 bg-accent/10 border border-accent/30 rounded-lg text-sm font-bold text-accent hover:bg-accent/20 transition-colors justify-center"
                >
                  <QrCode className="w-4 h-4" />
                  Tap to Open in Authenticator App
                </a>
                <p className="text-[10px] text-muted text-center">On mobile: tap the link above to open your authenticator app directly.</p>
                <p className="text-[10px] text-muted text-center">On desktop: copy the URI below and paste it into your authenticator.</p>
                <div className="relative">
                  <div className="font-mono text-[10px] text-accent break-all bg-panel px-3 py-2 rounded border border-border pr-16">{mfaSetup.provisioning_uri}</div>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard?.writeText(mfaSetup.provisioning_uri)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-muted hover:text-bright border border-border rounded px-2 py-0.5 bg-panel"
                  >
                    Copy
                  </button>
                </div>
                <p className="text-xs font-bold text-muted uppercase tracking-wider">Or enter this secret key manually:</p>
                <div className="font-mono text-sm text-bright bg-panel px-3 py-2 rounded border border-border tracking-widest">{mfaSetup.secret}</div>
              </div>
              <form onSubmit={handleMfaVerify} className="space-y-3">
                <p className="text-xs font-bold text-muted uppercase tracking-wider">2. Enter the 6-digit code from your app to confirm</p>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  value={mfaCode}
                  onChange={e => setMfaCode(e.target.value.replace(/\D/g, ''))}
                  placeholder="000000"
                  className="w-32 bg-surface border border-border rounded-lg px-4 py-2 text-bright text-center text-xl font-mono tracking-widest focus:outline-none focus:border-accent"
                  autoFocus
                />
                <div className="flex gap-3">
                  <button
                    type="submit"
                    disabled={mfaCode.length !== 6 || mfaStatus === 'verifying'}
                    className="bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors uppercase tracking-wider"
                  >
                    {mfaStatus === 'verifying' ? 'Verifying…' : 'Confirm & Enable MFA'}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setMfaSetup(null); setMfaCode(''); setMfaError(''); }}
                    className="text-muted hover:text-bright text-xs transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}

          {mfaEnabled && (
            <form onSubmit={handleMfaDisable} className="space-y-3">
              <p className="text-xs text-muted">To disable MFA, enter a code from your authenticator app.</p>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={mfaCode}
                onChange={e => setMfaCode(e.target.value.replace(/\D/g, ''))}
                placeholder="000000"
                className="w-32 bg-surface border border-border rounded-lg px-4 py-2 text-bright text-center text-xl font-mono tracking-widest focus:outline-none focus:border-accent"
              />
              <button
                type="submit"
                disabled={mfaCode.length !== 6 || mfaStatus === 'disabling'}
                className="bg-danger/20 text-danger border border-danger/30 hover:bg-danger/30 disabled:opacity-50 text-xs font-bold px-4 py-2 rounded-lg transition-colors uppercase tracking-wider"
              >
                {mfaStatus === 'disabling' ? 'Disabling…' : 'Disable MFA'}
              </button>
            </form>
          )}
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
      {/* GDPR — Data & Account Erasure */}
      <section className="panel overflow-hidden border-danger/30">
        <div className="bg-danger/10 px-6 py-4 border-b border-danger/20 flex items-center">
          <AlertTriangle className="w-4 h-4 mr-2 text-danger" />
          <h3 className="text-xs font-bold text-danger uppercase tracking-widest">Data &amp; Privacy</h3>
        </div>
        <div className="p-6 space-y-5">
          <div className="flex items-start gap-4">
            <div className="flex-1">
              <p className="text-sm font-semibold text-bright">Download your data</p>
              <p className="text-xs text-muted mt-0.5">Export all your account data as a machine-readable JSON file (GDPR Art. 20 — right to portability).</p>
              {exportError && <p className="text-red-400 text-xs mt-1">{exportError}</p>}
            </div>
            <button
              onClick={handleExportData}
              disabled={exporting}
              className="shrink-0 text-xs font-bold px-4 py-2 rounded-lg border border-accent text-accent hover:bg-accent/10 disabled:opacity-50 transition-colors uppercase tracking-wider"
            >
              {exporting ? 'Exporting…' : 'Export Data'}
            </button>
          </div>

          <div className="flex gap-4">
            <a href={appPath('/legal?doc=privacy')} target="_blank" rel="noopener noreferrer" className="text-xs text-accent hover:underline">Privacy Policy ↗</a>
            <a href={appPath('/legal?doc=tos')} target="_blank" rel="noopener noreferrer" className="text-xs text-accent hover:underline">Terms of Service ↗</a>
            <a href={appPath('/legal?doc=dpa')} target="_blank" rel="noopener noreferrer" className="text-xs text-accent hover:underline">DPA ↗</a>
          </div>

          <div className="border-t border-border/50 pt-5 space-y-3">
            <p className="text-sm font-semibold text-danger flex items-center gap-2">
              <Trash2 className="w-4 h-4" /> Delete Account (GDPR Erasure)
            </p>
            <p className="text-xs text-muted">
              Permanently anonymises your account and deletes all associated runs and artifacts. This cannot be undone.
              Type <strong className="text-bright font-mono">DELETE</strong> to confirm.
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={eraseConfirm}
                onChange={e => setEraseConfirm(e.target.value)}
                placeholder="Type DELETE to confirm"
                className="flex-1 bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright font-mono focus:outline-none focus:border-danger"
              />
              <button
                onClick={handleEraseAccount}
                disabled={eraseConfirm !== 'DELETE' || erasing}
                className="shrink-0 bg-danger hover:bg-danger/90 disabled:opacity-40 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors uppercase tracking-wider"
              >
                {erasing ? 'Erasing…' : 'Erase Account'}
              </button>
            </div>
            {eraseError && <p className="text-xs text-danger">{eraseError}</p>}
          </div>
        </div>
      </section>
    </div>
  );
};

export default Profile;
