import React, { useState, useEffect } from 'react';
import { LogOut, Plus, Coins } from 'lucide-react';
import { api } from '../api';
import { useNavigate } from 'react-router-dom';

// Hexagon SVG logo mark
const HexLogo = () => (
  <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
    <polygon
      points="14,2 25,8 25,20 14,26 3,20 3,8"
      fill="none"
      stroke="#6366f1"
      strokeWidth="1.5"
    />
    <polygon
      points="14,7 20,10.5 20,17.5 14,21 8,17.5 8,10.5"
      fill="#6366f1"
      opacity="0.25"
    />
    <circle cx="14" cy="14" r="3" fill="#6366f1" />
  </svg>
);

const TopBar = ({ onNewProject, activeRunCount = 0 }) => {
  const [health, setHealth] = useState(null);
  const [costs, setCosts] = useState({ today_usd: 0, tokens_today: '—' });
  const navigate = useNavigate();

  const fetchHealth = async () => {
    try {
      const res = await api.getHealth();
      setHealth(res.data);
    } catch {}
  };

  const fetchCosts = async () => {
    try {
      const res = await api.getCosts();
      setCosts(res.data);
    } catch {}
  };

  useEffect(() => {
    fetchHealth();
    fetchCosts();
    const interval = setInterval(() => {
      fetchHealth();
      fetchCosts();
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  const isHealthy = health?.status === 'ok' || health?.status === 'healthy';

  return (
    <header className="h-14 border-b border-border bg-panel flex items-center justify-between px-6 shrink-0">
      {/* Left: Logo + title */}
      <div className="flex items-center space-x-3">
        <HexLogo />
        <div className="flex items-baseline space-x-1.5">
          <span className="text-base font-bold text-bright tracking-tight">AetherOS</span>
          <span className="text-base font-light text-muted tracking-tight">Factory</span>
        </div>

        {/* Active runs pulse indicator */}
        {activeRunCount > 0 && (
          <div className="flex items-center space-x-1.5 ml-4 bg-accent/10 border border-accent/30 rounded-full px-2.5 py-0.5">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-accent" />
            </span>
            <span className="text-[10px] font-bold text-accent uppercase tracking-wider">
              {activeRunCount} running
            </span>
          </div>
        )}
      </div>

      {/* Center: system status */}
      {health && (
        <div className="flex items-center text-xs space-x-4">
          <div className="flex items-center space-x-1.5">
            <span
              className={`w-2 h-2 rounded-full ${isHealthy ? 'bg-success' : 'bg-warning animate-pulse'}`}
            />
            <span className="text-muted">
              {isHealthy ? 'Nominal' : 'Degraded'}
            </span>
          </div>
          <div className="flex items-center space-x-1.5 border-l border-border pl-4">
            <Coins className="w-3.5 h-3.5 text-accent" />
            <span className="text-muted">{costs.tokens_today || '—'} tokens</span>
          </div>
        </div>
      )}

      {/* Right: actions */}
      <div className="flex items-center space-x-3">
        <div className="bg-border/30 px-3 py-1 rounded-full flex items-center space-x-1.5 border border-border">
          <span className="text-xs font-mono font-medium text-success">
            ${costs.today_usd?.toFixed(2) || '0.00'}
          </span>
          <span className="text-[10px] text-muted">today</span>
        </div>

        <button
          onClick={onNewProject}
          className="flex items-center space-x-1.5 bg-accent hover:bg-accent/90 transition-colors text-white text-xs font-bold px-4 py-2 rounded-lg"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>New Project</span>
        </button>

        <button
          onClick={() => { api.logout(); navigate('/login'); }}
          className="text-muted hover:text-danger transition-colors p-1.5"
          title="Sign out"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};

export default TopBar;
