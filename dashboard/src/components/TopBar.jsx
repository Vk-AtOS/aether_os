import React, { useState, useEffect, useRef } from 'react';
import { LogOut, Plus, Coins, Zap, Search, Building2, ChevronDown, Check } from 'lucide-react';
import { api } from '../api';
import { useNavigate, useLocation } from 'react-router-dom';
import NotificationBell from './NotificationBell';
import { useSettings } from '../contexts/SettingsContext';

const HexLogo = () => (
  <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
    <polygon points="14,2 25,8 25,20 14,26 3,20 3,8" fill="none" stroke="#6366f1" strokeWidth="1.5" />
    <polygon points="14,7 20,10.5 20,17.5 14,21 8,17.5 8,10.5" fill="#6366f1" opacity="0.25" />
    <circle cx="14" cy="14" r="3" fill="#6366f1" />
  </svg>
);

const PROVIDER_COLORS = {
  anthropic: 'text-orange-400',
  openrouter: 'text-purple-400',
  gemini: 'text-blue-400',
  ollama: 'text-green-400',
};

const OrgSwitcher = () => {
  const [open, setOpen] = useState(false);
  const [orgs, setOrgs] = useState([]);
  const [currentOrg, setCurrentOrg] = useState(null);
  const ref = useRef(null);

  useEffect(() => {
    api.getMyOrgs().then(res => {
      setOrgs(res.data.orgs || []);
      const cur = (res.data.orgs || []).find(o => o.is_current);
      setCurrentOrg(cur || null);
    }).catch(() => {});
  }, []);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  if (!currentOrg) return null;

  return (
    <div ref={ref} className="relative hidden sm:block">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 bg-border/20 border border-border/50 rounded-full px-2.5 py-1 hover:border-accent/40 transition-colors"
        aria-label="Switch organisation"
        aria-expanded={open}
      >
        <Building2 className="w-3 h-3 text-muted" aria-hidden="true" />
        <span className="text-[10px] font-bold text-muted max-w-[120px] truncate">{currentOrg.name}</span>
        <ChevronDown className={`w-3 h-3 text-muted transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {open && (
        <div
          className="absolute left-0 top-full mt-2 w-56 bg-panel border border-border rounded-xl shadow-2xl z-50 overflow-hidden"
          role="menu"
          aria-label="Organisation list"
        >
          <div className="px-4 py-2.5 border-b border-border">
            <p className="text-[10px] font-bold text-muted uppercase tracking-widest">Organisations</p>
          </div>
          {orgs.map(org => (
            <button
              key={org.id}
              role="menuitem"
              onClick={() => setOpen(false)}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors text-left"
            >
              <div>
                <p className="text-sm font-medium text-bright">{org.name}</p>
                <p className="text-[10px] text-muted capitalize">{org.role} · {org.plan}</p>
              </div>
              {org.is_current && <Check className="w-3.5 h-3.5 text-accent shrink-0" aria-label="Current" />}
            </button>
          ))}
          <div className="border-t border-border px-4 py-2">
            <p className="text-[10px] text-muted">Multi-org support coming soon</p>
          </div>
        </div>
      )}
    </div>
  );
};

const TopBar = ({ onNewProject, activeRunCount = 0 }) => {
  const [health, setHealth] = useState(null);
  const [costs, setCosts] = useState({ today_usd: 0, tokens_today: '—' });
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQ, setSearchQ] = useState('');
  const [fetchError, setFetchError] = useState('');
  const navigate = useNavigate();
  const location = useLocation();
  const isOnWizard = location.pathname === '/new-project';

  // Live settings from context — updates instantly when settings are saved
  const { activeProvider, activeModel } = useSettings();

  useEffect(() => {
    const fetchHealth = async () => {
      try { setHealth((await api.getHealth()).data); } catch (err) {
        setFetchError(err.message || 'Health check failed');
      }
    };
    const fetchCosts = async () => {
      try { setCosts((await api.getCosts()).data); } catch (err) {
        setFetchError(err.message || 'Cost fetch failed');
      }
    };
    fetchHealth(); fetchCosts();
    const iv = setInterval(() => { fetchHealth(); fetchCosts(); }, 30_000);
    return () => clearInterval(iv);
  }, []);

  // Keyboard shortcut: Cmd+K / Ctrl+K opens search
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

  const isHealthy = health?.status === 'ok' || health?.status === 'healthy';
  const providerColor = PROVIDER_COLORS[activeProvider] || 'text-muted';

  return (
    <>
      {/* Search overlay */}
      {searchOpen && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-black/60 backdrop-blur-sm"
          onClick={() => setSearchOpen(false)}
          role="presentation"
        >
          <div
            className="bg-panel border border-border rounded-2xl shadow-2xl w-full max-w-xl mx-4"
            role="dialog"
            aria-modal="true"
            aria-label="Search AetherOS"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
              <Search className="w-4 h-4 text-muted shrink-0" aria-hidden="true" />
              <input
                autoFocus
                value={searchQ}
                onChange={e => setSearchQ(e.target.value)}
                onKeyDown={handleSearch}
                placeholder="Search runs, artifacts, code… (Enter to go)"
                aria-label="Search query"
                className="flex-1 bg-transparent text-bright placeholder-muted text-sm focus:outline-none"
              />
              <kbd className="text-[10px] text-muted border border-border rounded px-1.5 py-0.5 font-mono" aria-label="Press Escape to close">ESC</kbd>
            </div>
            <div className="px-4 py-2.5 text-xs text-muted" aria-live="polite">
              Press <kbd className="font-mono bg-border/30 rounded px-1">Enter</kbd> to search · <kbd className="font-mono bg-border/30 rounded px-1">Esc</kbd> to close
            </div>
          </div>
        </div>
      )}

      {fetchError && (
        <div className="bg-red-500/10 border-b border-red-500/20 px-6 py-1 flex items-center justify-between">
          <p className="text-red-400 text-xs">{fetchError}</p>
          <button onClick={() => setFetchError('')} className="text-muted hover:text-bright text-xs ml-4">×</button>
        </div>
      )}
      <header className="h-14 border-b border-border bg-panel flex items-center justify-between px-6 shrink-0 flex-1 min-w-0" role="banner">
        {/* Left: Logo + active runs */}
        <div className="flex items-center space-x-3">
          <HexLogo aria-hidden="true" />
          <div className="flex items-baseline space-x-1.5" aria-label="AetherOS Factory">
            <span className="text-base font-bold text-bright tracking-tight">AetherOS</span>
            <span className="text-base font-light text-muted tracking-tight">Factory</span>
          </div>

          {activeRunCount > 0 && (
            <div
              className="flex items-center space-x-1.5 ml-4 bg-accent/10 border border-accent/30 rounded-full px-2.5 py-0.5"
              role="status"
              aria-live="polite"
              aria-label={`${activeRunCount} pipeline run${activeRunCount !== 1 ? 's' : ''} in progress`}
            >
              <span className="relative flex h-2 w-2" aria-hidden="true">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-accent" />
              </span>
              <span className="text-[10px] font-bold text-accent uppercase tracking-wider">
                {activeRunCount} running
              </span>
            </div>
          )}
        </div>

        {/* Center: search bar + system status */}
        <div className="flex items-center gap-4">
          {/* Inline search trigger */}
          <button
            onClick={() => setSearchOpen(true)}
            aria-label="Open search (Cmd+K)"
            aria-keyshortcuts="Meta+k Control+k"
            className="hidden md:flex items-center gap-2 bg-surface border border-border rounded-lg px-3 py-1.5 text-xs text-muted hover:text-bright hover:border-accent/40 transition-colors w-48"
          >
            <Search className="w-3 h-3" aria-hidden="true" />
            <span>Search…</span>
            <kbd className="ml-auto font-mono bg-border/30 rounded px-1 text-[10px]" aria-hidden="true">⌘K</kbd>
          </button>

          {health && (
            <div className="flex items-center text-xs space-x-4" role="status" aria-live="polite" aria-label={`System status: ${isHealthy ? 'Nominal' : 'Degraded'}`}>
              <div className="flex items-center space-x-1.5">
                <span className={`w-2 h-2 rounded-full ${isHealthy ? 'bg-success' : 'bg-warning animate-pulse'}`} aria-hidden="true" />
                <span className="text-muted">{isHealthy ? 'Nominal' : 'Degraded'}</span>
              </div>
              <div className="flex items-center space-x-1.5 border-l border-border pl-4" aria-label={`${costs.tokens_today || '0'} tokens used today`}>
                <Coins className="w-3.5 h-3.5 text-accent" aria-hidden="true" />
                <span className="text-muted">{costs.tokens_today || '—'} tokens</span>
              </div>
            </div>
          )}
        </div>

        {/* Right: Org switcher + LLM badge + cost + actions */}
        <div className="flex items-center space-x-3">
          <OrgSwitcher />

          {/* Live LLM provider — updates instantly when settings change */}
          <div
            className="hidden sm:flex items-center gap-1.5 bg-border/20 border border-border/50 rounded-full px-2.5 py-1"
            aria-label={`Active LLM provider: ${activeProvider}`}
          >
            <Zap className={`w-3 h-3 ${providerColor}`} aria-hidden="true" />
            <span className={`text-[10px] font-bold uppercase tracking-wider ${providerColor}`}>
              {activeProvider}
            </span>
          </div>

          <div
            className="bg-border/30 px-3 py-1 rounded-full flex items-center space-x-1.5 border border-border"
            aria-label={`Today's spend: $${costs.today_usd?.toFixed(2) || '0.00'}`}
          >
            <span className="text-xs font-mono font-medium text-success">
              ${costs.today_usd?.toFixed(2) || '0.00'}
            </span>
            <span className="text-[10px] text-muted" aria-hidden="true">today</span>
          </div>

          <button
            onClick={() => isOnWizard ? null : navigate('/new-project')}
            disabled={isOnWizard}
            aria-label="Create new project"
            aria-disabled={isOnWizard}
            className="flex items-center space-x-1.5 bg-accent hover:bg-accent/90 transition-colors text-white text-xs font-bold px-4 py-2 rounded-lg disabled:opacity-50"
          >
            <Plus className="w-3.5 h-3.5" aria-hidden="true" />
            <span>New Project</span>
          </button>

          <NotificationBell />

          <button
            onClick={() => { api.logout?.(); api.clearToken?.(); navigate('/login'); }}
            aria-label="Sign out of AetherOS"
            className="text-muted hover:text-danger transition-colors p-1.5"
          >
            <LogOut className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </header>
    </>
  );
};

export default TopBar;
