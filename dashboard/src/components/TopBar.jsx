import React, { useState, useEffect, useRef } from 'react';
import { LogOut, Plus, Coins, Zap, Search, Building2, ChevronDown, Check } from 'lucide-react';
import { api } from '../api';
import { useNavigate, useLocation } from 'react-router-dom';
import NotificationBell from './NotificationBell';
import { useSettings } from '../contexts/SettingsContext';

const PROVIDER_COLORS = {
  anthropic:   { text: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/20' },
  openrouter:  { text: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20' },
  gemini:      { text: 'text-blue-400',   bg: 'bg-blue-500/10 border-blue-500/20' },
  ollama:      { text: 'text-green-400',  bg: 'bg-green-500/10 border-green-500/20' },
  bedrock:     { text: 'text-amber-400',  bg: 'bg-amber-500/10 border-amber-500/20' },
};

const OrgSwitcher = () => {
  const [open, setOpen] = useState(false);
  const [orgs, setOrgs] = useState([]);
  const [currentOrg, setCurrentOrg] = useState(null);
  const [switching, setSwitching] = useState(null);
  const ref = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.getMyOrgs().then(res => {
      setOrgs(res.data.orgs || []);
      const cur = (res.data.orgs || []).find(o => o.is_current);
      setCurrentOrg(cur || null);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleSwitch = async (org) => {
    if (org.is_current || switching) return;
    setSwitching(org.id);
    try {
      const res = await api.switchOrg(org.id);
      localStorage.setItem('aether_token', res.data.access_token);
      if (res.data.refresh_token) localStorage.setItem('aether_refresh_token', res.data.refresh_token);
      setOpen(false);
      navigate('/');
      window.location.reload();
    } catch {
      setSwitching(null);
    }
  };

  if (!currentOrg) return null;

  return (
    <div ref={ref} className="relative hidden sm:block">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-1.5 hover:border-violet-500/30 hover:bg-white/[0.06] transition-all duration-200"
        aria-label="Switch organisation"
        aria-expanded={open}
      >
        <Building2 className="w-3 h-3 text-slate-400" aria-hidden="true" />
        <span className="text-xs font-medium text-slate-300 max-w-[120px] truncate">{currentOrg.name}</span>
        <ChevronDown className={`w-3 h-3 text-slate-500 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {open && (
        <div
          className="absolute left-0 top-full mt-2 w-56 bg-[#0c0c14] border border-white/[0.08] rounded-2xl shadow-2xl shadow-black/50 z-50 overflow-hidden backdrop-blur-xl"
          role="menu"
          aria-label="Organisation list"
        >
          <div className="px-4 py-2.5 border-b border-white/[0.06]">
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Organisations</p>
          </div>
          {orgs.map(org => (
            <button
              key={org.id}
              role="menuitem"
              onClick={() => handleSwitch(org)}
              disabled={switching === org.id}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.04] transition-colors text-left disabled:opacity-60"
            >
              <div>
                <p className="text-sm font-medium text-white">{org.name}</p>
                <p className="text-[10px] text-slate-500 capitalize">{org.role} · {org.plan}</p>
              </div>
              {org.is_current
                ? <Check className="w-3.5 h-3.5 text-violet-400 shrink-0" aria-label="Current" />
                : switching === org.id && <span className="text-[10px] text-slate-500">Switching…</span>
              }
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const TopBar = ({ onNewProject, activeRunCount = 0 }) => {
  const [health, setHealth] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [costs, setCosts] = useState({ today_usd: 0, tokens_today: '—' });
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQ, setSearchQ] = useState('');
  const [fetchError, setFetchError] = useState('');
  const navigate = useNavigate();
  const location = useLocation();
  const isOnWizard = location.pathname === '/new';

  const { activeProvider, activeModel } = useSettings();

  useEffect(() => {
    const fetchHealth = async () => {
      try { setHealth((await api.getHealth()).data); } catch (err) {
        setFetchError(err.message || 'Health check failed');
      }
    };
    const fetchSystemStatus = async () => {
      try {
        const res = await api.client.get('/system/status');
        setSystemStatus(res.data);
      } catch {
        setSystemStatus(null);
      }
    };
    const fetchCosts = async () => {
      try { setCosts((await api.getCosts()).data); } catch (err) {
        setFetchError(err.message || 'Cost fetch failed');
      }
    };
    fetchHealth(); fetchSystemStatus(); fetchCosts();
    const iv = setInterval(() => { fetchHealth(); fetchSystemStatus(); fetchCosts(); }, 30_000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen(v => !v);
      }
      if (e.key === 'Escape') setSearchOpen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const handleSearch = (e) => {
    if (e.key === 'Enter' && searchQ.trim()) {
      navigate(`/search?q=${encodeURIComponent(searchQ.trim())}`);
      setSearchOpen(false);
      setSearchQ('');
    }
  };

  const derivedStatus = (() => {
    if (systemStatus) {
      const s = (systemStatus.status || '').toLowerCase();
      if (s === 'nominal' || s === 'ok' || s === 'healthy') return { label: systemStatus.message || systemStatus.status || 'Nominal', level: 'nominal' };
      if (s === 'warning' || s === 'degraded') return { label: systemStatus.message || systemStatus.status || 'Degraded', level: 'warning' };
      if (s === 'critical') return { label: systemStatus.message || 'Critical', level: 'critical' };
      return { label: systemStatus.status || 'Unknown', level: 'warning' };
    }
    if (health) {
      const ok = health.status === 'ok' || health.status === 'healthy';
      return { label: ok ? 'Nominal' : 'Degraded', level: ok ? 'nominal' : 'warning' };
    }
    return null;
  })();

  const statusConfig = derivedStatus ? {
    nominal:  { dot: 'bg-emerald-400', pill: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' },
    warning:  { dot: 'bg-amber-400 animate-pulse', pill: 'bg-amber-500/10 border-amber-500/20 text-amber-400' },
    critical: { dot: 'bg-red-400 animate-pulse', pill: 'bg-red-500/10 border-red-500/20 text-red-400' },
  }[derivedStatus.level] || { dot: 'bg-slate-400', pill: 'bg-white/[0.04] border-white/[0.08] text-slate-400' } : null;

  const providerStyle = PROVIDER_COLORS[activeProvider] || { text: 'text-slate-400', bg: 'bg-white/[0.04] border-white/[0.08]' };

  return (
    <>
      {/* Search overlay */}
      {searchOpen && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-black/70 backdrop-blur-sm"
          onClick={() => setSearchOpen(false)}
          role="presentation"
        >
          <div
            className="bg-[#0c0c14] border border-white/[0.10] rounded-2xl shadow-2xl shadow-black/50 w-full max-w-xl mx-4"
            role="dialog"
            aria-modal="true"
            aria-label="Search AetherOS"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 px-4 py-3.5 border-b border-white/[0.06]">
              <Search className="w-4 h-4 text-slate-400 shrink-0" aria-hidden="true" />
              <input
                autoFocus
                value={searchQ}
                onChange={e => setSearchQ(e.target.value)}
                onKeyDown={handleSearch}
                placeholder="Search runs, artifacts, code… (Enter to go)"
                aria-label="Search query"
                className="flex-1 bg-transparent text-white placeholder-slate-600 text-sm focus:outline-none"
              />
              <kbd className="text-[10px] text-slate-500 border border-white/[0.08] rounded-lg px-2 py-1 font-mono" aria-label="Press Escape to close">ESC</kbd>
            </div>
            <div className="px-4 py-2.5 text-xs text-slate-600" aria-live="polite">
              Press <kbd className="font-mono bg-white/[0.04] rounded px-1">Enter</kbd> to search · <kbd className="font-mono bg-white/[0.04] rounded px-1">Esc</kbd> to close
            </div>
          </div>
        </div>
      )}

      {fetchError && (
        <div className="bg-red-500/10 border-b border-red-500/20 px-6 py-1 flex items-center justify-between">
          <p className="text-red-400 text-xs">{fetchError}</p>
          <button onClick={() => setFetchError('')} className="text-slate-500 hover:text-white text-xs ml-4">×</button>
        </div>
      )}

      <header
        className="h-14 border-b border-white/[0.06] bg-[#050507]/80 backdrop-blur-xl flex items-center justify-between px-6 shrink-0 flex-1 min-w-0"
        role="banner"
      >
        {/* Left: active run pill */}
        <div className="flex items-center space-x-3">
          {activeRunCount > 0 && (
            <div
              className="flex items-center space-x-1.5 bg-violet-500/10 border border-violet-500/20 rounded-full px-3 py-1"
              role="status"
              aria-live="polite"
              aria-label={`${activeRunCount} pipeline run${activeRunCount !== 1 ? 's' : ''} in progress`}
            >
              <span className="relative flex h-2 w-2" aria-hidden="true">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-violet-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-violet-400" />
              </span>
              <span className="text-[11px] font-semibold text-violet-300">
                {activeRunCount} running
              </span>
            </div>
          )}
        </div>

        {/* Center: search + status */}
        <div className="flex items-center gap-4">
          <button
            onClick={() => setSearchOpen(true)}
            aria-label="Open search (Cmd+K)"
            aria-keyshortcuts="Meta+k Control+k"
            className="hidden md:flex items-center gap-2 bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-1.5 text-xs text-slate-500 hover:text-slate-300 hover:border-white/[0.12] hover:bg-white/[0.06] transition-all duration-200 w-48"
          >
            <Search className="w-3 h-3" aria-hidden="true" />
            <span>Search…</span>
            <kbd className="ml-auto font-mono bg-white/[0.04] rounded px-1 text-[10px]" aria-hidden="true">⌘K</kbd>
          </button>

          {derivedStatus && statusConfig && (
            <div className="flex items-center gap-2" role="status" aria-live="polite" aria-label={`System status: ${derivedStatus.label}`}>
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border ${statusConfig.pill}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${statusConfig.dot}`} aria-hidden="true" />
                {derivedStatus.label}
              </span>
            </div>
          )}
        </div>

        {/* Right: org + LLM + cost + actions */}
        <div className="flex items-center space-x-3">
          <OrgSwitcher />

          {/* Live LLM provider badge */}
          {activeProvider && (
            <div
              className={`hidden sm:flex items-center gap-1.5 border rounded-xl px-2.5 py-1 ${providerStyle.bg}`}
              aria-label={`Active LLM provider: ${activeProvider}`}
            >
              <Zap className={`w-3 h-3 ${providerStyle.text}`} aria-hidden="true" />
              <span className={`text-[10px] font-bold uppercase tracking-wider ${providerStyle.text}`}>
                {activeProvider}
              </span>
            </div>
          )}

          {/* Cost display — subtle */}
          <div
            className="hidden sm:flex items-center gap-1.5 text-xs text-slate-500"
            aria-label={`Today's spend: $${costs.today_usd?.toFixed(2) || '0.00'}`}
          >
            <Coins className="w-3 h-3 text-emerald-500" aria-hidden="true" />
            <span className="font-mono text-emerald-400 font-medium">${costs.today_usd?.toFixed(2) || '0.00'}</span>
          </div>

          <button
            onClick={() => isOnWizard ? null : navigate('/new')}
            disabled={isOnWizard}
            aria-label="Create new project"
            aria-disabled={isOnWizard}
            className="flex items-center space-x-1.5 bg-gradient-to-r from-violet-600 to-indigo-500 hover:from-violet-500 hover:to-indigo-400 transition-all duration-200 text-white text-xs font-semibold px-4 py-2 rounded-xl shadow-md shadow-violet-500/20 hover:shadow-violet-500/30 disabled:opacity-50 active:scale-95"
          >
            <Plus className="w-3.5 h-3.5" aria-hidden="true" />
            <span>New Project</span>
          </button>

          <NotificationBell />

          <button
            onClick={() => { api.logout?.(); api.clearToken?.(); navigate('/login'); }}
            aria-label="Sign out of AetherOS"
            className="text-slate-500 hover:text-red-400 transition-colors p-1.5 rounded-lg hover:bg-red-500/[0.06]"
          >
            <LogOut className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </header>
    </>
  );
};

export default TopBar;
