import React from 'react';
import { Check, X, Loader2, AlertCircle, Clock, StopCircle, Pause } from 'lucide-react';

const CONFIG = {
  // Pipeline-level statuses
  completed:   { bg: 'bg-emerald-500',    text: 'text-white',         border: 'border-emerald-600',    icon: Check,       label: 'COMPLETED' },
  passed:      { bg: 'bg-emerald-500/20', text: 'text-emerald-400',   border: 'border-emerald-500/40', icon: Check,       label: 'PASSED' },
  running:     { bg: 'bg-indigo-500/20',  text: 'text-indigo-400',    border: 'border-indigo-500/40',  icon: Loader2,     spin: true, label: 'RUNNING' },
  failed:      { bg: 'bg-red-500/20',     text: 'text-red-400',       border: 'border-red-500/40',     icon: X,           label: 'FAILED' },
  timeout:     { bg: 'bg-amber-500/20',   text: 'text-amber-400',     border: 'border-amber-500/40',   icon: AlertCircle, label: 'TIMEOUT' },
  pending:     { bg: 'bg-slate-700/30',   text: 'text-slate-400',     border: 'border-slate-600/30',   icon: Clock,       label: 'PENDING' },
  escalated:   { bg: 'bg-amber-500/20',   text: 'text-amber-400',     border: 'border-amber-500/40',   icon: AlertCircle, label: 'ESCALATED' },
  interrupted: { bg: 'bg-orange-500/20',  text: 'text-orange-400',    border: 'border-orange-500/40',  icon: StopCircle,  label: 'INTERRUPTED' },
  cancelled:   { bg: 'bg-slate-600/30',   text: 'text-slate-300',     border: 'border-slate-500/40',   icon: X,           label: 'CANCELLED' },
  paused:      { bg: 'bg-blue-500/20',    text: 'text-blue-400',      border: 'border-blue-500/40',    icon: Pause,       label: 'PAUSED' },
};

const PhaseBadge = ({ status, size = 'sm' }) => {
  const cfg = CONFIG[status] || CONFIG.pending;
  const Icon = cfg.icon;

  const sizeClass = size === 'sm'
    ? 'px-1.5 py-0.5 text-[10px]'
    : 'px-2.5 py-1 text-xs';

  return (
    <div
      className={`inline-flex items-center rounded border ${cfg.bg} ${cfg.text} ${cfg.border} ${sizeClass} font-bold tracking-wider`}
    >
      <Icon className={`w-3 h-3 mr-1 shrink-0 ${cfg.spin ? 'animate-spin' : ''}`} />
      <span className="uppercase">{cfg.label}</span>
    </div>
  );
};

export default PhaseBadge;
