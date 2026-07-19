import React, { useState, useEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, PlusCircle, List, Users, Settings,
  Plug, Wrench, Brain, DollarSign, ChevronDown, ChevronRight,
  Shield, UserCircle, Webhook, LogOut, Layout, Database, MessageSquare, Store,
  ScrollText, CreditCard, Building2, GraduationCap, Search, Cpu, Rocket,
  Activity, Sparkles, Zap, Bot, ShieldAlert, Wand2,
} from 'lucide-react';
import ProviderBadge from './ProviderBadge';
import { api } from '../api';
import { useRuns } from '../contexts/RunsContext';
import { useSettings } from '../contexts/SettingsContext';

const decodeToken = (token) => {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    return JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return null;
  }
};

const Sidebar = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { latestRunId } = useRuns();
  const { orgName } = useSettings();
  const [toolsOpen, setToolsOpen] = useState(false);
  const [platformOpen, setPlatformOpen] = useState(false);
  const [userRole, setUserRole] = useState('member');
  const [userEmail, setUserEmail] = useState('');

  useEffect(() => {
    const token = api.getToken();
    if (token) {
      const payload = decodeToken(token);
      if (payload?.role) setUserRole(payload.role);
      if (payload?.sub) setUserEmail(payload.sub);
    }

    if (['/connectors', '/skills', '/memory', '/costs', '/learning', '/settings/webhooks',
         '/frontend-builder', '/backend-builder', '/prompt'].some(p => location.pathname.startsWith(p))) {
      setToolsOpen(true);
    }
    if (['/intelligence', '/health', '/guardian', '/agents', '/compliance'].some(p => location.pathname.startsWith(p))) {
      setPlatformOpen(true);
    }
  }, [location.pathname]);

  const handleLogout = async () => {
    try { await api.client.post('/auth/logout'); } catch { /* ignore */ }
    api.clearToken();
    navigate('/login', { replace: true });
  };

  const isAdmin = ['owner', 'admin'].includes(userRole);
  const isViewer = userRole === 'viewer';

  const staticItems = [
    { name: 'Dashboard',     path: '/',            icon: LayoutDashboard },
    !isViewer && { name: 'New Project',   path: '/new',         icon: Wand2 },
    { name: 'Projects',      path: '/projects',    icon: List },
    { name: 'Workspaces',    path: '/workspaces',  icon: Building2 },
    { name: 'Search',        path: '/search',      icon: Search },
    { name: 'Deployments',   path: '/deployments', icon: Rocket },
    { name: 'Marketplace',   path: '/marketplace', icon: Store },
    { name: 'Settings',      path: '/settings',    icon: Settings },
  ].filter(Boolean);

  const platformItems = [
    { name: 'Intelligence',  path: '/intelligence', icon: Sparkles },
    { name: 'System Health', path: '/health',       icon: Activity },
    { name: 'Guardian',      path: '/guardian',     icon: ShieldAlert },
    { name: 'Agents',        path: '/agents',       icon: Bot },
    { name: 'Compliance',    path: '/compliance',   icon: Shield },
  ];

  const toolItems = [
    { name: 'Connectors',       path: '/connectors',        icon: Plug },
    { name: 'Skills',           path: '/skills',            icon: Wrench },
    { name: 'Memory',           path: '/memory',            icon: Brain },
    { name: 'Costs',            path: '/costs',             icon: DollarSign },
    { name: 'Webhooks',         path: '/settings/webhooks', icon: Webhook },
    { name: 'Learning',         path: '/learning',          icon: GraduationCap },
    // FE-H5: previously orphan routes — now discoverable via the Tools section
    { name: 'Frontend Builder', path: '/frontend-builder',  icon: Layout },
    { name: 'Backend Builder',  path: '/backend-builder',   icon: Database },
    { name: 'Prompt',           path: '/prompt',            icon: MessageSquare },
  ];

  const adminItems = isAdmin ? [
    { name: 'Users',        path: '/admin/users',        icon: Users },
    { name: 'Audit Logs',   path: '/audit',              icon: ScrollText },
    { name: 'Billing',      path: '/admin/billing',      icon: CreditCard },
    { name: 'Intelligence', path: '/admin/intelligence', icon: Sparkles },
  ] : [];

  const isActiveRoute = (path) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  const linkClass = (active) =>
    `flex items-center px-3 py-2.5 text-sm font-medium rounded-xl transition-all duration-200 ${
      active
        ? 'bg-gradient-to-r from-violet-600/20 to-transparent border-r-2 border-violet-500 text-white'
        : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]'
    }`;

  const subLinkClass = (active) =>
    `flex items-center px-3 py-2 text-sm font-medium rounded-xl transition-all duration-200 ml-3 ${
      active
        ? 'text-violet-300 bg-violet-500/10'
        : 'text-slate-500 hover:text-slate-300 hover:bg-white/[0.03]'
    }`;

  return (
    <aside className="w-60 bg-[#0a0a10] border-r border-white/[0.06] flex flex-col h-full" role="navigation" aria-label="Main navigation">
      {/* Logo */}
      <div className="p-5 border-b border-white/[0.06]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-600 to-indigo-500 flex items-center justify-center flex-shrink-0 shadow-lg shadow-violet-500/20">
            <span className="text-white text-xs font-bold">A</span>
          </div>
          <div>
            <h1 className="text-sm font-bold text-white tracking-tight">AetherOS</h1>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <span className="text-[10px] text-slate-500 font-medium">v1.0</span>
            </div>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-3 space-y-0.5 mt-3 overflow-y-auto pb-2" aria-label="Sidebar navigation">
        {staticItems.map((item) => {
          const active = isActiveRoute(item.path);
          return (
            <NavLink
              key={item.name}
              to={item.path}
              className={linkClass(active)}
              aria-current={active ? 'page' : undefined}
            >
              <item.icon className={`w-4 h-4 mr-3 flex-shrink-0 ${active ? 'text-violet-400' : ''}`} aria-hidden="true" />
              {item.name}
            </NavLink>
          );
        })}

        {/* Platform section */}
        <div className="pt-2">
          <button
            onClick={() => setPlatformOpen(!platformOpen)}
            aria-expanded={platformOpen}
            aria-controls="platform-submenu"
            className="flex items-center w-full px-3 py-2 text-xs font-bold rounded-xl text-slate-500 hover:text-slate-300 hover:bg-white/[0.03] transition-all uppercase tracking-widest"
          >
            <Sparkles className="w-3.5 h-3.5 mr-2.5" aria-hidden="true" />
            <span className="flex-1 text-left">Platform</span>
            {platformOpen
              ? <ChevronDown className="w-3 h-3" aria-hidden="true" />
              : <ChevronRight className="w-3 h-3" aria-hidden="true" />}
          </button>
          <div id="platform-submenu" role="region" aria-label="Platform submenu">
            {platformOpen && platformItems.map((item) => {
              const active = location.pathname.startsWith(item.path);
              return (
                <NavLink
                  key={item.name}
                  to={item.path}
                  className={subLinkClass(active)}
                  aria-current={active ? 'page' : undefined}
                >
                  <item.icon className={`w-3.5 h-3.5 mr-2.5 flex-shrink-0 ${active ? 'text-violet-400' : ''}`} aria-hidden="true" />
                  {item.name}
                </NavLink>
              );
            })}
          </div>
        </div>

        {/* Tools section */}
        <div className="pt-1">
          <button
            onClick={() => setToolsOpen(!toolsOpen)}
            aria-expanded={toolsOpen}
            aria-controls="tools-submenu"
            className="flex items-center w-full px-3 py-2 text-xs font-bold rounded-xl text-slate-500 hover:text-slate-300 hover:bg-white/[0.03] transition-all uppercase tracking-widest"
          >
            <Wrench className="w-3.5 h-3.5 mr-2.5" aria-hidden="true" />
            <span className="flex-1 text-left">Tools</span>
            {toolsOpen
              ? <ChevronDown className="w-3 h-3" aria-hidden="true" />
              : <ChevronRight className="w-3 h-3" aria-hidden="true" />}
          </button>
          <div id="tools-submenu" role="region" aria-label="Tools submenu">
            {toolsOpen && toolItems.map((item) => {
              const active = location.pathname.startsWith(item.path);
              return (
                <NavLink
                  key={item.name}
                  to={item.path}
                  className={subLinkClass(active)}
                  aria-current={active ? 'page' : undefined}
                >
                  <item.icon className={`w-3.5 h-3.5 mr-2.5 flex-shrink-0 ${active ? 'text-violet-400' : ''}`} aria-hidden="true" />
                  {item.name}
                </NavLink>
              );
            })}
          </div>
        </div>

        {/* Admin section */}
        {adminItems.length > 0 && (
          <div className="pt-2">
            <div className="px-3 pt-2 pb-1" role="separator" aria-label="Admin section">
              <span className="text-[9px] font-bold text-slate-600 uppercase tracking-widest">Admin</span>
            </div>
            {adminItems.map((item) => {
              const active = location.pathname.startsWith(item.path);
              return (
                <NavLink
                  key={item.name}
                  to={item.path}
                  className={subLinkClass(active)}
                  aria-current={active ? 'page' : undefined}
                >
                  <item.icon className={`w-3.5 h-3.5 mr-2.5 flex-shrink-0 ${active ? 'text-violet-400' : ''}`} aria-hidden="true" />
                  {item.name}
                </NavLink>
              );
            })}
          </div>
        )}

        {/* Client Portal */}
        <div className="pt-1">
          {latestRunId ? (
            <NavLink
              to={`/portal/${latestRunId}`}
              className={linkClass(location.pathname.startsWith('/portal/'))}
              aria-current={location.pathname.startsWith('/portal/') ? 'page' : undefined}
            >
              <Users className={`w-4 h-4 mr-3 flex-shrink-0 ${location.pathname.startsWith('/portal/') ? 'text-violet-400' : ''}`} aria-hidden="true" />
              Client Portal
            </NavLink>
          ) : (
            <div
              className="flex items-center px-3 py-2.5 text-sm font-medium rounded-xl text-slate-600 cursor-default select-none"
              aria-disabled="true"
              aria-label="Client Portal — no runs available"
            >
              <Users className="w-4 h-4 mr-3 flex-shrink-0" aria-hidden="true" />
              <span className="flex-1">Client Portal</span>
              <span className="text-[10px] text-slate-700 uppercase font-bold" aria-hidden="true">no runs</span>
            </div>
          )}
        </div>
      </nav>

      {/* Bottom user section */}
      <div className="p-3 border-t border-white/[0.06] space-y-1">
        {/* Org context */}
        {orgName && (
          <div className="px-3 py-2.5 mb-1 flex items-center gap-2.5 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <Building2 className="w-3.5 h-3.5 text-violet-400 shrink-0" />
            <div className="min-w-0">
              <div className="text-[9px] font-bold text-slate-600 uppercase tracking-widest">Organisation</div>
              <div className="text-xs font-semibold text-white truncate">{orgName}</div>
            </div>
          </div>
        )}
        <NavLink
          to="/profile"
          className={linkClass(location.pathname.startsWith('/profile'))}
          aria-current={location.pathname.startsWith('/profile') ? 'page' : undefined}
          aria-label={userEmail ? `Profile — ${userEmail}` : 'Profile'}
        >
          <UserCircle className="w-4 h-4 mr-3 flex-shrink-0" aria-hidden="true" />
          {userEmail ? <span className="truncate">{userEmail.split('@')[0]}</span> : 'Profile'}
        </NavLink>
        <button
          onClick={handleLogout}
          aria-label="Sign out of AetherOS"
          className="flex items-center w-full px-3 py-2.5 text-sm font-medium rounded-xl text-slate-400 hover:text-red-400 hover:bg-red-500/[0.06] transition-all duration-200"
        >
          <LogOut className="w-4 h-4 mr-3 flex-shrink-0" aria-hidden="true" />
          Sign Out
        </button>
        {/* LLM badge */}
        <div className="px-3 pt-1">
          <ProviderBadge />
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
