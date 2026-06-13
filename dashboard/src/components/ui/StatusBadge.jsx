export function StatusBadge({ status }) {
  const config = {
    completed:   { label: 'Completed',   cls: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
    passed:      { label: 'Completed',   cls: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
    running:     { label: 'Running',     cls: 'bg-blue-500/10 text-blue-400 border-blue-500/20 animate-pulse' },
    interrupted: { label: 'Interrupted', cls: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
    cancelled:   { label: 'Cancelled',   cls: 'bg-slate-500/10 text-slate-400 border-slate-500/20' },
    pending:     { label: 'Pending',     cls: 'bg-violet-500/10 text-violet-400 border-violet-500/20' },
    failed:      { label: 'Failed',      cls: 'bg-red-500/10 text-red-400 border-red-500/20' },
    paused:      { label: 'Paused',      cls: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' },
  };
  const { label, cls } = config[status?.toLowerCase()] || config.pending;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border ${cls}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}
