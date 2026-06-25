import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ScanSearch, Play, CheckCircle2, XCircle, AlertCircle,
  Loader2, FileCode2, RefreshCcw, ChevronDown, ChevronUp
} from 'lucide-react';
import api from '../lib/api';

interface ScanIssue {
  file: string;
  line?: number;
  error_type: string;
  message: string;
  patch_diff?: string;
  confidence?: number;
  fixed?: boolean;
}

interface ScanResult {
  repo_name: string;
  scanned_at: string;
  total_files: number;
  issues_found: number;
  issues: ScanIssue[];
  status: 'complete' | 'running' | 'failed';
}

const Scan = () => {
  const qc = useQueryClient();
  const [repoInput, setRepoInput] = useState('');
  const [expandedFile, setExpandedFile] = useState<string | null>(null);
  const [lastScan, setLastScan] = useState<ScanResult | null>(null);

  const { data: installs } = useQuery({
    queryKey: ['github-installations'],
    queryFn: () => api.get('/api/github/installations').then(r => r.data),
  });

  const connectedRepos: string[] = [];
  installs?.installations?.forEach((inst: { account_login: string; repos: string[] }) => {
    inst.repos.forEach((r: string) => connectedRepos.push(`${inst.account_login}/${r}`));
  });

  const scanMutation = useMutation({
    mutationFn: (repoName: string) =>
      api.post('/api/scan', { repo_name: repoName }),
    onSuccess: (res) => {
      setLastScan(res.data);
      qc.invalidateQueries({ queryKey: ['jobs'] });
    },
  });

  const targetRepo = repoInput || connectedRepos[0] || '';

  const errorGroups = lastScan?.issues.reduce((acc, issue) => {
    acc[issue.error_type] = (acc[issue.error_type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>) ?? {};

  const fileGroups = lastScan?.issues.reduce((acc, issue) => {
    if (!acc[issue.file]) acc[issue.file] = [];
    acc[issue.file].push(issue);
    return acc;
  }, {} as Record<string, ScanIssue[]>) ?? {};

  return (
    <div className="space-y-7">
      <div>
        <h2 className="text-xl font-bold text-white">Repository Scan</h2>
        <p className="text-slate-500 text-xs mt-0.5">
          Proactively scan for syntax errors, import failures, and startup-blocking issues — before CI runs.
        </p>
      </div>

      {/* How scan mode works */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <div className="flex items-start gap-3">
          <ScanSearch size={18} className="text-accent shrink-0 mt-0.5" />
          <div>
            <p className="text-white font-semibold text-sm mb-1">What this does</p>
            <p className="text-slate-400 text-xs leading-relaxed">
              DCSP clones your repository and checks every file for problems that would stop the project from
              running — syntax errors, broken imports, missing dependencies, type mismatches.
              Each issue is sent through the same AI repair pipeline and DSEE guardrails as normal CI failures.
              Resulting patches appear in your Patches queue.
            </p>
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
          {['Syntax errors', 'Import errors', 'Missing deps', 'Entry point check'].map(t => (
            <div key={t} className="flex items-center gap-2 bg-background border border-border rounded-md px-3 py-2">
              <CheckCircle2 size={11} className="text-success shrink-0" />
              <span className="text-xs text-slate-400">{t}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Scan launcher */}
      <div className="bg-surface border border-border rounded-lg p-6 space-y-4">
        <h3 className="text-white font-semibold text-sm">Launch Scan</h3>

        <div>
          <label className="block text-xs text-slate-500 mb-1.5">Repository</label>
          {connectedRepos.length > 0 ? (
            <select
              value={targetRepo}
              onChange={e => setRepoInput(e.target.value)}
              className="w-full bg-background border border-border rounded-md px-3 py-2.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {connectedRepos.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          ) : (
            <input
              value={repoInput}
              onChange={e => setRepoInput(e.target.value)}
              placeholder="owner/repo-name"
              className="w-full bg-background border border-border rounded-md px-3 py-2.5 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-accent"
            />
          )}
        </div>

        <button
          onClick={() => targetRepo && scanMutation.mutate(targetRepo)}
          disabled={!targetRepo || scanMutation.isPending}
          className="flex items-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-md transition-colors disabled:opacity-60"
        >
          {scanMutation.isPending
            ? <><Loader2 size={15} className="animate-spin" /> Scanning…</>
            : <><Play size={14} /> Start Scan</>
          }
        </button>

        {scanMutation.isPending && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-accent">
              <RefreshCcw size={12} className="animate-spin" />
              Cloning repository and checking files…
            </div>
            <div className="h-1.5 bg-background rounded-full overflow-hidden">
              <div className="h-full bg-accent animate-pulse rounded-full w-1/2" style={{ transition: 'width 2s' }} />
            </div>
          </div>
        )}

        {scanMutation.isError && (
          <div className="flex items-center gap-2 text-xs text-error bg-error/5 border border-error/20 rounded-md px-3 py-2">
            <AlertCircle size={13} />
            Scan failed — check the repository name and try again.
          </div>
        )}
      </div>

      {/* Scan results */}
      {lastScan && (
        <div className="space-y-4">
          {/* Summary */}
          <div className={`flex items-center gap-3 p-4 rounded-lg border ${
            lastScan.issues_found === 0
              ? 'bg-success/5 border-success/20'
              : 'bg-warning/5 border-warning/20'
          }`}>
            {lastScan.issues_found === 0
              ? <CheckCircle2 size={18} className="text-success shrink-0" />
              : <AlertCircle size={18} className="text-warning shrink-0" />
            }
            <div>
              <p className={`font-semibold text-sm ${lastScan.issues_found === 0 ? 'text-success' : 'text-warning'}`}>
                {lastScan.issues_found === 0
                  ? 'Clean — no issues found'
                  : `${lastScan.issues_found} issue${lastScan.issues_found !== 1 ? 's' : ''} found across ${Object.keys(fileGroups).length} file${Object.keys(fileGroups).length !== 1 ? 's' : ''}`
                }
              </p>
              <p className="text-slate-500 text-xs">
                {lastScan.total_files} files scanned · {lastScan.repo_name}
              </p>
            </div>
          </div>

          {/* Error type breakdown */}
          {Object.keys(errorGroups).length > 0 && (
            <div className="flex flex-wrap gap-2">
              {Object.entries(errorGroups).map(([type, count]) => (
                <span key={type} className="text-xs px-2.5 py-1 bg-surface border border-border rounded-full text-slate-400">
                  {type} <span className="text-white font-bold">{count}</span>
                </span>
              ))}
            </div>
          )}

          {/* Per-file issue list */}
          {Object.entries(fileGroups).map(([file, issues]) => (
            <div key={file} className="bg-surface border border-border rounded-lg overflow-hidden">
              <button
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-800/50 transition-colors"
                onClick={() => setExpandedFile(expandedFile === file ? null : file)}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <FileCode2 size={14} className="text-slate-500 shrink-0" />
                  <span className="text-sm text-white font-mono truncate">{file}</span>
                  <span className="text-xs text-error font-semibold">
                    {issues.length} issue{issues.length > 1 ? 's' : ''}
                  </span>
                </div>
                {expandedFile === file ? <ChevronUp size={15} className="text-slate-500 shrink-0" /> : <ChevronDown size={15} className="text-slate-500 shrink-0" />}
              </button>

              {expandedFile === file && (
                <div className="border-t border-border divide-y divide-border">
                  {issues.map((issue, i) => (
                    <div key={i} className="p-4">
                      <div className="flex items-start justify-between gap-3 mb-2">
                        <div className="flex items-start gap-2">
                          <XCircle size={13} className="text-error shrink-0 mt-0.5" />
                          <div>
                            <span className="text-xs font-semibold text-error">{issue.error_type}</span>
                            {issue.line && <span className="text-xs text-slate-500 ml-2">line {issue.line}</span>}
                            <p className="text-xs text-slate-400 mt-0.5 font-mono">{issue.message}</p>
                          </div>
                        </div>
                        {issue.confidence && (
                          <span className="text-xs text-accent font-bold shrink-0">
                            {Math.round(issue.confidence * 100)}% fix confidence
                          </span>
                        )}
                      </div>
                      {issue.patch_diff && (
                        <div className="mt-2 bg-background rounded-md overflow-hidden border border-border">
                          <div className="px-3 py-1.5 bg-surface text-[10px] text-slate-500 font-mono border-b border-border">
                            Proposed fix
                          </div>
                          <pre className="text-xs font-mono p-3 overflow-x-auto max-h-40 leading-relaxed">
                            {issue.patch_diff.split('\n').map((line, li) => (
                              <div key={li} className={
                                line.startsWith('+') && !line.startsWith('+++') ? 'text-success' :
                                line.startsWith('-') && !line.startsWith('---') ? 'text-error' :
                                line.startsWith('@@') ? 'text-accent' : 'text-slate-500'
                              }>{line || ' '}</div>
                            ))}
                          </pre>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {lastScan.issues_found > 0 && (
            <p className="text-xs text-slate-500 text-center">
              Repair jobs have been added to your <a href="/app/patches" className="text-accent hover:underline">Patches queue</a> — approve to create PRs.
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default Scan;
