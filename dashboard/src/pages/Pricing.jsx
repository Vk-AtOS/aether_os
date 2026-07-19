import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { api } from '../api';
import { CheckCircle2, Zap, Building2, Rocket, Loader2, Star } from 'lucide-react';
import { motion } from 'framer-motion';

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

// Animated gradient orb background element
function GradientOrb({ className }) {
  return <div className={`absolute rounded-full blur-[120px] opacity-20 pointer-events-none ${className}`} />;
}

// Animated terminal showing pipeline phases
function LivePipelineDemo() {
  const phases = [
    { name: 'Research', time: '0.8s', status: 'done' },
    { name: 'Architecture', time: '12.4s', status: 'done' },
    { name: 'Domain IR', time: '8.2s', status: 'done' },
    { name: 'Backend Codegen', time: '34.1s', status: 'done' },
    { name: 'Frontend Generation', time: '3m 42s', status: 'running' },
    { name: 'Security Review', time: '—', status: 'pending' },
    { name: 'Testing', time: '—', status: 'pending' },
    { name: 'Deployment', time: '—', status: 'pending' },
  ];
  return (
    <div className="bg-white/[0.02] border border-white/[0.08] rounded-2xl p-5 font-mono text-sm">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-3 h-3 rounded-full bg-red-500/60" />
        <div className="w-3 h-3 rounded-full bg-yellow-500/60" />
        <div className="w-3 h-3 rounded-full bg-green-500/60" />
        <span className="ml-2 text-slate-500 text-xs">AetherOS Factory — ClinicPro SAAS</span>
      </div>
      {phases.map((p) => (
        <div key={p.name} className="flex items-center gap-3 py-1.5 border-b border-white/[0.03] last:border-0">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
            p.status === 'done' ? 'bg-emerald-400' :
            p.status === 'running' ? 'bg-blue-400 animate-pulse' : 'bg-slate-600'
          }`} />
          <span className={`flex-1 ${p.status === 'pending' ? 'text-slate-600' : 'text-slate-300'}`}>{p.name}</span>
          <span className="text-slate-500 text-xs">{p.time}</span>
        </div>
      ))}
      <div className="mt-4 text-emerald-400 text-xs">▶ 39,814 files generated · 7m 29s</div>
    </div>
  );
}

const PlanCard = ({ plan, current, onUpgrade, upgrading }) => {
  const Icon = PLAN_ICONS[plan.id] || Rocket;
  const isCurrent = current === plan.id;
  const isHighlight = plan.highlight;
  const isEnterprise = plan.id === 'enterprise';

  return (
    <div className={`relative flex flex-col rounded-2xl overflow-hidden transition-all duration-300 ${
      isHighlight
        ? 'bg-gradient-to-b from-violet-600/20 to-indigo-600/10 border-2 border-violet-500/40 shadow-xl shadow-violet-500/10 scale-[1.02]'
        : 'bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.12] hover:bg-white/[0.04]'
    }`}>
      {isHighlight && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-gradient-to-r from-violet-600 to-indigo-500 text-white text-xs font-semibold px-4 py-1 rounded-full flex items-center gap-1">
          <Star className="w-3 h-3" /> Most popular
        </div>
      )}

      <div className="p-6 border-b border-white/[0.06]">
        <div className="flex items-center gap-2 mb-4">
          <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${isHighlight ? 'bg-violet-500/20 border border-violet-500/30' : 'bg-white/[0.04] border border-white/[0.06]'}`}>
            <Icon className={`w-4 h-4 ${isHighlight ? 'text-violet-400' : 'text-slate-400'}`} />
          </div>
          <span className="font-bold text-white text-lg">{plan.name}</span>
        </div>

        <div className="flex items-end gap-1 mb-1">
          {plan.price_usd === 0 || plan.price_inr === 0 ? (
            <span className="text-3xl font-bold text-white">Free</span>
          ) : (
            <>
              <span className="text-sm font-bold text-slate-400 self-start mt-1">$</span>
              <span className="text-3xl font-bold text-white">{plan.price_usd ?? (plan.id === 'pro' ? '49' : '199')}</span>
              <span className="text-sm text-slate-400 mb-1">/{plan.period}</span>
            </>
          )}
        </div>
        {(plan.price_usd > 0 || (plan.price_inr > 0 && !plan.price_usd)) && (
          <p className="text-xs text-slate-500">Billed monthly · Cancel any time</p>
        )}
      </div>

      <ul className="p-6 space-y-3 flex-1">
        {plan.features.map((f, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
            <span className="text-emerald-400 flex-shrink-0 mt-0.5">✓</span>
            {f}
          </li>
        ))}
      </ul>

      <div className="p-6 pt-0">
        {isCurrent ? (
          <div className="w-full py-3 rounded-xl bg-white/[0.04] border border-white/[0.08] text-center text-sm font-bold text-slate-400">
            Current plan
          </div>
        ) : isEnterprise ? (
          <a href="mailto:sales@aetheros.ai?subject=Enterprise%20Enquiry"
            className="block w-full py-3 rounded-xl border border-white/[0.10] hover:border-white/[0.20] hover:bg-white/[0.04] text-center text-sm font-bold text-slate-300 transition-all">
            Contact Sales
          </a>
        ) : plan.id === 'trial' ? (
          <Link to="/signup"
            className="block w-full py-3 rounded-xl border border-white/[0.10] hover:border-white/[0.20] hover:bg-white/[0.04] text-center text-sm font-bold text-slate-300 transition-all">
            {plan.cta}
          </Link>
        ) : (
          <button onClick={() => onUpgrade(plan.id)} disabled={upgrading === plan.id}
            className={`w-full py-3 rounded-xl text-sm font-bold transition-all flex items-center justify-center gap-2 ${
              isHighlight
                ? 'bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 text-white shadow-lg shadow-violet-500/25'
                : 'border border-white/[0.10] hover:border-white/[0.20] hover:bg-white/[0.04] text-white'
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
  // null = loading, [] = API failed (show fallback), array = API data
  const [plans, setPlans] = useState(null);
  const [current, setCurrent] = useState('trial');
  const [upgrading, setUpgrading] = useState('');
  const [success, setSuccess] = useState('');
  const [error, setError] = useState('');
  const isLoggedIn = !!api.getToken();

  useEffect(() => {
    api.client.get('/billing/plans')
      .then(r => setPlans(r.data.plans || []))
      .catch(() => setPlans([])); // empty array triggers fallback block below
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
          theme:       { color: '#7c3aed' },
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
    <div className="min-h-screen bg-[#050507] text-white overflow-hidden">
      {/* NAV */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-white/[0.06] backdrop-blur-xl bg-[#050507]/80">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-600 to-indigo-500 flex items-center justify-center">
              <span className="text-white text-xs font-bold">A</span>
            </div>
            <span className="font-semibold text-white">AetherOS</span>
          </Link>
          <div className="flex items-center gap-3">
            {isLoggedIn ? (
              <Link to="/" className="text-sm text-slate-400 hover:text-white transition-colors">
                Back to dashboard →
              </Link>
            ) : (
              <>
                <Link to="/login" className="text-sm text-slate-400 hover:text-white transition-colors px-4 py-2">Sign in</Link>
                <Link to="/signup" className="bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 text-white text-sm font-medium px-4 py-2 rounded-xl transition-all duration-200 shadow-lg shadow-violet-500/25">
                  Start building free
                </Link>
              </>
            )}
          </div>
        </div>
      </nav>

      {/* HERO */}
      <section className="relative min-h-screen flex items-center pt-16">
        <GradientOrb className="w-[600px] h-[600px] bg-violet-600 top-[-100px] left-[-200px] animate-pulse" />
        <GradientOrb className="w-[400px] h-[400px] bg-indigo-600 top-[200px] right-[-100px] animate-pulse" />
        <GradientOrb className="w-[300px] h-[300px] bg-purple-600 bottom-[100px] left-[200px] animate-pulse" />

        <div className="relative max-w-7xl mx-auto px-6 py-24 grid lg:grid-cols-2 gap-16 items-center">
          <motion.div initial={{opacity:0, y:30}} animate={{opacity:1, y:0}} transition={{duration:0.8}}>
            <div className="inline-flex items-center gap-2 bg-violet-500/10 border border-violet-500/20 rounded-full px-4 py-1.5 text-sm text-violet-300 mb-8">
              <span className="w-2 h-2 rounded-full bg-violet-400 animate-pulse" />
              29-phase autonomous pipeline · now live
            </div>
            <h1 className="text-5xl lg:text-7xl font-bold tracking-tight mb-6">
              <span className="text-white">Build production</span>
              <br />
              <span className="bg-gradient-to-r from-violet-400 via-indigo-400 to-cyan-400 bg-clip-text text-transparent">
                apps. Autonomously.
              </span>
            </h1>
            <p className="text-xl text-slate-400 mb-10 leading-relaxed max-w-lg">
              Describe your product. AetherOS architects, codes, tests, and deploys a complete full-stack application — backend, frontend, infrastructure, docs.
            </p>
            <div className="flex flex-wrap gap-4">
              <Link to="/signup" className="bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 text-white font-semibold px-8 py-4 rounded-xl transition-all duration-200 shadow-xl shadow-violet-500/30 hover:shadow-violet-500/50 hover:scale-105 text-base">
                Start building free →
              </Link>
              {isLoggedIn ? (
                <Link to="/" className="border border-white/10 hover:border-white/20 hover:bg-white/[0.04] text-white font-medium px-8 py-4 rounded-xl transition-all duration-200 text-base">
                  Go to dashboard
                </Link>
              ) : (
                <Link to="/login" className="border border-white/10 hover:border-white/20 hover:bg-white/[0.04] text-white font-medium px-8 py-4 rounded-xl transition-all duration-200 text-base">
                  Sign in
                </Link>
              )}
            </div>
            <div className="mt-10 flex items-center gap-6 text-sm text-slate-500">
              <span className="flex items-center gap-2"><span className="text-emerald-400">✓</span> No credit card required</span>
              <span className="flex items-center gap-2"><span className="text-emerald-400">✓</span> Free tier available</span>
              <span className="flex items-center gap-2"><span className="text-emerald-400">✓</span> Own your code</span>
            </div>
          </motion.div>

          <motion.div initial={{opacity:0, y:30}} animate={{opacity:1, y:0}} transition={{duration:0.8, delay:0.2}}>
            <LivePipelineDemo />
          </motion.div>
        </div>
      </section>

      {/* STATS */}
      <section className="border-y border-white/[0.06] py-16">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
            {[
              { value: '29', label: 'Pipeline phases', sub: 'fully autonomous' },
              { value: '~8min', label: 'Avg build time', sub: 'full-stack app' },
              { value: '39K+', label: 'Files generated', sub: 'per project' },
              { value: '100%', label: 'Code ownership', sub: 'you own everything' },
            ].map((s) => (
              <div key={s.label} className="text-center">
                <div className="text-4xl font-bold bg-gradient-to-r from-violet-400 to-indigo-400 bg-clip-text text-transparent mb-1">{s.value}</div>
                <div className="text-white font-medium text-sm">{s.label}</div>
                <div className="text-slate-500 text-xs mt-0.5">{s.sub}</div>
              </div>
            ))}
          </div>
          <p className="text-center text-slate-600 text-xs mt-8">(Beta testing statistics — measured across internal pipeline runs)</p>
        </div>
      </section>

      {/* FEATURES */}
      <section className="py-32">
        <div className="max-w-7xl mx-auto px-6">
          <motion.div initial={{opacity:0,y:20}} whileInView={{opacity:1,y:0}} viewport={{once:true}} className="text-center mb-16">
            <div className="text-violet-400 text-sm font-medium uppercase tracking-widest mb-4">Capabilities</div>
            <h2 className="text-4xl font-bold text-white mb-4">Everything a software team needs</h2>
            <p className="text-slate-400 text-lg max-w-2xl mx-auto">From a single requirement to a production-deployed application — every layer generated, tested, and documented.</p>
          </motion.div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[
              { icon: '⚡', title: '29-Phase Pipeline', desc: 'Research, architecture, domain modeling, backend, frontend, security, testing, CI/CD, deployment — all automated.', color: 'from-violet-500 to-purple-600' },
              { icon: '🎨', title: 'Designer Studio', desc: 'Set your brand colors, typography, component library, and visual style. The LLM builds to your spec.', color: 'from-indigo-500 to-blue-600' },
              { icon: '🔒', title: 'Enterprise Security', desc: 'ABAC permissions, immutable audit trails, JWT RS256, SOC2/HIPAA compliance profiles built in.', color: 'from-emerald-500 to-teal-600' },
              { icon: '🔌', title: 'Integration Codegen', desc: 'Connects to Salesforce, SAP, Active Directory, Stripe, and any REST/SOAP API — clients generated automatically.', color: 'from-amber-500 to-orange-600' },
              { icon: '📦', title: 'Enterprise Deployment', desc: 'Helm charts, Terraform (AWS/Azure/GCP), K8s HPA, backup scripts, and air-gap bundle — all generated.', color: 'from-rose-500 to-pink-600' },
              { icon: '📚', title: 'Handoff Package', desc: 'README, architecture docs, API reference, database ERD, runbook, and Postman collection — auto-generated.', color: 'from-cyan-500 to-sky-600' },
            ].map((f, i) => (
              <motion.div key={f.title} initial={{opacity:0,y:20}} whileInView={{opacity:1,y:0}} viewport={{once:true}} transition={{delay: i * 0.1}}
                className="group bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.06] hover:border-white/[0.12] rounded-2xl p-6 transition-all duration-300 cursor-pointer hover:-translate-y-1">
                <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${f.color} flex items-center justify-center text-2xl mb-4 group-hover:scale-110 transition-transform duration-300`}>
                  {f.icon}
                </div>
                <h3 className="text-white font-semibold text-lg mb-2">{f.title}</h3>
                <p className="text-slate-400 text-sm leading-relaxed">{f.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section className="py-32 border-t border-white/[0.06]">
        <div className="max-w-4xl mx-auto px-6">
          <motion.div initial={{opacity:0,y:20}} whileInView={{opacity:1,y:0}} viewport={{once:true}} className="text-center mb-16">
            <div className="text-violet-400 text-sm font-medium uppercase tracking-widest mb-4">How it works</div>
            <h2 className="text-4xl font-bold text-white mb-4">From prompt to production in minutes</h2>
          </motion.div>
          <div className="space-y-0">
            {[
              { n: '01', title: 'Describe what you want to build', desc: 'Use the Designer Studio to set your app type, domain, features, brand colors, and integration requirements. No technical spec needed.', color: 'text-violet-400' },
              { n: '02', title: 'AetherOS runs the 29-phase pipeline', desc: 'Architecture, domain modeling, backend codegen, frontend generation, security review, performance testing, enterprise deployment — all autonomous.', color: 'text-indigo-400' },
              { n: '03', title: 'Download and deploy instantly', desc: 'Get a ZIP with your complete codebase, Helm charts, Terraform, documentation, and Postman collection. Or deploy directly from the dashboard.', color: 'text-cyan-400' },
              { n: '04', title: 'Own it forever', desc: 'Clean, readable code with full documentation. No vendor lock-in. Modify, extend, and ship on your own infrastructure.', color: 'text-emerald-400' },
            ].map((s, i) => (
              <motion.div key={s.n} initial={{opacity:0,x:-20}} whileInView={{opacity:1,x:0}} viewport={{once:true}} transition={{delay: i*0.15}}
                className="flex gap-8 items-start py-8 border-b border-white/[0.04] last:border-0">
                <div className={`text-5xl font-black ${s.color} opacity-30 min-w-[60px]`}>{s.n}</div>
                <div>
                  <h3 className="text-white font-semibold text-xl mb-2">{s.title}</h3>
                  <p className="text-slate-400 leading-relaxed">{s.desc}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section className="py-32 border-t border-white/[0.06]">
        <div className="max-w-5xl mx-auto px-6">
          <motion.div initial={{opacity:0,y:20}} whileInView={{opacity:1,y:0}} viewport={{once:true}} className="text-center mb-16">
            <div className="text-violet-400 text-sm font-medium uppercase tracking-widest mb-4">Pricing</div>
            <h2 className="text-4xl font-bold text-white mb-4">Start free, grow when you're ready</h2>
            <p className="text-slate-400 text-lg">No contracts. Cancel anytime.</p>
          </motion.div>

          {success && (
            <div className="mb-8 max-w-md mx-auto bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4 flex items-center gap-3 text-emerald-400">
              <CheckCircle2 className="w-5 h-5 shrink-0" />
              <p className="text-sm font-medium">{success}</p>
            </div>
          )}
          {error && (
            <div className="mb-8 max-w-md mx-auto bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">{error}</div>
          )}

          {plans === null ? (
            /* Loading skeleton — avoids flashing wrong prices before API responds */
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start animate-pulse">
              {[1, 2, 3].map(i => (
                <div key={i} className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-6 space-y-4">
                  <div className="h-5 bg-white/[0.06] rounded w-1/3" />
                  <div className="h-8 bg-white/[0.06] rounded w-1/2" />
                  <div className="space-y-2">
                    {[1, 2, 3].map(j => <div key={j} className="h-3 bg-white/[0.04] rounded" />)}
                  </div>
                  <div className="h-10 bg-white/[0.06] rounded-xl" />
                </div>
              ))}
            </div>
          ) : plans.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
              {plans.map(plan => (
                <PlanCard key={plan.id} plan={plan} current={current}
                  onUpgrade={handleUpgrade} upgrading={upgrading} />
              ))}
            </div>
          ) : (
            /* Fallback USD prices shown only when API call definitively fails */
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
              {[
                { name: 'Free', price: '$0', period: 'forever', features: ['3 pipeline runs/month', 'All phases', 'ZIP download', 'Community support'], cta: 'Start free', highlight: false, link: '/signup' },
                { name: 'Pro', price: '$49', period: '/month', features: ['Unlimited runs', 'All 29 phases', 'Priority builds', 'Enterprise deployment', 'Handoff package', 'Email support'], cta: 'Start Pro trial', highlight: true, link: '/signup' },
                { name: 'Enterprise', price: '$199', period: '/month', features: ['Everything in Pro', 'SAML SSO', 'Custom models', 'SLA guarantee', 'Dedicated support', 'On-premise option'], cta: 'Contact sales', highlight: false, link: 'mailto:sales@aetheros.ai' },
              ].map((p) => (
                <div key={p.name} className={`relative rounded-2xl p-6 ${p.highlight
                  ? 'bg-gradient-to-b from-violet-600/20 to-indigo-600/10 border-2 border-violet-500/40 shadow-xl shadow-violet-500/10 scale-[1.02]'
                  : 'bg-white/[0.02] border border-white/[0.06]'
                }`}>
                  {p.highlight && <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-gradient-to-r from-violet-600 to-indigo-500 text-white text-xs font-semibold px-4 py-1 rounded-full">Most popular</div>}
                  <div className="mb-6">
                    <div className="text-slate-400 text-sm mb-2">{p.name}</div>
                    <div className="flex items-baseline gap-1">
                      <span className="text-4xl font-bold text-white">{p.price}</span>
                      <span className="text-slate-400 text-sm">{p.period}</span>
                    </div>
                  </div>
                  <ul className="space-y-3 mb-8">
                    {p.features.map(f => (
                      <li key={f} className="flex items-center gap-2 text-sm text-slate-300">
                        <span className="text-emerald-400 flex-shrink-0">✓</span> {f}
                      </li>
                    ))}
                  </ul>
                  <Link to={p.link} className={`block text-center py-3 rounded-xl font-medium text-sm transition-all duration-200 ${p.highlight
                    ? 'bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 text-white shadow-lg shadow-violet-500/25'
                    : 'border border-white/10 hover:border-white/20 hover:bg-white/[0.04] text-white'
                  }`}>{p.cta}</Link>
                </div>
              ))}
            </div>
          )}

          {/* FAQ strip */}
          <div className="mt-16 border-t border-white/[0.06] pt-12 grid grid-cols-1 md:grid-cols-3 gap-8 text-center">
            {[
              { q: 'Can I cancel any time?', a: 'Yes. No lock-in. You keep all generated artifacts.' },
              { q: 'Is my code private?', a: 'Completely. All runs are isolated per org. Nothing shared.' },
              { q: 'What payment methods?', a: 'Cards, bank transfers via Stripe. Enterprise pricing available in your local currency — contact sales.' },
            ].map(({ q, a }) => (
              <div key={q}>
                <p className="text-sm font-bold text-white mb-1">{q}</p>
                <p className="text-xs text-slate-500">{a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-32 border-t border-white/[0.06]">
        <div className="max-w-3xl mx-auto px-6 text-center">
          <motion.div initial={{opacity:0,y:20}} whileInView={{opacity:1,y:0}} viewport={{once:true}}>
            <h2 className="text-5xl font-bold text-white mb-6">Ready to ship faster?</h2>
            <p className="text-slate-400 text-lg mb-10">Join teams using AetherOS to build production software in minutes, not months.</p>
            <div className="flex flex-wrap justify-center gap-4">
              <Link to="/signup" className="bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 text-white font-semibold px-10 py-4 rounded-xl transition-all duration-200 shadow-xl shadow-violet-500/30 hover:scale-105 text-base">
                Start building free →
              </Link>
              {isLoggedIn ? (
                <Link to="/" className="border border-white/10 hover:border-white/20 hover:bg-white/[0.04] text-white font-medium px-10 py-4 rounded-xl transition-all duration-200 text-base">
                  Go to dashboard
                </Link>
              ) : (
                <Link to="/login" className="border border-white/10 hover:border-white/20 hover:bg-white/[0.04] text-white font-medium px-10 py-4 rounded-xl transition-all duration-200 text-base">
                  Sign in
                </Link>
              )}
            </div>
          </motion.div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="border-t border-white/[0.06] py-8">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-slate-500">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-violet-600 to-indigo-500" />
            <span>© 2026 VKatOS Private Limited — AetherOS Factory</span>
          </div>
          <div className="flex gap-6">
            <Link to="/legal" className="hover:text-slate-300 transition-colors">Privacy & Terms</Link>
            {isLoggedIn && <Link to="/" className="hover:text-slate-300 transition-colors">Dashboard</Link>}
          </div>
        </div>
      </footer>
    </div>
  );
};

export default Pricing;
