import React, { useState, useEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, PlusCircle, List, Users, Settings,
  Plug, Wrench, Brain, DollarSign, ChevronDown, ChevronRight,
  Shield, UserCircle, Webhook, LogOut, Layout, Database, MessageSquare, Store,
  ScrollText, CreditCard, Building2, GraduationCap, Search, Cpu, Rocket,
  Activity, Sparkles, Zap,
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
  const [userRole, setUserRole] = useState('member');
  const [userEmail, setUserEmail] = useState('');

  useEffect(() => {
    const token = api.getToken();
    if (token) {
      const payload = decodeToken(token);
      if (payload?.role) setUserRole(payload.role);
      if (payload?.sub) setUserEmail(payload.sub);
    }

    if (['/connectors', '/skills', '/memory', '/costs', '/frontend-builder', '/backend-builder', '/prompt', '/learning', '/settings/webhooks'].some(p => location.pathname.startsWith(p))) {
      setToolsOpen(true);
    }
  }, []);

  const handleLogout = async () => {
    try { await api.client.post('/auth/logout'); } catch { /* ignore */ }
    api.clearToken();
    navigate('/login', { replace: true });
  };

  const isAdmin = ['owner', 'admin'].includes(userRole);
  const isViewer = userRole === 'viewer';

  const staticItems = [
    { name: 'Dashboard',   path: '/',              icon: LayoutDashboard },
    !isViewer && { name: 'New Project', path: '/new-project', icon: PlusCircle },
    { name: 'Projects',    path: '/projects',      icon: List },
    { name: 'Search',      path: '/search',        icon: Search },
    { name: 'Deployments', path: '/deployments',   icon: Rocket },
    { name: 'Marketplace', path: '/marketplace',   icon: Store },
    { name: 'Intelligence',path: '/intelligence',  icon: Sparkles },
    { name: 'System Health',path: '/health',       icon: Activity },
    { name: 'Pricing',      path: '/pricing',      icon: Zap },
    { name: 'Settings',    path: '/settings',      icon: Settings },
    { name: 'Compliance',  path: '/compliance',    icon: Shield },
    { name: 'Profile',     path: '/profile',       icon: UserCircle },
  ].filter(Boolean);

  const toolItems = [
    { name: 'Connectors', path: '/connectors', icon: Plug },
    { name: 'Skills',     path: '/skills',     icon: Wrench },
    { name: 'Memory',     path: '/memory',     icon: Brain },
    { name: 'Costs',      path: '/costs',      icon: DollarSign },
    { name: 'Webhooks',   path: '/settings/webhooks', icon: Webhook },
    { name: 'Frontend Builder', path: '/frontend-builder', icon: Layout },
    { name: 'Backend Builder',  path: '/backend-builder',  icon: Database },
    { name: 'Prompt Input',     path: '/prompt',            icon: MessageSquare },
    { name: 'Learning',         path: '/learning',          icon: GraduationCap },
  ];

  const adminItems = isAdmin ? [
    { name: 'Users',      path: '/admin/users',    icon: Users },
    { name: 'Audit Logs', path: '/audit',          icon: ScrollText },
    { name: 'Billing',    path: '/admin/billing',  icon: CreditCard },
  ] : [];

  const isActiveRoute = (path) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  const linkClass = (active) =>
    `flex items-center px-4 py-2.5 text-sm font-medium rounded-md transition-colors ${
      active
        ? 'bg-indigo-600 text-white'
        : 'text-gray-400 hover:text-white hover:bg-gray-800'
    }`;

  return (
    <aside className="w-60 bg-panel border-r border-border flex flex-col h-full" role="navigation" aria-label="Main navigation">
      <div className="p-6">
        <h1 className="text-xl font-bold text-bright tracking-wider">AetherOS Factory</h1>
        <p className="text-xs text-muted mt-1 uppercase">Factory Control</p>
      </div>

      <nav className="flex-1 px-4 space-y-2 mt-4 overflow-y-auto" aria-label="Sidebar navigation">
        {staticItems.map((item) => {
          const active = isActiveRoute(item.path);
          return (
            <NavLink
              key={item.name}
              to={item.path}
              className={linkClass(active)}
              aria-current={active ? 'page' : undefined}
            >
              <item.icon className={`w-4 h-4 mr-3 ${active ? 'text-white' : ''}`} aria-hidden="true" />
              {item.name}
            </NavLink>
          );
        })}

        {/* Tools section */}
        <button
          onClick={() => setToolsOpen(!toolsOpen)}
          aria-expanded={toolsOpen}
          aria-controls="tools-submenu"
          className="flex items-center w-full px-4 py-2.5 text-sm font-medium rounded-md text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
        >
          <Wrench className="w-4 h-4 mr-3" aria-hidden="true" />
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
                className={`ml-3 ${linkClass(active)}`}
                aria-current={active ? 'page' : undefined}
              >
                <item.icon className={`w-4 h-4 mr-3 ${active ? 'text-white' : ''}`} aria-hidden="true" />
                {item.name}
              </NavLink>
            );
          })}
        </div>

        {/* Admin section */}
        {adminItems.length > 0 && (
          <>
            <div className="px-4 pt-4 pb-1" role="separator" aria-label="Admin section">
              <span className="text-[9px] font-bold text-muted/50 uppercase tracking-widest">Admin</span>
            </div>
            {adminItems.map((item) => {
              const active = location.pathname.startsWith(item.path);
              return (
                <NavLink
                  key={item.name}
                  to={item.path}
                  className={linkClass(active)}
                  aria-current={active ? 'page' : undefined}
                >
                  <item.icon className={`w-4 h-4 mr-3 ${active ? 'text-white' : ''}`} aria-hidden="true" />
                  {item.name}
                </NavLink>
              );
            })}
          </>
        )}

        {/* Client Portal */}
        {latestRunId ? (
          <NavLink
            to={`/portal/${latestRunId}`}
            className={linkClass(location.pathname.startsWith('/portal/'))}
            aria-current={location.pathname.startsWith('/portal/') ? 'page' : undefined}
          >
            <Users className={`w-4 h-4 mr-3 ${location.pathname.startsWith('/portal/') ? 'text-white' : ''}`} aria-hidden="true" />
            Client Portal
          </NavLink>
        ) : (
          <div
            className="flex items-center px-4 py-2.5 text-sm font-medium rounded-md text-gray-600 cursor-default select-none"
            aria-disabled="true"
            aria-label="Client Portal — no runs available"
          >
            <Users className="w-4 h-4 mr-3" aria-hidden="true" />
            <span>Client Portal</span>
            <span className="ml-auto text-[10px] text-gray-700 uppercase font-bold" aria-hidden="true">no runs</span>
          </div>
        )}
      </nav>

      <div className="p-4 border-t border-border space-y-2">
        {/* Org context */}
        {orgName && (
          <div className="px-4 py-2 mb-1 flex items-center gap-2 rounded-md bg-border/20 border border-border/50">
            <Building2 className="w-3.5 h-3.5 text-accent shrink-0" />
            <div className="min-w-0">
              <div className="text-[9px] font-bold text-muted/60 uppercase tracking-widest">Organisation</div>
              <div className="text-xs font-semibold text-bright truncate">{orgName}</div>
            </div>
          </div>
        )}
        <NavLink
          to="/profile"
          className={linkClass(location.pathname.startsWith('/profile'))}
          aria-current={location.pathname.startsWith('/profile') ? 'page' : undefined}
          aria-label={userEmail ? `Profile — ${userEmail}` : 'Profile'}
        >
          <UserCircle className="w-4 h-4 mr-3" aria-hidden="true" />
          {userEmail ? <span className="truncate">{userEmail.split('@')[0]}</span> : 'Profile'}
        </NavLink>
        <button
          onClick={handleLogout}
          aria-label="Sign out of AetherOS"
          className="flex items-center w-full px-4 py-2.5 text-sm font-medium rounded-md text-gray-400 hover:text-red-400 hover:bg-gray-800 transition-colors"
        >
          <LogOut className="w-4 h-4 mr-3" aria-hidden="true" />
          Sign Out
        </button>
        <ProviderBadge />
      </div>
    </aside>
  );
};

export default Sidebar;
