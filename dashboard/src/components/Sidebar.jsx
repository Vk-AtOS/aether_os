import React, { useState, useEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, PlusCircle, List, Users, Settings,
  Plug, Wrench, Brain, DollarSign, ChevronDown, ChevronRight,
  Shield, UserCircle, Webhook, LogOut,
} from 'lucide-react';
import ProviderBadge from './ProviderBadge';
import { api } from '../api';

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
  const [latestRunId, setLatestRunId] = useState(null);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [userRole, setUserRole] = useState('member');

  useEffect(() => {
    const token = api.getToken();
    if (token) {
      const payload = decodeToken(token);
      if (payload?.role) setUserRole(payload.role);
    }

    api.listRuns()
      .then(res => {
        const runs = res.data || [];
        if (runs.length > 0) setLatestRunId(runs[0].id || runs[0].run_id || null);
      })
      .catch(() => {});

    if (['/connectors', '/skills', '/memory', '/costs'].some(p => location.pathname.startsWith(p))) {
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
    { name: 'Dashboard',   path: '/',         icon: LayoutDashboard },
    !isViewer && { name: 'New Project', path: '/new-project', icon: PlusCircle },
    { name: 'Projects',    path: '/projects',  icon: List },
    { name: 'Settings',    path: '/settings',  icon: Settings },
    { name: 'Compliance',  path: '/compliance', icon: Shield },
  ].filter(Boolean);

  const toolItems = [
    { name: 'Connectors', path: '/connectors', icon: Plug },
    { name: 'Skills',     path: '/skills',     icon: Wrench },
    { name: 'Memory',     path: '/memory',     icon: Brain },
    { name: 'Costs',      path: '/costs',      icon: DollarSign },
    { name: 'Webhooks',   path: '/settings/webhooks', icon: Webhook },
  ];

  const adminItems = isAdmin ? [
    { name: 'Users',  path: '/admin/users', icon: Users },
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
    <aside className="w-60 bg-panel border-r border-border flex flex-col">
      <div className="p-6">
        <h1 className="text-xl font-bold text-bright tracking-wider">AetherOS Factory</h1>
        <p className="text-xs text-muted mt-1 uppercase">Factory Control</p>
      </div>

      <nav className="flex-1 px-4 space-y-2 mt-4 overflow-y-auto">
        {staticItems.map((item) => {
          const active = isActiveRoute(item.path);
          return (
            <NavLink key={item.name} to={item.path} className={linkClass(active)}>
              <item.icon className={`w-4 h-4 mr-3 ${active ? 'text-white' : ''}`} />
              {item.name}
            </NavLink>
          );
        })}

        {/* Tools section */}
        <button
          onClick={() => setToolsOpen(!toolsOpen)}
          className="flex items-center w-full px-4 py-2.5 text-sm font-medium rounded-md text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
        >
          <Wrench className="w-4 h-4 mr-3" />
          <span className="flex-1 text-left">Tools</span>
          {toolsOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        </button>
        {toolsOpen && toolItems.map((item) => {
          const active = location.pathname.startsWith(item.path);
          return (
            <NavLink key={item.name} to={item.path} className={`ml-3 ${linkClass(active)}`}>
              <item.icon className={`w-4 h-4 mr-3 ${active ? 'text-white' : ''}`} />
              {item.name}
            </NavLink>
          );
        })}

        {/* Admin section */}
        {adminItems.length > 0 && (
          <>
            <div className="px-4 pt-4 pb-1">
              <span className="text-[9px] font-bold text-muted/50 uppercase tracking-widest">Admin</span>
            </div>
            {adminItems.map((item) => {
              const active = location.pathname.startsWith(item.path);
              return (
                <NavLink key={item.name} to={item.path} className={linkClass(active)}>
                  <item.icon className={`w-4 h-4 mr-3 ${active ? 'text-white' : ''}`} />
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
          >
            <Users className={`w-4 h-4 mr-3 ${location.pathname.startsWith('/portal/') ? 'text-white' : ''}`} />
            Client Portal
          </NavLink>
        ) : (
          <div className="flex items-center px-4 py-2.5 text-sm font-medium rounded-md text-gray-600 cursor-default select-none">
            <Users className="w-4 h-4 mr-3" />
            <span>Client Portal</span>
            <span className="ml-auto text-[10px] text-gray-700 uppercase font-bold">no runs</span>
          </div>
        )}
      </nav>

      <div className="p-4 border-t border-border space-y-2">
        <NavLink
          to="/profile"
          className={linkClass(location.pathname.startsWith('/profile'))}
        >
          <UserCircle className="w-4 h-4 mr-3" />
          Profile
        </NavLink>
        <button
          onClick={handleLogout}
          className="flex items-center w-full px-4 py-2.5 text-sm font-medium rounded-md text-gray-400 hover:text-red-400 hover:bg-gray-800 transition-colors"
        >
          <LogOut className="w-4 h-4 mr-3" />
          Sign Out
        </button>
        <ProviderBadge />
      </div>
    </aside>
  );
};

export default Sidebar;
