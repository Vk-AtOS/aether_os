import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { api } from '../api';
import { CheckCircle2, Zap, Building2, Rocket, Loader2, Star } from 'lucide-react';

const PLAN_ICONS = { trial: Rocket, pro: Zap, enterprise: Building2 };

const loadRazorpay = () =>
  new Promise((resolve) => {
    if (window.Razorpay) { resolve(true); return; }
    const s = document.createElement('script');
    s.src = 'https://checkout.razorpay.com/v1/checkout.js';
    s.onload  = () => resolve(true);
    s.onerror = () => resolve(false);
    document.body.appendChild(s);
  });

const PlanCard = ({ plan, current, onUpgrade, upgrading }) => {
  const Icon = PLAN_ICONS[plan.id] || Rocket;
  const isCurrent = current === plan.id;
  const isHighlight = plan.highlight;
  const isEnterprise = plan.id === 'enterprise';

  return (
    <div className={`relative flex flex-col bg-panel border rounded-2xl overflow-hidden transition-all ${
      isHighlight
        ? 'border-accent shadow-lg shadow-accent/20 scale-[1.02]'
        : 'border-border hover:border-accent/40'
    }`}>
      {isHighlight && (
        <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500" />
      )}
      {isHighlight && (
        <div className="absolute top-3 right-4 flex items-center gap-1 bg-accent/20 border border-accent/40 rounded-full px-2 py-0.5">
          <Star className="w-2.5 h-2.5 text-accent" />
          <span className="text-[9px] font-bold text-accent uppercase tracking-wider">Most Popular</span>
        </div>
      )}

      <div className="p-6 border-b border-border">
        <div className="flex items-center gap-2 mb-3">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${isHighlight ? 'bg-accent/20' : 'bg-surface'}`}>
            <Icon className={`w-4 h-4 ${isHighlight ? 'text-accent' : 'text-muted'}`} />
          </div>
          <span className="font-bold text-bright text-lg">{plan.name}</span>
        </div>

        <div className="flex items-end gap-1 mb-1">
          {plan.price_inr === 0 ? (
            <span className="text-3xl font-bold text-bright">Free</span>
          ) : (
            <>
              <span className="text-sm font-bold text-muted self-start mt-1">₹</span>
              <span className="text-3xl font-bold text-bright">{plan.price_inr.toLocaleString('en-IN')}</span>
              <span className="text-sm text-muted mb-1">/{plan.period}</span>
            </>
          )}
        </div>
        {plan.price_inr > 0 && (
          <p className="text-[10px] text-muted">Billed monthly · Cancel any time</p>
        )}
      </div>

      <ul className="p-6 space-y-2.5 flex-1">
        {plan.features.map((f, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-bright/80">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />
            {f}
          </li>
        ))}
      </ul>

      <div className="p-6 pt-0">
        {isCurrent ? (
          <div className="w-full py-2.5 rounded-lg bg-surface border border-border text-center text-sm font-bold text-muted">
            Current plan
          </div>
        ) : isEnterprise ? (
          <a href="mailto:sales@aetheros.ai?subject=Enterprise%20Enquiry"
            className="block w-full py-2.5 rounded-lg border border-border hover:border-accent/50 text-center text-sm font-bold text-muted hover:text-bright transition-colors">
            Contact Sales
          </a>
        ) : plan.id === 'trial' ? (
          <Link to="/signup"
            className="block w-full py-2.5 rounded-lg bg-surface border border-border hover:border-accent/50 text-center text-sm font-bold text-muted hover:text-bright transition-colors">
            {plan.cta}
          </Link>
        ) : (
          <button onClick={() => onUpgrade(plan.id)} disabled={upgrading === plan.id}
            className={`w-full py-2.5 rounded-lg text-sm font-bold transition-all flex items-center justify-center gap-2 ${
              isHighlight
                ? 'bg-accent hover:bg-accent/90 text-white'
                : 'bg-surface border border-border hover:border-accent text-bright'
            } disabled:opacity-50`}>
            {upgrading === plan.id ? <Loader2 className="w-4 h-4 animate-spin" /> : plan.cta}
          </button>
        )}
      </div>
    </div>
  );
};

const Pricing = () => {
  const navigate = useNavigate();
  const [plans, setPlans] = useState([]);
  const [current, setCurrent] = useState('trial');
  const [upgrading, setUpgrading] = useState('');
  const [success, setSuccess] = useState('');
  const [error, setError] = useState('');
  const isLoggedIn = !!api.getToken();

  useEffect(() => {
    api.client.get('/billing/plans').then(r => setPlans(r.data.plans || [])).catch(() => {});
    if (isLoggedIn) {
      api.client.get('/account/usage').then(r => setCurrent(r.data.plan || 'trial')).catch(() => {});
    }
  }, []);

  const handleUpgrade = async (planId) => {
    if (!isLoggedIn) { navigate('/signup'); return; }
    const loaded = await loadRazorpay();
    if (!loaded) { setError('Payment gateway failed to load. Check your internet connection.'); return; }

    setUpgrading(planId);
    setError('');
    try {
      const orderRes = await api.client.post('/billing/create-order', { plan: planId });
      const { order_id, amount, currency, key_id, plan_name } = orderRes.data;

      await new Promise((resolve, reject) => {
        const rzp = new window.Razorpay({
          key:         key_id,
          amount:      amount,
          currency:    currency,
          order_id:    order_id,
          name:        'AetherOS Factory',
          description: `${plan_name} Plan — Monthly`,
          image:       '/dashboard/aetheros-icon.png',
          theme:       { color: '#6366f1' },
          prefill:     {},
          handler: async (response) => {
            try {
              await api.client.post('/billing/verify-payment', {
                razorpay_order_id:   response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature:  response.razorpay_signature,
                plan: planId,
              });
              setCurrent(planId);
              setSuccess(`You're now on the ${plan_name} plan! Enjoy unlimited builds.`);
              resolve();
            } catch (verifyErr) {
              reject(new Error(verifyErr.response?.data?.detail || 'Payment verification failed'));
            }
          },
          modal: {
            ondismiss: () => reject(new Error('dismissed')),
          },
        });
        rzp.on('payment.failed', (resp) => reject(new Error(resp.error?.description || 'Payment failed')));
        rzp.open();
      });
    } catch (err) {
      if (err.message !== 'dismissed') setError(err.message || 'Payment failed');
    } finally {
      setUpgrading('');
    }
  };

  return (
    <div className="min-h-screen bg-surface">
      {/* Nav strip */}
      <div className="border-b border-border bg-panel px-6 py-4 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <polygon points="14,2 25,8 25,20 14,26 3,20 3,8" fill="none" stroke="#6366f1" strokeWidth="1.5"/>
            <circle cx="14" cy="14" r="3" fill="#6366f1"/>
          </svg>
          <span className="font-bold text-bright">AetherOS</span>
        </Link>
        <div className="flex items-center gap-3">
          {isLoggedIn ? (
            <Link to="/" className="text-sm text-muted hover:text-bright transition-colors">Back to dashboard →</Link>
          ) : (
            <>
              <Link to="/login"  className="text-sm text-muted hover:text-bright transition-colors">Sign in</Link>
              <Link to="/signup" className="text-sm font-bold bg-accent hover:bg-accent/90 text-white px-4 py-2 rounded-lg transition-colors">Start free</Link>
            </>
          )}
        </div>
      </div>

      {/* Hero */}
      <div className="max-w-5xl mx-auto px-6 pt-16 pb-12 text-center">
        <h1 className="text-4xl font-bold text-bright mb-3">Simple, transparent pricing</h1>
        <p className="text-lg text-muted max-w-xl mx-auto">
          Build production-ready software from a single prompt. Start free, scale when you're ready.
        </p>

        {success && (
          <div className="mt-6 max-w-md mx-auto bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4 flex items-center gap-3 text-emerald-400">
            <CheckCircle2 className="w-5 h-5 shrink-0" />
            <p className="text-sm font-medium">{success}</p>
          </div>
        )}
        {error && (
          <div className="mt-6 max-w-md mx-auto bg-danger/10 border border-danger/30 rounded-xl p-4 text-danger text-sm">{error}</div>
        )}
      </div>

      {/* Plan cards */}
      <div className="max-w-5xl mx-auto px-6 pb-20">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
          {plans.map(plan => (
            <PlanCard key={plan.id} plan={plan} current={current}
              onUpgrade={handleUpgrade} upgrading={upgrading} />
          ))}
        </div>

        {/* FAQ / trust strip */}
        <div className="mt-16 border-t border-border pt-12 grid grid-cols-1 md:grid-cols-3 gap-8 text-center">
          {[
            { q: 'Can I cancel any time?', a: 'Yes. No lock-in. You keep all generated artifacts.' },
            { q: 'Is my code private?', a: 'Completely. All runs are isolated per org. Nothing shared.' },
            { q: 'What payment methods?', a: 'UPI, cards, netbanking, wallets via Razorpay. INR only.' },
          ].map(({ q, a }) => (
            <div key={q}>
              <p className="text-sm font-bold text-bright mb-1">{q}</p>
              <p className="text-xs text-muted">{a}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Pricing;
