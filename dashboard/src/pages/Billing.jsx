import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import {
  CreditCard, TrendingUp, RefreshCw, AlertTriangle, CheckCircle2,
  Zap, Star, Building2, Loader2, ExternalLink, Download,
} from 'lucide-react';
import { PageLoader } from '../components/PageLoader';
import { confirmAction } from '../components/confirmAction';
import { apiError } from '../apiError';

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

const fmtDate = (unixS) => new Date(unixS * 1000).toLocaleDateString(undefined, { dateStyle: 'medium' });

// Paid period from GET /billing/status. When a paid period ends the org drops to the
// Free plan on its next request (core/billing/payments.py expire_if_due).
const PlanPeriod = ({ status, planLabel }) => {
  if (!status) return null;
  if (status.error) return <p className="mx-6 mb-4 text-xs text-danger">{status.error}</p>;
  if (status.period_end == null) {
    return <p className="mx-6 mb-4 text-xs text-muted">No paid period on record. The {planLabel} plan has no end date.</p>;
  }
  const ending = status.period_active && status.days_remaining <= 7;
  return (
    <div className={`mx-6 mb-6 p-4 rounded-lg border text-xs space-y-1 ${!status.period_active ? 'bg-danger/10 border-danger/30' : ending ? 'bg-warning/10 border-warning/30' : 'bg-border/10 border-border'}`}>
      {status.period_active ? (
        <p className="font-bold text-bright">
          Paid period ends {fmtDate(status.period_end)}: {status.days_remaining} day{status.days_remaining === 1 ? '' : 's'} left
          {status.period_days ? ` of ${status.period_days}` : ''}.
        </p>
      ) : (
        <p className="font-bold text-danger">The paid period ended on {fmtDate(status.period_end)}.</p>
      )}
      <p className="text-muted">
        {status.period_active
          ? 'When it ends without a renewal, your organisation moves to the Free plan (3 builds per 30 days, 1 at a time). Renew by buying the plan again below.'
          : 'Your organisation is on the Free plan (3 builds per 30 days, 1 at a time). Buy a plan below to restore paid limits.'}
      </p>
    </div>
  );
};

