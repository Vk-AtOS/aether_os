import React, { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { LayoutDashboard, PlusCircle, List, Users, Settings } from 'lucide-react';
import ProviderBadge from './ProviderBadge';
import { api } from '../api';

const Sidebar = () => {
  const location = useLocation();
  const [latestRunId, setLatestRunId] = useState(null);

  // Fetch the most recent run once so we can link to its client portal
  useEffect(() => {
    api.listRuns()
      .then(res => {
        const runs = res.data || [];
        if (runs.length > 0) setLatestRunId(runs[0].id || runs[0].run_id || null);
      })
      .catch(() => {});
  }, []);

  const staticItems = [
    { name: 'Dashboard',   path: '/',         icon: LayoutDashboard },
    { name: 'New Project', path: '/new',       icon: PlusCircle },
    { name: 'Projects',    path: '/projects',  icon: List },
    { name: 'Settings',    path: '/settings',  icon: Settings },
  ];

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

      <nav className="flex-1 px-4 space-y-2 mt-4">
        {staticItems.map((item) => {
          const active = isActiveRoute(item.path);
          return (
            <NavLink
              key={item.name}
              to={item.path}
              className={linkClass(active)}
            >
              <item.icon className={`w-4 h-4 mr-3 ${active ? 'text-white' : ''}`} />
              {item.name}
            </NavLink>
          );
        })}

        {/* Client Portal — links to most recent run, or disabled when no runs exist */}
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

      <div className="p-4 border-t border-border">
        <ProviderBadge />
      </div>
    </aside>
  );
};

export default Sidebar;
