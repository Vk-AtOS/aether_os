import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { CreditCard, TrendingUp, Users, RefreshCw, AlertTriangle } from 'lucide-react';

const Billing = () => {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchUsage = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.client.get('/account/usage');
      setUsage(res.data);
    } catch (e) {
      setError(e.response?.status === 403 ? 'Admin access required.' : 'Failed to load billing data.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchUsage(); }, []);

  const planLabels = { trial: 'Trial', starter: 'Starter', pro: 'Pro', enterprise: 'Enterprise' };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright">Billing & Usage</h1>
          <p className="text-muted mt-1">Monitor usage, plan limits, and subscription details.</p>
        </div>
        <button
          onClick={fetchUsage}
          className="p-2 text-muted hover:text-bright border border-border rounded-lg transition-colors"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </header>

      {loading ? (
        <div className="p-12 flex justify-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
        </div>
      ) : error ? (
        <div className="panel p-8 flex items-center gap-3 text-danger">
          <AlertTriangle className="w-5 h-5" />
          <span className="text-sm">{error}</span>
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
                { label: 'Plan', value: planLabels[usage?.plan] ?? usage?.plan ?? '—' },
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
            {usage?.plan === 'trial' && (
              <div className="mx-6 mb-6 p-4 bg-warning/10 border border-warning/30 rounded-lg flex items-center gap-3">
                <AlertTriangle className="w-4 h-4 text-warning flex-shrink-0" />
                <div>
                  <p className="text-xs font-bold text-warning">Trial Plan</p>
                  <p className="text-xs text-muted mt-0.5">
                    {usage.runs_used ?? 0} of {usage.runs_limit ?? 3} trial runs used. Upgrade to continue running pipelines after the trial ends.
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

          {/* Upgrade CTA */}
          <section className="panel p-6 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-bright">Need more capacity?</h3>
              <p className="text-xs text-muted mt-1">Contact us to upgrade your plan or add team seats.</p>
            </div>
            <a
              href="mailto:sales@aetheros.ai?subject=Upgrade Inquiry"
              className="bg-accent hover:bg-accent/90 text-white text-xs font-bold px-5 py-2.5 rounded-lg transition-colors uppercase tracking-wider"
            >
              Contact Sales
            </a>
          </section>
        </>
      )}
    </div>
  );
};

export default Billing;