const Billing = () => {
  const [usage, setUsage]         = useState(null);
  const [billingStatus, setBillingStatus] = useState(null);
  const [plans, setPlans]         = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [upgrading, setUpgrading] = useState(null);
  const [success, setSuccess]     = useState(() => (
    new URLSearchParams(window.location.search).get('upgrade') === 'success'
      ? 'Payment successful! Your plan has been upgraded.' : null));
  const [portalLoading, setPortalLoading] = useState(false);
  const [invoices, setInvoices] = useState([]);
  const [cancellingSubscription, setCancellingSubscription] = useState(false);

  // Promise chain with no state set before the requests: this runs from an effect.
  const fetchAll = useCallback(() => Promise.all([
    api.client.get('/account/usage').catch(() => ({ data: null })),
    api.client.get('/billing/plans').catch(() => ({ data: null })),
    api.getBillingStatus().catch((e) => ({ data: null, error: apiError(e) || 'Plan period could not be loaded.' })),
    // Invoices may not exist for every payment method.
    api.client.get('/billing/invoices').catch(() => ({ data: [] })),
  ])
    .then(([usageRes, plansRes, statusRes, invoicesRes]) => {
      setUsage(usageRes.data);
      setBillingStatus(statusRes.data ? statusRes.data : { error: statusRes.error });
      setPlans(plansRes.data?.plans ?? []);
      setInvoices(invoicesRes.data?.invoices ?? invoicesRes.data ?? []);
      setError(plansRes.data ? null : 'Billing plans could not be loaded. Please check your connection or contact support.');
    })
    .finally(() => setLoading(false)), []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // ── India flow: Razorpay ──────────────────────────────────────────────────
  const handleRazorpayUpgrade = async (planId) => {
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
            reject(new Error(apiError(err) || 'Payment verification failed.'));
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
    window.location.assign(checkout_url);
  };

  // ── Unified upgrade handler ───────────────────────────────────────────────
  const handleUpgrade = async (planId) => {
    setUpgrading(planId);
    setSuccess(null);
    setError(null);
    try {
      if (isIndiaOrg(usage)) {
        await handleRazorpayUpgrade(planId);
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
      if (res.data?.portal_url) window.location.assign(res.data.portal_url);
    } catch (e) {
      setError(apiError(e) || 'Could not open billing portal.');
    } finally {
      setPortalLoading(false);
    }
  };

  // ── India cancel subscription ─────────────────────────────────────────────
  const handleCancelIndia = async () => {
    if (!(await confirmAction('Cancel your subscription? Your organisation moves to the Free plan straight away.'))) return;
    setCancellingSubscription(true);
    try {
      await api.client.post('/billing/cancel');
      setSuccess('Subscription cancelled. Your organisation is now on the Free plan.');
      await fetchAll();
    } catch (e) {
      setError(apiError(e) || 'Could not cancel subscription.');
    } finally {
      setCancellingSubscription(false);
    }
  };

  // ── Detect success/cancel from URL params after Stripe redirect ──────────
  // (the success message is read into initial state; fetchAll on mount already reloads the plan)
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('upgrade')) {
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  const planLabels = { free: 'Free', trial: 'Trial', starter: 'Starter', pro: 'Pro', enterprise: 'Enterprise' };
  const currentPlan = billingStatus?.plan ?? usage?.plan ?? 'trial';
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
          {india && currentPlan !== 'trial' && (
            <button
              onClick={handleCancelIndia}
              disabled={cancellingSubscription}
              className="flex items-center gap-1.5 px-3 py-2 text-xs font-bold text-danger border border-danger/30 rounded-lg hover:bg-danger/10 transition-colors disabled:opacity-50"
            >
              {cancellingSubscription ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
              Cancel Subscription
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

      {/* Payment processor badge — show only the generic Stripe badge; India flow is handled silently */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold text-muted uppercase tracking-wider">Payment Processor:</span>
        <span className="text-[10px] font-bold text-accent bg-accent/10 border border-accent/20 px-2 py-0.5 rounded-full">
          Secure Payments
        </span>
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
            <PlanPeriod status={billingStatus} planLabel={planLabels[currentPlan] ?? currentPlan} />
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
                { label: 'Tokens Today',      value: usage?.tokens_today != null ? usage.tokens_today : null },
                { label: 'Tokens This Month', value: usage?.tokens_month != null ? usage.tokens_month : null },
                { label: 'Cost This Month',   value: usage?.cost_month_usd != null ? `$${Number(usage.cost_month_usd).toFixed(4)}` : null },
                { label: 'Total Runs',        value: usage?.total_runs != null ? usage.total_runs : (usage?.runs_used != null ? usage.runs_used : null) },
              ].map(({ label, value }) => (
                <div key={label} className="flex justify-between items-center py-2 border-b border-border/30 last:border-0">
                  <span className="text-xs font-bold text-muted uppercase tracking-wider">{label}</span>
                  <span className={`text-sm font-mono ${value != null ? 'text-bright' : 'text-muted/50 italic'}`}>
                    {value != null ? value : 'No data yet'}
                  </span>
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
                          onClick={() => handleUpgrade(plan.id)}
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
              Payments processed securely. Enterprise pricing available in your local currency — contact sales.
            </p>
          </section>

          {/* Invoice history */}
          {invoices.length > 0 && (
            <section>
              <h2 className="text-sm font-bold text-muted uppercase tracking-widest mb-4">Invoice History</h2>
              <div className="panel overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-border/10">
                      <th className="text-left text-[10px] font-bold text-muted uppercase px-4 py-3">Date</th>
                      <th className="text-left text-[10px] font-bold text-muted uppercase px-4 py-3">Amount</th>
                      <th className="text-left text-[10px] font-bold text-muted uppercase px-4 py-3">Status</th>
                      <th className="text-right text-[10px] font-bold text-muted uppercase px-4 py-3">Invoice</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {invoices.map((inv, i) => (
                      <tr key={inv.id || i} className="hover:bg-border/5 transition-colors">
                        <td className="px-4 py-3 text-xs text-muted font-mono">
                          {inv.created ? new Date(inv.created * 1000).toLocaleDateString() : inv.date || '—'}
                        </td>
                        <td className="px-4 py-3 text-sm font-bold text-bright">
                          {inv.amount_paid != null ? `$${(inv.amount_paid / 100).toFixed(2)}` : inv.amount || '—'}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${
                            inv.status === 'paid' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                            : 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400'
                          }`}>{inv.status || '—'}</span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          {inv.invoice_pdf ? (
                            <a href={inv.invoice_pdf} target="_blank" rel="noopener noreferrer"
                              className="text-xs text-accent hover:underline flex items-center gap-1 justify-end">
                              <Download className="w-3 h-3" /> PDF
                            </a>
                          ) : inv.hosted_invoice_url ? (
                            <a href={inv.hosted_invoice_url} target="_blank" rel="noopener noreferrer"
                              className="text-xs text-accent hover:underline">
                              View ↗
                            </a>
                          ) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
};

export default Billing;
