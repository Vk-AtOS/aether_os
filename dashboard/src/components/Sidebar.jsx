import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { LayoutDashboard, PlusCircle, List, Users, Settings } from 'lucide-react';
import ProviderBadge from './ProviderBadge';

const Sidebar = () => {
  const location = useLocation();
  const navItems = [
    { name: 'Dashboard', path: '/', icon: LayoutDashboard },
    { name: 'New Project', path: '/new', icon: PlusCircle },
    { name: 'Projects', path: '/projects', icon: List },
    { name: 'Client Portal', path: '/portal/demo', icon: Users },
    { name: 'Settings', path: '/settings', icon: Settings },
  ];

  const isActiveRoute = (path) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  return (
    <aside className="w-60 bg-panel border-r border-border flex flex-col">
      <div className="p-6">
        <h1 className="text-xl font-bold text-bright tracking-wider">AetherOS Factory</h1>
        <p className="text-xs text-muted mt-1 uppercase">Factory Control</p>
      </div>
      
      <nav className="flex-1 px-4 space-y-2 mt-4">
        {navItems.map((item) => {
          const active = isActiveRoute(item.path);
          return (
            <NavLink
              key={item.name}
              to={item.path}
              className={`flex items-center px-4 py-2.5 text-sm font-medium rounded-md transition-colors ${
                active 
                  ? 'bg-indigo-600 text-white' 
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}
            >
              <item.icon className={`w-4 h-4 mr-3 ${active ? 'text-white' : ''}`} />
              {item.name}
            </NavLink>
          );
        })}
      </nav>

      <div className="p-4 border-t border-border">
        <ProviderBadge />
      </div>
    </aside>
  );
};

export default Sidebar;
