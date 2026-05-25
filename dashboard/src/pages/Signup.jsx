import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { api } from '../api';
import { Loader2, Eye, EyeOff, CheckCircle2, Rocket } from 'lucide-react';

const HexLogo = () => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
    <polygon points="20,3 36,12 36,28 20,37 4,28 4,12" fill="none" stroke="#6366f1" strokeWidth="2" />
    <polygon points="20,10 29,15 29,25 20,30 11,25 11,15" fill="#6366f1" opacity="0.2" />
    <circle cx="20" cy="20" r="4.5" fill="#6366f1" />
  </svg>
);

const Field = ({ label, required, children, hint }) => (
  <div className="space-y-1.5">
    <label className="block text-xs font-bold text-muted uppercase tracking-wider">
      {label} {required && <span className="text-danger">*</span>}
    </label>
    {children}
    {hint && <p className="text-[10px] text-muted/60">{hint}</p>}
  </div>
);

const Signup = () => {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    email: '', org_name: '', password: '', confirm: '',
    terms_accepted: false, dpa_accepted: false,
  });
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));

  const pwStrength = (() => {
    const p = form.password;
    if (!p) return null;
    let score = 0;
    if (p.length >= 10) score++;
    if (/[A-Z]/.test(p)) score++;
    if (/[0-9]/.test(p)) score++;
    if (/[^A-Za-z0-9]/.test(p)) score++;
    return score;
  })();

  const pwColor = ['bg-red-500', 'bg-orange-400', 'bg-yellow-400', 'bg-emerald-400'][Math.min((pwStrength || 1) - 1, 3)];

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.password !== form.confirm) { setError('Passwords do not match.'); return; }
    if (form.password.length < 10) { setError('Password must be at least 10 characters.'); return; }
    if (!form.terms_accepted) { setError('You must accept the Terms of Service.'); return; }
    if (!form.dpa_accepted) { setError('You must accept the Data Processing Agreement.'); return; }
    setLoading(true);
    try {
      const res = await api.client.post('/auth/register', {
        email: form.email.trim(),
        password: form.password,
        org_name: form.org_name.trim() || undefined,
        terms_accepted: true,
        dpa_accepted: true,
      });
      api.setToken(res.data.access_token);
      if (res.data.refresh_token) {
        localStorage.setItem('aether_refresh_token', res.data.refresh_token);
      }
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8 space-y-3">
          <HexLogo />
          <div className="text-center">
            <h1 className="text-2xl font-bold text-bright tracking-tight">Create your account</h1>
            <p className="text-sm text-muted mt-1">Start with 3 free factory runs — no card required</p>
          </div>
        </div>

        {/* Trial callout */}
        <div className="bg-accent/10 border border-accent/30 rounded-xl p-3 mb-6 flex items-start gap-2.5">
          <Rocket className="w-4 h-4 text-accent mt-0.5 shrink-0" />
          <div className="text-xs text-bright/90">
            <span className="font-bold text-accent">Free Trial</span> — 3 complete factory runs, all 12 phases, no credit card needed.
            {' '}<Link to="/pricing" className="text-accent underline underline-offset-2">See all plans →</Link>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="bg-panel border border-border rounded-2xl p-8 space-y-5 shadow-xl">
          <Field label="Work email" required>
            <input type="email" value={form.email} onChange={set('email')} required
              placeholder="you@company.com" autoComplete="email"
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-bright placeholder-muted text-sm focus:outline-none focus:border-accent transition-colors" />
          </Field>

          <Field label="Organisation name" hint="Your company or team name — can be changed later">
            <input type="text" value={form.org_name} onChange={set('org_name')}
              placeholder="Acme Corp"
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-bright placeholder-muted text-sm focus:outline-none focus:border-accent transition-colors" />
          </Field>

          <Field label="Password" required hint="Minimum 10 characters">
            <div className="relative">
              <input type={showPw ? 'text' : 'password'} value={form.password} onChange={set('password')} required
                placeholder="Choose a strong password" autoComplete="new-password"
                className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 pr-10 text-bright placeholder-muted text-sm focus:outline-none focus:border-accent transition-colors" />
              <button type="button" onClick={() => setShowPw(v => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-bright">
                {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {form.password && (
              <div className="flex gap-1 mt-1.5">
                {[1,2,3,4].map(i => (
                  <div key={i} className={`h-1 flex-1 rounded-full transition-colors ${(pwStrength || 0) >= i ? pwColor : 'bg-border'}`} />
                ))}
              </div>
            )}
          </Field>

          <Field label="Confirm password" required>
            <input type="password" value={form.confirm} onChange={set('confirm')} required
              placeholder="Repeat your password" autoComplete="new-password"
              className={`w-full bg-surface border rounded-lg px-4 py-2.5 text-bright placeholder-muted text-sm focus:outline-none transition-colors ${
                form.confirm && form.confirm !== form.password ? 'border-danger' : 'border-border focus:border-accent'
              }`} />
            {form.confirm && form.confirm !== form.password && (
              <p className="text-xs text-danger mt-1">Passwords do not match</p>
            )}
          </Field>

          {/* Legal checkboxes */}
          <div className="space-y-3 pt-1">
            {[
              { key: 'terms_accepted', doc: 'tos', linkText: 'Terms of Service', suffix: '' },
              { key: 'dpa_accepted',   doc: 'dpa', linkText: 'Data Processing Agreement', suffix: ' (GDPR Art. 28)' },
            ].map(({ key, doc, linkText, suffix }) => (
              <div key={key} className="flex items-start gap-3">
                <button type="button"
                  onClick={() => setForm(f => ({ ...f, [key]: !f[key] }))}
                  aria-checked={form[key]}
                  role="checkbox"
                  className={`w-4 h-4 mt-0.5 rounded border flex-shrink-0 flex items-center justify-center transition-colors ${
                    form[key] ? 'bg-accent border-accent' : 'border-border hover:border-accent/60'
                  }`}>
                  {form[key] && <CheckCircle2 className="w-3 h-3 text-white" />}
                </button>
                <span className="text-xs text-muted">
                  I accept the{' '}
                  <a href={`/legal?doc=${doc}`} target="_blank" rel="noopener noreferrer"
                    className="text-accent underline underline-offset-2">{linkText}</a>
                  {suffix}
                </span>
              </div>
            ))}
          </div>

          {error && (
            <div className="bg-danger/10 border border-danger/30 rounded-lg p-3 text-sm text-danger">{error}</div>
          )}

          <button type="submit" disabled={loading}
            className="w-full bg-accent hover:bg-accent/90 disabled:opacity-50 text-white font-bold py-3 rounded-lg transition-all flex items-center justify-center gap-2">
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Rocket className="w-4 h-4" />}
            {loading ? 'Creating account…' : 'Start Free Trial'}
          </button>

          <p className="text-center text-xs text-muted">
            Already have an account?{' '}
            <Link to="/login" className="text-accent hover:underline font-semibold">Sign in</Link>
          </p>
        </form>

        <p className="text-center text-[10px] text-muted/50 mt-6 uppercase tracking-[0.15em]">
          Powered by VKatOS · Secure Enterprise AI
        </p>
      </div>
    </div>
  );
};

export default Signup;
