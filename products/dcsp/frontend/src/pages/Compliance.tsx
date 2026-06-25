import { useQuery } from '@tanstack/react-query';
import { Shield, Download, FileText, Clock, User, Activity } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import api from '../lib/api';

interface AuditEntry {
  id: string;
  timestamp: string;
  action: string;
  actor: string;
  repo_name?: string;
  details?: string;
  ip_address?: string;
}

const Compliance = () => {
  const { data: auditData } = useQuery({
    queryKey: ['audit-logs'],
    queryFn: () => api.get('/api/audit/logs').then(r => r.data),
    refetchInterval: 30_000,
  });

  const { data: compReport } = useQuery({
    queryKey: ['compliance-summary'],
    queryFn: () => api.get('/api/compliance/report').then(r => r.data).catch(() => null),
  });

  const logs: AuditEntry[] = auditData?.logs ?? [];

  const actionColor: Record<string, string> = {
    webhook_received: 'text-accent',
    patch_approved:   'text-success',
    patch_rejected:   'text-error',
    login:            'text-slate-400',
    pr_created:       'text-success',
    scan_started:     'text-warning',
  };

  return (
    <div className="space-y-7">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Compliance</h2>
          <p className="text-slate-500 text-xs mt-0.5">Full audit trail of every DCSP action</p>
        </div>
        <div className="flex gap-2">
          <a
            href="/api/compliance/csv"
            className="flex items-center gap-2 px-3 py-2 bg-surface border border-border hover:border-slate-500 text-slate-300 text-xs font-semibold rounded-md transition-colors"
          >
            <Download size={13} /> CSV
          </a>
          <a
            href="/api/compliance/report"
            className="flex items-center gap-2 px-3 py-2 bg-surface border border-border hover:border-slate-500 text-slate-300 text-xs font-semibold rounded-md transition-colors"
          >
            <FileText size={13} /> PDF Report
          </a>
        </div>
      </div>

      {/* Stats row */}
      {compReport && (
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Total Events',   value: compReport.total_events   ?? '—' },
            { label: 'Patches Applied',value: compReport.patches_applied ?? '—' },
            { label: 'Human Reviews',  value: compReport.human_reviews   ?? '—' },
          ].map(s => (
            <div key={s.label} className="bg-surface border border-border rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-white">{s.value}</p>
              <p className="text-xs text-slate-500 mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Audit log */}
      <div className="bg-surface border border-border rounded-lg overflow-hidden">
        <div className="px-5 py-3 border-b border-border flex items-center gap-2">
          <Activity size={14} className="text-slate-500" />
          <span className="text-white font-semibold text-sm">Audit Log</span>
          <span className="ml-auto text-xs text-slate-600">{logs.length} events</span>
        </div>

        <div className="divide-y divide-border max-h-[32rem] overflow-y-auto">
          {logs.length === 0 ? (
            <div className="py-14 text-center text-slate-500 text-sm">No audit events yet</div>
          ) : logs.map(entry => (
            <div key={entry.id} className="px-5 py-3 hover:bg-slate-800/30 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="mt-0.5 p-1.5 bg-background border border-border rounded">
                    <Shield size={12} className="text-slate-500" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-mono font-semibold ${actionColor[entry.action] ?? 'text-slate-300'}`}>
                        {entry.action}
                      </span>
                      {entry.repo_name && (
                        <span className="text-xs text-slate-600 truncate">{entry.repo_name}</span>
                      )}
                    </div>
                    {entry.details && (
                      <p className="text-xs text-slate-500 mt-0.5 truncate">{entry.details}</p>
                    )}
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-[10px] text-slate-600 flex items-center gap-1">
                        <User size={9} /> {entry.actor}
                      </span>
                      {entry.ip_address && (
                        <span className="text-[10px] text-slate-700 font-mono">{entry.ip_address}</span>
                      )}
                    </div>
                  </div>
                </div>
                <span className="text-[10px] text-slate-600 shrink-0 flex items-center gap-1 whitespace-nowrap">
                  <Clock size={9} />
                  {formatDistanceToNow(new Date(entry.timestamp))} ago
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Compliance;
