import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import {
  CreditCard, TrendingUp, RefreshCw, AlertTriangle, CheckCircle2,
  Zap, Star, Building2, Loader2, ExternalLink,
} from 'lucide-react';
import { PageLoader } from '../components/PageLoader';

const PLAN_ICONS  = { trial: Zap, pro: Star, enterprise: Building2 };
const PLAN_COLORS = { trial: 'text-yellow-400', pro: 'text-accent', enterprise: 'text-purple-400' };

// ── Razorpay SDK loader ────────────────────────────────────────────────────────
const loadRazorpay = () =>
  new Promise((resolve) => {
    if (document.getElementById('razorpay-script')) { resolve(true); return; }
    const s = document.createElement('script');
    s.id = 'razorpay-script';
    s.src = 'https://checkout.razorpay.com/v1/checkout.js';
    s.onload  = () => resolve(true);
    s.onerror = () => resolve(false);
    document.body.appendChild(s);
  });

// ── Detect org country from usage/profile data ─────────────────────────────
const isIndiaOrg = (usage) => {
  const country = (usage?.country || usage?.org_country || '').toUpperCase().trim();
  return country === 'IN' || country === 'IND' || country === 'INDIA';
};

const Billing = () => {
  const [usage, setUsage]         = useState(null);
  const [plans, setPlans]         = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [upgrading, setUpgrading] = useState(null);
  const [success, setSuccess]     = useState(null);
  const [portalLoading, setPortalLoading] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [usageRes, plansRes] = await Promise.all([
        api.client.get('/account/usage').catch(() => ({ data: null })),
        api.client.get('/billing/plans').catch(() => ({ data: null })),
      ]);
      setUsage(usageRes.data);
      const planList = plansRes.data?.plans ?? [];
      setPlans(planList);
      if (!plansRes.data) setError('Billing plans could not be loaded. Please check your connection or contact support.');
    } catch (e) {
      setError('Failed to load billing data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // ── India flow: Razorpay ──────────────────────────────────────────────────
  const handleRazorpayUpgrade = async (planId, planName) => {
    const loaded = await loadRazorpay();
    if (!loaded) throw new Error('Failed to load Razorpay SDK. Check your internet connection.');

    const orderRes = await api.client.post('/billing/create-order', { plan: planId });
    const { order_id, amount, currency, plan_name, key_id } = orderRes.data;
    if (!key_id) throw new Error('Payment gateway not configured on server.');

    await new Promise((resolve, reject) => {
      const rzp = new window.Razorpay({
        key:         key_id,
        amount,
        currency,
        order_id,
        name:        'AetherOS',
        description: `Upgrade to ${plan_name}`,
        image:       '/dashboard/favicon.svg',
        handler: async (response) => {
          try {
            await api.client.post('/billing/verify-payment', {
              razorpay_order_id:   response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature:  response.razorpay_signature,
              plan:                planId,
            });
            setSuccess(`You are now on the ${plan_name} plan!`);
            await fetchAll();
            resolve();
          } catch (err) {
            reject(new Error(err.response?.data?.detail || 'Payment verification failed.'));
          }
        },
        modal: { ondismiss: () => reject(new Error('__dismissed__')) },
        prefill: {},
        theme: { color: '#6366f1' },
      });
      rzp.on('payment.failed', (resp) => {
        reject(new Error(resp.error?.description || 'Payment failed.'));
      });
      rzp.open();
    });
  };

  // ── Non-India flow: Stripe Checkout ──────────────────────────────────────
  const handleStripeUpgrade = async (planId) => {
    const res = await api.client.post('/billing/stripe/checkout', {
      plan:        planId,
      success_url: `${window.location.origin}/billing?upgrade=success`,
      cancel_url:  `${window.location.origin}/billing?upgrade=cancelled`,
    });
    const { checkout_url } = res.data;
    if (!checkout_url) throw new Error('Stripe checkout URL not returned from server.');
    // Redirect to Stripe-hosted checkout
    window.location.href = checkout_url;
  };

  // ── Unified upgrade handler ───────────────────────────────────────────────
  const handleUpgrade = async (planId, planName) => {
    setUpgrading(planId);
    setSuccess(null);
    setError(null);
    try {
      if (isIndiaOrg(usage)) {
        await handleRazorpayUpgrade(planId, planName);
      } else {
        await handleStripeUpgrade(planId);
      }
    } catch (e) {
      if (e.message !== '__dismissed__') setError(e.message);
    } finally {
      setUpgrading(null);
    }
  };

  // ── Stripe Customer Portal ────────────────────────────────────────────────
  const handleStripePortal = async () => {
    setPortalLoading(true);
    setError(null);
    try {
      const res = await api.client.get('/billing/stripe/portal');
      if (res.data?.portal_url) window.location.href = res.data.portal_url;
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not open billing portal.');
    } finally {
      setPortalLoading(false);
    }
  };

  // ── Detect success/cancel from URL params after Stripe redirect ──────────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('upgrade') === 'success') {
      setSuccess('Payment successful! Your plan has been upgraded.');
      window.history.replaceState({}, '', window.location.pathname);
      fetchAll();
    } else if (params.get('upgrade') === 'cancelled') {
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const planLabels = { trial: 'Trial', starter: 'Starter', pro: 'Pro', enterprise: 'Enterprise' };
  const currentPlan = usage?.plan ?? 'trial';
  const india = isIndiaOrg(usage);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright">Billing &amp; Usage</h1>
          <p className="text-muted mt-1">Monitor usage, plan limits, and subscription details.</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Stripe Portal button for active non-India subscribers */}
          {!india && currentPlan !== 'trial' && (
            <button
              onClick={handleStripePortal}
              disabled={portalLoading}
              className="flex items-center gap-1.5 px-3 py-2 text-xs font-bold text-muted border border-border rounded-lg hover:text-bright hover:border-accent/50 transition-colors disabled:opacity-50"
              title="Manage subscription in Stripe portal"
            >
              {portalLoading
                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                : <ExternalLink className="w-3.5 h-3.5" />
              }
              Manage Subscription
            </button>
          )}
          <button
            onClick={fetchAll}
            className="p-2 text-muted hover:text-bright border border-border rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Payment processor badge */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold text-muted uppercase tracking-wider">Payment Processor:</span>
        {india ? (
          <span className="text-[10px] font-bold text-orange-400 bg-orange-400/10 border border-orange-400/20 px-2 py-0.5 rounded-full">
            Razorpay (India)
          </span>
        ) : (
          <span className="text-[10px] font-bold text-accent bg-accent/10 border border-accent/20 px-2 py-0.5 rounded-full">
            Stripe
          </span>
        )}
      </div>

      {success && (
        <div className="flex items-center gap-3 p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
          <span className="text-sm font-medium">{success}</span>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-danger">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {loading ? (
        <div className="p-6">
          <PageLoader />
        </div>
      ) : (
        <>
          {/* Plan summary */}
          <section className="panel overflow-hidden">
            <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center gap-2">
              <CreditCard className="w-4 h-4 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Current Plan</h3>
            </div>
            <div className="p-6 grid grid-cols-2 gap-6 sm:grid-cols-4">
              {[
                { label: 'Plan',       value: planLabels[currentPlan] ?? currentPlan ?? '—' },
                { label: 'Runs Used',  value: usage?.runs_used ?? '—' },
                { label: 'Runs Limit', value: usage?.runs_limit ?? '∞' },
                { label: 'Cost Today', value: usage?.cost_today_usd != null ? `$${Number(usage.cost_today_usd).toFixed(4)}` : '—' },
              ].map(({ label, value }) => (
                <div key={label} className="space-y-1">
                  <div className="text-[10px] font-bold text-muted uppercase tracking-wider">{label}</div>
                  <div className="text-xl font-bold text-bright font-mono">{value}</div>
                </div>
              ))}
            </div>
            {currentPlan === 'trial' && (
              <div className="mx-6 mb-6 p-4 bg-warning/10 border border-warning/30 rounded-lg flex items-center gap-3">
                <AlertTriangle className="w-4 h-4 text-warning flex-shrink-0" />
                <div>
                  <p className="text-xs font-bold text-warning">Trial Plan</p>
                  <p className="text-xs text-muted mt-0.5">
                    {usage?.runs_used ?? 0} of {usage?.runs_limit ?? 3} trial runs used. Upgrade to continue running pipelines after the trial ends.
                  </p>
                </div>
              </div>
            )}
          </section>

          {/* Usage breakdown */}
          <section className="panel overflow-hidden">
            <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-accent" />
              <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Usage Breakdown</h3>
            </div>
            <div className="p-6 space-y-4">
              {[
                { label: 'Tokens Today',      value: usage?.tokens_today ?? '—' },
                { label: 'Tokens This Month', value: usage?.tokens_month ?? '—' },
                { label: 'Cost This Month',   value: usage?.cost_month_usd != null ? `$${Number(usage.cost_month_usd).toFixed(4)}` : '—' },
                { label: 'Total Runs',        value: usage?.total_runs ?? '—' },
              ].map(({ label, value }) => (
                <div key={label} className="flex justify-between items-center py-2 border-b border-border/30 last:border-0">
                  <span className="text-xs font-bold text-muted uppercase tracking-wider">{label}</span>
                  <span className="text-sm font-mono text-bright">{value}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Plan cards */}
          <section>
            <h2 className="text-sm font-bold text-muted uppercase tracking-widest mb-4">Available Plans</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {plans.map((plan) => {
                const Icon       = PLAN_ICONS[plan.id]  ?? CreditCard;
                const iconColor  = PLAN_COLORS[plan.id] ?? 'text-muted';
                const isCurrent  = plan.id === currentPlan;
                const isUpgradeable = plan.id === 'pro' || plan.id === 'enterprise';
                const isBusy     = upgrading === plan.id;

                return (
                  <div
                    key={plan.id}
                    className={`panel overflow-hidden flex flex-col transition-all ${plan.highlight ? 'ring-2 ring-accent/50' : ''}`}
                  >
                    {plan.highlight && (
                      <div className="bg-accent text-white text-[10px] font-bold uppercase tracking-widest text-center py-1">
                        Most Popular
                      </div>
                    )}
                    <div className="p-5 flex flex-col flex-1">
                      <div className="flex items-center gap-2 mb-4">
                        <Icon className={`w-5 h-5 ${iconColor}`} />
                        <span className="font-bold text-bright">{plan.name}</span>
                        {isCurrent && (
                          <span className="ml-auto text-[10px] font-bold uppercase tracking-wider text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full">
                            Current
                          </span>
                        )}
                      </div>

                      {/* Pricing — show INR for India, USD for others */}
                      <div className="mb-4">
                        {plan.price_inr === 0 ? (
                          <span className="text-3xl font-bold text-bright">Free</span>
                        ) : india ? (
                          <>
                            <span className="text-3xl font-bold text-bright">&#8377;{plan.price_inr}</span>
                            <span className="text-muted text-sm">/{plan.period}</span>
                          </>
                        ) : (
                          <>
                            <span className="text-3xl font-bold text-bright">
                              ${plan.id === 'pro' ? '29' : '149'}
                            </span>
                            <span className="text-muted text-sm">/{plan.period}</span>
                          </>
                        )}
                      </div>

                      <ul className="space-y-2 flex-1 mb-5">
                        {plan.features.map((f) => (
                          <li key={f} className="flex items-start gap-2 text-xs text-muted">
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 flex-shrink-0" />
                            {f}
                          </li>
                        ))}
                      </ul>

                      {isCurrent ? (
                        <div className="w-full py-2.5 text-center text-xs font-bold text-muted bg-border/30 rounded-lg cursor-default">
                          Active Plan
                        </div>
                      ) : plan.id === 'enterprise' ? (
                        <a
                          href="mailto:sales@aetheros.ai?subject=Enterprise Plan Inquiry"
                          className="w-full block text-center py-2.5 bg-purple-500/10 text-purple-400 border border-purple-400/30 text-xs font-bold rounded-lg hover:bg-purple-500/20 transition-colors"
                        >
                          Contact Sales
                        </a>
                      ) : isUpgradeable ? (
                        <button
                          onClick={() => handleUpgrade(plan.id, plan.name)}
                          disabled={isBusy || upgrading !== null}
                          className="w-full py-2.5 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-2"
                        >
                          {isBusy ? (
                            <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Processing…</>
                          ) : (
                            <>
                              {!india && <CreditCard className="w-3.5 h-3.5" />}
                              {plan.cta}
                            </>
                          )}
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Payment method note */}
            <p className="text-[10px] text-muted mt-4 text-center">
              {india
                ? 'Payments processed securely via Razorpay. Prices in INR inclusive of GST.'
                : 'Payments processed securely via Stripe. Prices in USD. Cancel anytime from the subscription portal.'
              }
            </p>
          </section>
        </>
      )}
    </div>
  );
};

export default Billing;
