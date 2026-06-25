import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { GitBranch, ExternalLink, ScanSearch, CheckCircle2, AlertCircle, Loader2, Plus, RefreshCcw } from 'lucide-react';
import api from '../lib/api';
import { Link } from 'react-router-dom';

interface Installation {
  installation_id: number;
  account_login: string;
  account_type: string;
  repos: string[];
  is_active: boolean;
}

const Repositories = () => {
  const qc = useQueryClient();

  const { data: installs, isLoading: installsLoading } = useQuery<{ installations: Installation[] }>({
    queryKey: ['github-installations'],
    queryFn: () => api.get('/api/github/installations').then(r => r.data),
    refetchInterval: 30_000,
  });

  const { data: jobStats } = useQuery({
    queryKey: ['repo-stats'],
    queryFn: () => api.get('/api/analytics/per-repo-breakdown').then(r => r.data).catch(() => ({})),
  });

  const scanMutation = useMutation({
    mutationFn: (repoFullName: string) =>
      api.post('/api/scan', { repo_name: repoFullName }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['stats'] }),
  });

  const allRepos: { full_name: string; installation_id: number; account: string }[] = [];
  installs?.installations?.forEach(inst => {
    inst.repos.forEach(r => {
      allRepos.push({ full_name: `${inst.account_login}/${r}`, installation_id: inst.installation_id, account: inst.account_login });
    });
  });

  return (
    <div className="space-y-7">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Repositories</h2>
          <p className="text-slate-500 text-xs mt-0.5">Connected repos via GitHub App</p>
        </div>
        <a
          href="https://github.com/apps/dcsp-autofix/installations/new"
          target="_blank" rel="noreferrer"
          className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-md transition-colors"
        >
          <Plus size={14} />
          Add Repository
        </a>
      </div>

      {installsLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={24} className="text-slate-600 animate-spin" />
        </div>
      )}

      {!installsLoading && allRepos.length === 0 && (
        <div className="bg-surface border border-dashed border-border rounded-lg p-14 text-center">
          <GitBranch size={32} className="text-slate-700 mx-auto mb-3" />
          <p className="text-slate-400 text-sm font-semibold mb-1">No repositories connected</p>
          <p className="text-slate-600 text-xs mb-5">Install the DCSP GitHub App on your repositories to get started.</p>
          <a
            href="https://github.com/apps/dcsp-autofix/installations/new"
            target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-md transition-colors"
          >
            <Plus size={14} /> Install GitHub App
          </a>
        </div>
      )}

      <div className="space-y-3">
        {allRepos.map(repo => {
          const stats = jobStats?.[repo.full_name];
          const successRate = stats ? Math.round((stats.success / stats.total) * 100) : null;
          const isScanning = scanMutation.isPending && scanMutation.variables === repo.full_name;

          return (
            <div key={repo.full_name} className="bg-surface border border-border rounded-lg p-5 hover:border-slate-600 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="p-2 bg-background border border-border rounded-md mt-0.5">
                    <GitBranch size={16} className="text-slate-400" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-white font-semibold text-sm">{repo.full_name}</span>
                      <a
                        href={`https://github.com/${repo.full_name}`}
                        target="_blank" rel="noreferrer"
                        className="text-slate-600 hover:text-slate-400 transition-colors"
                      >
                        <ExternalLink size={12} />
                      </a>
                    </div>
                    <div className="flex items-center gap-4 mt-2">
                      {stats ? (
                        <>
                          <span className="text-xs text-slate-500">{stats.total} jobs</span>
                          <span className={`text-xs font-semibold ${(successRate ?? 0) >= 70 ? 'text-success' : 'text-warning'}`}>
                            {successRate}% success
                          </span>
                        </>
                      ) : (
                        <span className="text-xs text-slate-600">No jobs yet</span>
                      )}
                      <span className="text-[10px] text-slate-600">
                        Installation #{repo.installation_id}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => scanMutation.mutate(repo.full_name)}
                    disabled={isScanning}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-accent/10 hover:bg-accent/20 text-accent border border-accent/20 text-xs font-semibold rounded-md transition-colors disabled:opacity-60"
                  >
                    {isScanning ? <Loader2 size={12} className="animate-spin" /> : <ScanSearch size={12} />}
                    Scan
                  </button>
                  <Link
                    to="/scan"
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-slate-800 text-slate-400 border border-border text-xs font-medium rounded-md transition-colors"
                  >
                    History
                  </Link>
                </div>
              </div>

              {/* Scan progress */}
              {isScanning && (
                <div className="mt-3 pt-3 border-t border-border">
                  <div className="flex items-center gap-2 text-xs text-accent">
                    <RefreshCcw size={12} className="animate-spin" />
                    Scanning repository for errors…
                  </div>
                  <div className="mt-2 h-1 bg-background rounded-full overflow-hidden">
                    <div className="h-full bg-accent animate-pulse rounded-full w-2/3" />
                  </div>
                </div>
              )}

              {/* Success indicator */}
              {scanMutation.isSuccess && scanMutation.variables === repo.full_name && (
                <div className="mt-3 pt-3 border-t border-border flex items-center gap-2 text-xs text-success">
                  <CheckCircle2 size={12} />
                  Scan complete — check Patches for results
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Installation list */}
      {(installs?.installations?.length ?? 0) > 0 && (
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-white font-semibold text-sm mb-4">GitHub App Installations</h3>
          <div className="space-y-2">
            {installs?.installations?.map(inst => (
              <div key={inst.installation_id} className="flex items-center justify-between py-2 border-b border-border last:border-0">
                <div className="flex items-center gap-3">
                  <span className="text-sm text-white">{inst.account_login}</span>
                  <span className="text-[10px] text-slate-500 capitalize">{inst.account_type}</span>
                  <span className="text-xs text-slate-500">{inst.repos.length} repo{inst.repos.length !== 1 ? 's' : ''}</span>
                </div>
                <div className="flex items-center gap-2">
                  {inst.is_active
                    ? <span className="flex items-center gap-1 text-[10px] text-success font-bold"><CheckCircle2 size={10} /> Active</span>
                    : <span className="flex items-center gap-1 text-[10px] text-error font-bold"><AlertCircle size={10} /> Inactive</span>
                  }
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default Repositories;
