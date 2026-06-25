import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom';
import {
  Activity,
  GitBranch,
  GitPullRequest,
  ScanSearch,
  Layers,
  Cpu,
  Bell,
  Shield,
  Settings as SettingsIcon,
  LogOut,
  Zap,
  Search,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import api from '../lib/api';

const NAV_MAIN = [
  { name: 'Live Feed',     path: '/feed',         icon: Activity },
  { name: 'Repositories',  path: '/repositories', icon: GitBranch },
  { name: 'Patches',       path: '/patches',      icon: GitPullRequest },
  { name: 'Scan',          path: '/scan',         icon: ScanSearch },
  { name: 'Patterns',      path: '/patterns',     icon: Layers },
];

const NAV_CONFIG = [
  { name: 'AI Engine',     path: '/ai-engine',    icon: Cpu },
  { name: 'Notifications', path: '/notifications',icon: Bell },
  { name: 'Compliance',    path: '/compliance',   icon: Shield },
  { name: 'Settings',      path: '/settings',     icon: SettingsIcon },
];

const Layout = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [wsLive, setWsLive] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = (import.meta.env.VITE_WS_HOST as string) || window.location.host;
    let ws: WebSocket;
    const connect = () => {
      ws = new WebSocket(`${proto}://${host}/ws/dashboard`);
      ws.onopen = () => setWsLive(true);
      ws.onclose = () => { setWsLive(false); setTimeout(connect, 3000); };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => ws?.close();
  }, []);

  useEffect(() => {
    api.get('/api/jobs?status=pending').then(r => {
      setPendingCount(r.data?.total ?? 0);
    }).catch(() => {});
  }, [location.pathname]);

  const handleLogout = async () => {
    try { await api.get('/logout'); } catch { /* ignore */ }
    navigate('/login');
  };

  const isActive = (path: string) => location.pathname.startsWith(path);

  const NavItem = ({ name, path, icon: Icon }: { name: string; path: string; icon: React.ElementType }) => (
    <Link
      to={path}
      className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors relative ${
        isActive(path)
          ? 'bg-accent/10 text-accent'
          : 'text-slate-400 hover:bg-slate-800 hover:text-white'
      }`}
    >
      <Icon size={16} />
      <span>{name}</span>
      {path === '/patches' && pendingCount > 0 && (
        <span className="ml-auto text-[10px] font-bold bg-warning/20 text-warning border border-warning/30 rounded-full px-1.5 py-0.5 min-w-[18px] text-center">
          {pendingCount}
        </span>
      )}
    </Link>
  );

  return (
    <div className="flex h-screen bg-background">
      <aside className="w-56 border-r border-border bg-surface flex flex-col shrink-0">
        {/* Logo */}
        <div className="px-5 py-5 flex items-center gap-2.5">
          <Zap size={20} className="text-accent fill-accent" />
          <span className="text-lg font-bold text-white tracking-tight">DCSP</span>
          <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest ml-auto mt-0.5">Beta</span>
        </div>

        {/* Live status pill */}
        <div className="mx-4 mb-4 flex items-center gap-2 px-3 py-1.5 bg-background rounded-full border border-border">
          <span className={`w-1.5 h-1.5 rounded-full ${wsLive ? 'bg-success shadow-[0_0_6px_#3fb950]' : 'bg-slate-600'}`} />
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
            {wsLive ? 'Live' : 'Offline'}
          </span>
        </div>

        {/* Main nav */}
        <nav className="flex-1 px-3 space-y-0.5 overflow-y-auto">
          {NAV_MAIN.map(item => <NavItem key={item.path} {...item} />)}

          <div className="pt-4 pb-1 px-3">
            <span className="text-[9px] font-bold text-slate-600 uppercase tracking-widest">Configure</span>
          </div>

          {NAV_CONFIG.map(item => <NavItem key={item.path} {...item} />)}
        </nav>

        {/* Bottom */}
        <div className="p-3 border-t border-border">
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-3 py-2 w-full text-slate-400 hover:text-error hover:bg-error/5 rounded-md transition-colors text-sm font-medium"
          >
            <LogOut size={16} />
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-14 border-b border-border bg-surface flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center gap-2 bg-background border border-border rounded-md px-3 py-1.5 w-80">
            <Search size={14} className="text-slate-500" />
            <input
              type="text"
              placeholder="Search jobs, repos, patterns…"
              className="bg-transparent border-none text-xs focus:ring-0 text-white w-full placeholder:text-slate-600"
            />
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500">
              {new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
            </span>
            <div className="w-7 h-7 rounded-full bg-accent/20 border border-accent/30 flex items-center justify-center">
              <span className="text-[10px] font-bold text-accent">AD</span>
            </div>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-7">
          <Outlet />
        </div>
      </main>
    </div>
  );
};

export default Layout;
