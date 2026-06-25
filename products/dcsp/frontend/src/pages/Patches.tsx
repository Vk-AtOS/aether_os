import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  GitPullRequest, CheckCircle2, XCircle, Clock, ChevronDown, ChevronUp,
  Loader2, AlertCircle, RefreshCcw
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import api from '../lib/api';

interface Job {
  id: string;
  repo_name: string;
  branch?: string;
  explanation?: string;
  error_type?: string;
  patch_diff: string;
  confidence: number;
  timestamp: string;
  success: boolean;
  escalated: boolean;
  approved?: boolean | null;
  approved_pr_url?: string;
  detected_language?: string;
  violations?: string[];
  slm_generated?: boolean;
  source?: string;
}

const Patches = () => {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [tab, setTab] = useState<'pending' | 'approved' | 'rejected'>('pending');

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['jobs', tab],
    queryFn: () => api.get(`/api/jobs?approved=${tab}`).then(r => r.data),
    refetchInterval: 15_000,
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => api.post(`/api/jobs/${id}/approve`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['jobs'] }); },
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => api.post(`/api/jobs/${id}/reject`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['jobs'] }); },
  });

  const jobs: Job[] = data?.jobs ?? [];
  const pending = jobs.filter(j => j.success && j.approved === null || j.approved === undefined);
  const approved = jobs.filter(j => j.approved === true);
  const rejected = jobs.filter(j => j.approved === false);

  const visibleJobs = tab === 'pending' ? pending : tab === 'approved' ? approved : rejected;

  const tabs = [
    { key: 'pending',  label: 'Pending',  count: pending.length },
    { key: 'approved', label: 'Approved', count: approved.length },
    { key: 'rejected', label: 'Rejected', count: rejected.length },
  ] as const;

  return (
    <div className="space-y-7">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Patches</h2>
          <p className="text-slate-500 text-xs mt-0.5">Review and approve AI-generated fixes before they ship</p>
        </div>
        <button onClick={() => refetch()} className="p-2 text-slate-500 hover:text-white border border-border rounded-md hover:border-slate-600 transition-colors">
          <RefreshCcw size={15} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border pb-0">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-semibold border-b-2 transition-colors -mb-px ${
              tab === t.key
                ? 'border-accent text-accent'
                : 'border-transparent text-slate-500 hover:text-white'
            }`}
          >
            {t.label}
            {t.count > 0 && (
              <span className={`ml-2 text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                tab === t.key
                  ? 'bg-accent/20 text-accent'
                  : 'bg-slate-800 text-slate-500'
              }`}>
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={22} className="text-slate-600 animate-spin" />
        </div>
      )}

      <div className="space-y-3">
        {visibleJobs.map(job => {
          const isOpen = expanded === job.id;
          const isApproving = approveMutation.isPending && approveMutation.variables === job.id;
          const isRejecting = rejectMutation.isPending && rejectMutation.variables === job.id;

          return (
            <div key={job.id} className={`bg-surface border rounded-lg overflow-hidden transition-colors ${
              isOpen ? 'border-accent/40' : 'border-border hover:border-slate-600'
            }`}>
              <div
                className="flex items-start justify-between p-4 cursor-pointer"
                onClick={() => setExpanded(isOpen ? null : job.id)}
              >
                <div className="flex items-start gap-3 min-w-0">
                  <div className={`p-1.5 rounded-md mt-0.5 shrink-0 ${
                    job.success ? 'bg-success/10' : job.escalated ? 'bg-warning/10' : 'bg-error/10'
                  }`}>
                    {job.success
                      ? <CheckCircle2 size={15} className="text-success" />
                      : job.escalated
                        ? <AlertCircle size={15} className="text-warning" />
                        : <XCircle size={15} className="text-error" />
                    }
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-white font-semibold text-sm">{job.repo_name}</span>
                      {job.branch && <span className="text-slate-600 text-xs">/{job.branch}</span>}
                      <span className="text-xs text-accent font-bold">{Math.round(job.confidence * 100)}%</span>
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5 truncate">
                      {job.explanation ?? job.error_type ?? 'Unknown failure'}
                    </p>
                    <div className="flex items-center gap-3 mt-1.5">
                      <span className="text-[10px] text-slate-500 flex items-center gap-1">
                        <Clock size={9} /> {formatDistanceToNow(new Date(job.timestamp))} ago
                      </span>
                      {job.slm_generated && (
                        <span className="text-[10px] text-accent/70 font-medium">AI generated</span>
                      )}
                      {job.source === 'memory' && (
                        <span className="text-[10px] text-slate-500">from cache</span>
                      )}
                      {job.violations && job.violations.length > 0 && (
                        <span className="text-[10px] text-error">⚠ {job.violations.length} violation{job.violations.length > 1 ? 's' : ''}</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0 ml-2">
                  {tab === 'pending' && job.success && (
                    <>
                      <button
                        onClick={e => { e.stopPropagation(); approveMutation.mutate(job.id); }}
                        disabled={isApproving || isRejecting}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-success/10 hover:bg-success/20 text-success border border-success/20 text-xs font-bold rounded-md transition-colors disabled:opacity-60"
                      >
                        {isApproving ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}
                        Approve
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); rejectMutation.mutate(job.id); }}
                        disabled={isApproving || isRejecting}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-error/10 hover:bg-error/20 text-error border border-error/20 text-xs font-bold rounded-md transition-colors disabled:opacity-60"
                      >
                        {isRejecting ? <Loader2 size={11} className="animate-spin" /> : <XCircle size={11} />}
                        Reject
                      </button>
                    </>
                  )}
                  {tab === 'approved' && job.approved_pr_url && (
                    <a href={job.approved_pr_url} target="_blank" rel="noreferrer"
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-accent/10 hover:bg-accent/20 text-accent border border-accent/20 text-xs font-bold rounded-md transition-colors"
                    >
                      <GitPullRequest size={11} /> View PR
                    </a>
                  )}
                  {isOpen ? <ChevronUp size={16} className="text-slate-500" /> : <ChevronDown size={16} className="text-slate-500" />}
                </div>
              </div>

              {/* Expanded diff view */}
              {isOpen && (
                <div className="border-t border-border">
                  {job.patch_diff ? (
                    <div>
                      <div className="px-4 py-2 bg-background border-b border-border flex items-center justify-between">
                        <span className="text-xs text-slate-500 font-medium font-mono">Unified diff</span>
                        {job.detected_language && (
                          <span className="text-[10px] text-slate-600 capitalize">{job.detected_language}</span>
                        )}
                      </div>
                      <pre className="overflow-x-auto text-xs font-mono p-4 leading-relaxed max-h-96">
                        {job.patch_diff.split('\n').map((line, i) => (
                          <div key={i} className={
                            line.startsWith('+') && !line.startsWith('+++') ? 'text-success bg-success/5' :
                            line.startsWith('-') && !line.startsWith('---') ? 'text-error bg-error/5' :
                            line.startsWith('@@') ? 'text-accent' :
                            'text-slate-400'
                          }>
                            {line || ' '}
                          </div>
                        ))}
                      </pre>
                    </div>
                  ) : (
                    <div className="px-4 py-6 text-center text-xs text-slate-500">
                      {job.escalated ? 'Escalated — no patch generated. Manual review required.' : 'No patch available.'}
                    </div>
                  )}

                  {job.violations && job.violations.length > 0 && (
                    <div className="px-4 py-3 bg-error/5 border-t border-error/20">
                      <p className="text-error text-xs font-semibold mb-1">DSEE violations:</p>
                      {job.violations.map((v, i) => (
                        <p key={i} className="text-xs text-slate-400 font-mono">• {v}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {!isLoading && visibleJobs.length === 0 && (
          <div className="bg-surface border border-dashed border-border rounded-lg p-14 text-center">
            <GitPullRequest size={28} className="text-slate-700 mx-auto mb-3" />
            <p className="text-slate-500 text-sm">
              {tab === 'pending' ? 'No patches awaiting approval' :
               tab === 'approved' ? 'No approved patches yet' :
               'No rejected patches'}
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default Patches;
