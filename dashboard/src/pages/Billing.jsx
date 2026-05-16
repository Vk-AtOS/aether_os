import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { CreditCard, TrendingUp, RefreshCw, AlertTriangle, CheckCircle2, Zap, Star, Building2, Loader2 } from 'lucide-react';

const PLAN_ICONS = { trial: Zap, pro: Star, enterprise: Building2 };
const PLAN_COLORS = { trial: 'text-yellow-400', pro: 'text-accent', enterprise: 'text-purple-400' };

const loadRazorpay = () =>
  new Promise((resolve) => {
    if (document.getElementById('razorpay-script')) { resolve(true); return; }
    const s = document.createElement('script');
    s.id = 'razorpay-script';
    s.src = 'https://checkout.razorpay.com/v1/checkout.js';
    s.onload = () => resolve(true);
    s.onerror = () => resolve(false);
    document.body.appendChild(s);
  });

const Billing = () => {
  const [usage, setUsage]         = useState(null);
  const [plans, setPlans]         = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [upgrading, setUpgrading] = useState(null); // plan id being upgraded
  const [success, setSuccess]     = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [usageRes, plansRes] = await Promise.all([
        api.client.get('/account/usage').catch(() => ({ data: null })),
        api.client.get('/billing/plans').catch(() => ({ data: { plans: [] } })),
      ]);
      setUsage(usageRes.data);
      setPlans(plansRes.data?.plans ?? []);
    } catch (e) {
      setError('Failed to load billing data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleUpgrade = async (planId) => {
    setUpgrading(planId);
    setSuccess(null);
    try {
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
          modal: {
            ondismiss: () => reject(new Error('__dismissed__')),
          },
          prefill: {},
          theme: { color: '#6366f1' },
        });
        rzp.on('payment.failed', (resp) => {
          reject(new Error(resp.error?.description || 'Payment failed.'));
        });
        rzp.open();
      });
    } catch (e) {
      if (e.message !== '__dismissed__') {
        setError(e.message);
      }
    } finally {
      setUpgrading(null);
    }
  };

  const planLabels = { trial: 'Trial', starter: 'Starter', pro: 'Pro', enterprise: 'Enterprise' };
  const currentPlan = usage?.plan ?? 'trial';

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright">Billing & Usage</h1>
          <p className="text-muted mt-1">Monitor usage, plan limits, and subscription details.</p>
        </div>
        <button
          onClick={fetchAll}
          className="p-2 text-muted hover:text-bright border border-border rounded-lg transition-colors"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </header>

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
        <div className="p-12 flex justify-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
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
                { label: 'Plan', value: planLabels[currentPlan] ?? currentPlan ?? '—' },
                { label: 'Runs Used', value: usage?.runs_used ?? '—' },
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
                { label: 'Tokens Today', value: usage?.tokens_today ?? '—' },
                { label: 'Tokens This Month', value: usage?.tokens_month ?? '—' },
                { label: 'Cost This Month', value: usage?.cost_month_usd != null ? `$${Number(usage.cost_month_usd).toFixed(4)}` : '—' },
                { label: 'Total Runs', value: usage?.total_runs ?? '—' },
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
                const Icon = PLAN_ICONS[plan.id] ?? CreditCard;
                const iconColor = PLAN_COLORS[plan.id] ?? 'text-muted';
                const isCurrent = plan.id === currentPlan;
                const isUpgradeable = plan.id === 'pro' || plan.id === 'enterprise';
                const isBusy = upgrading === plan.id;

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

                      <div className="mb-4">
                        {plan.price_inr === 0 ? (
                          <span className="text-3xl font-bold text-bright">Free</span>
                        ) : (
                          <>
                            <span className="text-3xl font-bold text-bright">₹{plan.price_inr}</span>
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
                            plan.cta
                          )}
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </>
      )}
    </div>
  );
};

export default Billing;
