import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';
import { confirmAction } from '../confirmAction';

// Lowest to highest, same order as the server (billing_router._PLAN_ORDER).
const ORDER = ['free', 'trial', 'starter', 'pro', 'enterprise'];
const LABEL = { free: 'Free', trial: 'Trial', starter: 'Starter', pro: 'Pro', enterprise: 'Enterprise' };

// One control for lowering the plan, for Razorpay and Stripe orgs alike: "Free" is the cancel.
// The server does the provider side first; this only confirms what is lost and shows the result.
const PlanReduction = ({ currentPlan, periodEnd, onDone, onError }) => {
  const lower = ORDER.slice(0, Math.max(0, ORDER.indexOf(currentPlan))).filter((p) => p !== 'trial');
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState(false);
  if (lower.length === 0) return null;

  const run = async () => {
    const ends = periodEnd ? new Date(periodEnd * 1000).toLocaleDateString() : null;
    const msg = target === 'free'
      ? 'Cancel your subscription? Your organisation moves to the Free plan straight away and the paid period ends.'
      : `Move to ${LABEL[target]}? This takes effect now. Features of ${LABEL[currentPlan]} are lost${ends ? `; the period you paid for still ends on ${ends}` : ''}.`;
    if (!(await confirmAction(msg, target === 'free' ? 'Cancel subscription' : 'Downgrade plan'))) return;
    setBusy(true);
    try {
      if (target === 'free') await api.cancelSubscription();
      else await api.downgradePlan(target);
      onDone(target === 'free' ? 'Subscription cancelled. Your organisation is now on the Free plan.' : `Plan changed to ${LABEL[target]}.`);
    } catch (e) {
      onError(apiError(e) || 'Could not change the plan.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <select aria-label="Lower plan" value={target} onChange={(e) => setTarget(e.target.value)}
        className="bg-surface border border-border rounded-lg px-2 py-2 text-xs text-bright">
        <option value="">Lower plan…</option>
        {lower.map((p) => <option key={p} value={p}>{p === 'free' ? 'Free (cancel subscription)' : LABEL[p]}</option>)}
      </select>
      <button onClick={run} disabled={!target || busy}
        className="flex items-center gap-1.5 px-3 py-2 text-xs font-bold text-danger border border-danger/30 rounded-lg hover:bg-danger/10 disabled:opacity-50">
        {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}Apply
      </button>
    </div>
  );
};

export default PlanReduction;
