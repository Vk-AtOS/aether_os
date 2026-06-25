import { useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  CheckCircle2, XCircle, AlertCircle, ArrowLeft, ExternalLink,
  Clock, GitBranch, Code2, FileText, ShieldAlert, Zap,
  ThumbsUp, ThumbsDown, PenLine, RotateCcw, Copy, CheckCheck,
  AlertTriangle, Terminal, Layers, Search,
} from 'lucide-react';
import { formatDistanceToNow, format } from 'date-fns';
import api from '../lib/api';

interface Job {
  id: string;
  repo_name: string;
  branch: string;
  commit_sha?: string;
  success: boolean;
  escalated: boolean;
  confidence: number;
  timestamp: string;
  ci_system?: string;
  detected_language?: string;
  explanation: string;
  patch_diff?: string;
  sandbox_result?: string;
  approved?: boolean | null;
  approved_pr_url?: string;
  slm_generated?: boolean;
  source?: string;
  fingerprint?: string;
  violations?: string[];
  patch_edited?: boolean;
  error_type?: string;
}

type Tab = 'analysis' | 'patch' | 'rootcause' | 'violations';

// Parse files touched by a diff
function extractFilesFromDiff(diff: string): string[] {
  const files: string[] = [];
  for (const line of diff.split('\n')) {
    if (line.startsWith('+++ b/') || line.startsWith('--- a/')) {
      const f = line.replace(/^[+-]{3} [ab]\//, '');
      if (f && !files.includes(f)) files.push(f);
    }
  }
  return files;
}

// Parse error lines from explanation (e.g. "File ..., line N: SyntaxError: ...")
function parseErrors(explanation: string): Array<{ file: string; line: number; type: string; msg: string }> {
  const errors: Array<{ file: string; line: number; type: string; msg: string }> = [];
  const re = /File "([^"]+)", line (\d+)[,:]?\s*(?:in [^\n]*)?\n?\s*(\w+Error|\w+Warning|SyntaxError|IndentationError|NameError|TypeError|ValueError):\s*(.+)/g;
  let m;
  while ((m = re.exec(explanation)) !== null) {
    errors.push({ file: m[1], line: parseInt(m[2]), type: m[3], msg: m[4].trim() });
  }
  // Fallback: look for simpler patterns
  if (errors.length === 0) {
    const re2 = /(\w+Error|\w+Warning): (.+)/g;
    while ((m = re2.exec(explanation)) !== null) {
      errors.push({ file: 'unknown', line: 0, type: m[1], msg: m[2].trim() });
    }
  }
  return errors;
}

// Syntax-colored diff renderer
function DiffViewer({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return (
      <div className="flex items-center gap-2 text-slate-500 text-sm p-6">
        <FileText size={16} /> No patch generated for this job.
      </div>
    );
  }

  const lines = diff.split('\n');
  return (
    <div className="overflow-x-auto rounded-lg bg-[#0d1117] border border-border text-xs font-mono">
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, i) => {
            let rowCls = '';
            let textCls = 'text-slate-500';
            if (line.startsWith('+') && !line.startsWith('+++')) {
              rowCls = 'bg-green-500/5';
              textCls = 'text-green-400';
            } else if (line.startsWith('-') && !line.startsWith('---')) {
              rowCls = 'bg-red-500/5';
              textCls = 'text-red-400';
            } else if (line.startsWith('@@')) {
              rowCls = 'bg-blue-500/5';
              textCls = 'text-blue-400';
            } else if (line.startsWith('+++') || line.startsWith('---')) {
              textCls = 'text-slate-400 font-semibold';
            }
            return (
              <tr key={i} className={rowCls}>
                <td className="select-none w-12 text-right pr-4 py-0.5 text-slate-600 border-r border-border/50 pl-3">
                  {i + 1}
                </td>
                <td className={`py-0.5 pl-4 pr-6 whitespace-pre ${textCls}`}>{line || ' '}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handle = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button onClick={handle} className="p-1.5 text-slate-500 hover:text-white rounded transition-colors" title="Copy">
      {copied ? <CheckCheck size={14} className="text-green-400" /> : <Copy size={14} />}
    </button>
  );
}

export default function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>('analysis');
  const [customPatch, setCustomPatch] = useState('');
  const [showCustomForm, setShowCustomForm] = useState(false);

  const { data: job, isLoading, error } = useQuery<Job>({
    queryKey: ['job', jobId],
    queryFn: () => api.get(`/api/jobs/${jobId}`).then(r => r.data),
    enabled: !!jobId,
  });

  const approveMutation = useMutation({
    mutationFn: () => api.post(`/api/jobs/${jobId}/approve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['job', jobId] }),
  });

  const rejectMutation = useMutation({
    mutationFn: () => api.post(`/api/jobs/${jobId}/reject`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['job', jobId] }),
  });

  const customPatchMutation = useMutation({
    mutationFn: (patch: string) => api.post(`/api/jobs/${jobId}/custom-patch`, { patch_diff: patch }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['job', jobId] });
      setShowCustomForm(false);
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="text-center py-16 text-slate-500">
        <AlertCircle size={40} className="mx-auto mb-3 text-slate-700" />
        <p>Job not found.</p>
        <button onClick={() => navigate('/feed')} className="mt-4 text-accent text-sm hover:underline">
          ← Back to feed
        </button>
      </div>
    );
  }

  const isPatched = job.success;
  const isEscalated = job.escalated;
  const isPending = job.approved === null || job.approved === undefined;
  const isApproved = job.approved === true;
  const isRejected = job.approved === false;

  const statusBadge = isPatched
    ? { label: 'Patched', cls: 'text-green-400 bg-green-400/10 border-green-400/20', Icon: CheckCircle2 }
    : isEscalated
    ? { label: 'Escalated', cls: 'text-amber-400 bg-amber-400/10 border-amber-400/20', Icon: AlertCircle }
    : { label: 'Failed', cls: 'text-red-400 bg-red-400/10 border-red-400/20', Icon: XCircle };

  const approvalBadge = isApproved
    ? { label: 'Approved', cls: 'text-green-400 bg-green-400/10 border-green-400/20' }
    : isRejected
    ? { label: 'Rejected', cls: 'text-red-400 bg-red-400/10 border-red-400/20' }
    : { label: 'Awaiting Review', cls: 'text-amber-400 bg-amber-400/10 border-amber-400/20' };

  const errors = parseErrors(job.explanation || '');
  const touchedFiles = job.patch_diff ? extractFilesFromDiff(job.patch_diff) : [];
  const hasPatch = !!(job.patch_diff && job.patch_diff.trim());
  const sandboxPassed = job.sandbox_result === 'passed';

  const tabs: Array<{ id: Tab; label: string; icon: React.FC<{ size?: number; className?: string }> }> = [
    { id: 'analysis', label: 'Failure Analysis', icon: Search },
    { id: 'rootcause', label: 'Root Cause', icon: Layers },
    { id: 'patch', label: 'Patch Diff', icon: Code2 },
    { id: 'violations', label: 'Violations', icon: ShieldAlert },
  ];

  return (
    <div className="space-y-5 max-w-5xl">
      {/* Back link */}
      <Link to="/feed" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-white transition-colors">
        <ArrowLeft size={14} /> Live Feed
      </Link>

      {/* Header card */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <statusBadge.Icon size={16} className={statusBadge.cls.split(' ')[0]} />
              <h2 className="text-white font-bold text-lg truncate">{job.repo_name}</h2>
              {job.branch && (
                <span className="flex items-center gap-1 text-xs text-slate-500">
                  <GitBranch size={12} /> {job.branch}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <span className={`text-xs px-2 py-0.5 rounded-full border font-bold ${statusBadge.cls}`}>
                {statusBadge.label}
              </span>
              <span className={`text-xs px-2 py-0.5 rounded-full border font-bold ${approvalBadge.cls}`}>
                {approvalBadge.label}
              </span>
              {job.patch_edited && (
                <span className="text-xs px-2 py-0.5 rounded-full border border-purple-400/20 text-purple-400 bg-purple-400/10 font-bold">
                  Custom Patch
                </span>
              )}
              {job.slm_generated && (
                <span className="text-xs px-2 py-0.5 rounded-full border border-accent/20 text-accent bg-accent/5 font-bold flex items-center gap-1">
                  <Zap size={10} /> AI Generated
                </span>
              )}
            </div>
          </div>

          {/* Meta */}
          <div className="text-right space-y-1 shrink-0">
            <div className="text-xs text-slate-500 flex items-center gap-1 justify-end">
              <Clock size={11} />
              {format(new Date(job.timestamp), 'MMM d, yyyy HH:mm:ss')}
            </div>
            <div className="text-xs text-slate-500">
              {formatDistanceToNow(new Date(job.timestamp))} ago
            </div>
            {job.commit_sha && (
              <div className="text-xs font-mono text-slate-600">{job.commit_sha.slice(0, 8)}</div>
            )}
          </div>
        </div>

        {/* KPI row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5 pt-5 border-t border-border">
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Confidence</p>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${job.confidence >= 0.8 ? 'bg-green-400' : job.confidence >= 0.5 ? 'bg-amber-400' : 'bg-red-400'}`}
                  style={{ width: `${job.confidence * 100}%` }}
                />
              </div>
              <span className="text-white text-sm font-bold">{Math.round(job.confidence * 100)}%</span>
            </div>
          </div>
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Language</p>
            <p className="text-white text-sm font-semibold capitalize">{job.detected_language || 'Unknown'}</p>
          </div>
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">CI System</p>
            <p className="text-white text-sm font-semibold">{job.ci_system || 'Unknown'}</p>
          </div>
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Sandbox</p>
            {job.sandbox_result ? (
              <span className={`text-sm font-bold ${sandboxPassed ? 'text-green-400' : 'text-red-400'}`}>
                {sandboxPassed ? '✓ Passed' : '✗ ' + job.sandbox_result.replace('failed: ', '')}
              </span>
            ) : (
              <span className="text-slate-600 text-sm">—</span>
            )}
          </div>
        </div>
      </div>

      {/* PR link if exists */}
      {job.approved_pr_url && (
        <a
          href={job.approved_pr_url}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2 bg-green-500/5 border border-green-500/20 rounded-lg px-4 py-3 text-green-400 text-sm font-medium hover:bg-green-500/10 transition-colors"
        >
          <ExternalLink size={14} />
          View Auto-Fix PR on GitHub
          <span className="ml-auto text-xs text-green-400/60 font-mono truncate">{job.approved_pr_url}</span>
        </a>
      )}

      {/* Tab navigation */}
      <div className="flex gap-1 border-b border-border overflow-x-auto">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold border-b-2 -mb-px transition-colors whitespace-nowrap ${
              tab === t.id
                ? 'border-accent text-accent'
                : 'border-transparent text-slate-500 hover:text-white'
            }`}
          >
            <t.icon size={13} /> {t.label}
          </button>
        ))}
      </div>

      {/* ── TAB: Failure Analysis ───────────────────────────────────────── */}
      {tab === 'analysis' && (
        <div className="space-y-4">
          <div className="bg-surface border border-border rounded-lg p-5">
            <h3 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
              <Terminal size={14} className="text-red-400" /> What Failed
            </h3>
            <p className="text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">{job.explanation || 'No explanation recorded.'}</p>
          </div>

          {errors.length > 0 && (
            <div className="bg-surface border border-border rounded-lg overflow-hidden">
              <div className="px-5 py-3 border-b border-border flex items-center gap-2">
                <AlertTriangle size={13} className="text-amber-400" />
                <span className="text-white text-sm font-semibold">
                  {errors.length} Error{errors.length !== 1 ? 's' : ''} Detected
                </span>
              </div>
              <div className="divide-y divide-border">
                {errors.map((err, i) => (
                  <div key={i} className="px-5 py-4">
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 text-[10px] bg-red-500/10 border border-red-500/20 text-red-400 font-bold px-2 py-0.5 rounded shrink-0">
                        #{i + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                          <span className="text-red-400 font-bold text-sm">{err.type}</span>
                          {err.line > 0 && (
                            <span className="text-xs text-slate-500 font-mono">line {err.line}</span>
                          )}
                        </div>
                        <p className="text-slate-300 text-sm">{err.msg}</p>
                        {err.file !== 'unknown' && (
                          <p className="text-xs text-slate-600 font-mono mt-1 truncate">{err.file}</p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* What DCSP found */}
          <div className="bg-surface border border-border rounded-lg p-5">
            <h3 className="text-white font-semibold text-sm mb-3 flex items-center gap-2">
              <CheckCircle2 size={14} className="text-accent" /> What DCSP Found & Applied
            </h3>
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500 w-32 shrink-0">Outcome</span>
                <span className={`text-sm font-semibold ${isPatched ? 'text-green-400' : isEscalated ? 'text-amber-400' : 'text-red-400'}`}>
                  {isPatched ? 'Patch generated and validated' : isEscalated ? 'Escalated — requires manual review' : 'Could not generate valid patch'}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500 w-32 shrink-0">Patch method</span>
                <span className="text-sm text-white">{job.slm_generated ? 'LLM-generated diff' : job.source === 'memory' ? 'Pattern matched from history' : 'Rule-based repair'}</span>
              </div>
              {hasPatch && (
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-500 w-32 shrink-0">Files patched</span>
                  <div className="flex flex-wrap gap-1">
                    {touchedFiles.map(f => (
                      <span key={f} className="text-xs font-mono bg-slate-800 border border-border px-2 py-0.5 rounded text-slate-300">{f}</span>
                    ))}
                  </div>
                </div>
              )}
              {job.sandbox_result && (
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-500 w-32 shrink-0">Sandbox check</span>
                  <span className={`text-sm font-semibold ${sandboxPassed ? 'text-green-400' : 'text-red-400'}`}>
                    {sandboxPassed ? 'Syntax validated in isolated environment' : job.sandbox_result}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── TAB: Root Cause ─────────────────────────────────────────────── */}
      {tab === 'rootcause' && (
        <div className="space-y-4">
          <div className="bg-surface border border-border rounded-lg p-5">
            <h3 className="text-white font-semibold text-sm mb-4 flex items-center gap-2">
              <Layers size={14} className="text-accent" /> Root Cause Trace
            </h3>

            {errors.length > 0 ? (
              <div className="space-y-4">
                {errors.map((err, i) => (
                  <div key={i} className="relative pl-6 before:absolute before:left-2 before:top-2 before:bottom-0 before:w-0.5 before:bg-border last:before:hidden">
                    <div className="absolute left-0 top-1.5 w-4 h-4 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center">
                      <div className="w-1.5 h-1.5 rounded-full bg-red-400" />
                    </div>
                    <div className="bg-slate-900/60 border border-border rounded-lg p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-red-400 font-bold text-sm">{err.type}</span>
                        {err.line > 0 && (
                          <span className="text-xs font-mono bg-slate-800 px-2 py-0.5 rounded text-slate-400">line {err.line}</span>
                        )}
                      </div>
                      <p className="text-slate-300 text-sm mb-3">{err.msg}</p>
                      {err.file !== 'unknown' && (
                        <div className="flex items-center gap-2 text-xs text-slate-500">
                          <FileText size={11} />
                          <span className="font-mono">{err.file}</span>
                        </div>
                      )}
                    </div>
                  </div>
                ))}

                {touchedFiles.length > 0 && (
                  <div className="relative pl-6">
                    <div className="absolute left-0 top-1.5 w-4 h-4 rounded-full bg-blue-500/20 border border-blue-500/40 flex items-center justify-center">
                      <div className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                    </div>
                    <div className="bg-slate-900/60 border border-border rounded-lg p-4">
                      <p className="text-blue-400 font-semibold text-sm mb-2">Files Modified by Patch</p>
                      <div className="space-y-1.5">
                        {touchedFiles.map(f => (
                          <div key={f} className="flex items-center gap-2 text-xs font-mono text-slate-400">
                            <Code2 size={11} className="text-slate-600 shrink-0" /> {f}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {isPatched && (
                  <div className="relative pl-6">
                    <div className="absolute left-0 top-1.5 w-4 h-4 rounded-full bg-green-500/20 border border-green-500/40 flex items-center justify-center">
                      <div className="w-1.5 h-1.5 rounded-full bg-green-400" />
                    </div>
                    <div className="bg-green-500/5 border border-green-500/20 rounded-lg p-4">
                      <p className="text-green-400 font-semibold text-sm">
                        Patch validated — {sandboxPassed ? 'syntax check passed in sandbox' : 'accepted by pipeline'}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-slate-500 text-sm">No structured error trace available. See Failure Analysis tab for details.</p>
            )}
          </div>

          {job.fingerprint && (
            <div className="bg-surface border border-border rounded-lg p-4">
              <p className="text-xs text-slate-500 mb-1">Error Fingerprint</p>
              <p className="text-xs font-mono text-slate-400 break-all">{job.fingerprint}</p>
              <p className="text-xs text-slate-600 mt-1">Identical fingerprints across repos indicate the same root cause.</p>
            </div>
          )}
        </div>
      )}

      {/* ── TAB: Patch Diff ─────────────────────────────────────────────── */}
      {tab === 'patch' && (
        <div className="space-y-4">
          <div className="bg-surface border border-border rounded-lg overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-border">
              <div className="flex items-center gap-2">
                <Code2 size={14} className="text-slate-400" />
                <span className="text-white text-sm font-semibold">Generated Patch</span>
                {job.patch_edited && (
                  <span className="text-[10px] text-purple-400 border border-purple-400/20 bg-purple-400/5 px-2 py-0.5 rounded font-bold">
                    User-Edited
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {hasPatch && <CopyButton text={job.patch_diff!} />}
                {job.sandbox_result && (
                  <span className={`text-[10px] px-2 py-0.5 rounded border font-bold ${sandboxPassed ? 'text-green-400 border-green-400/20 bg-green-400/5' : 'text-red-400 border-red-400/20 bg-red-400/5'}`}>
                    sandbox: {job.sandbox_result}
                  </span>
                )}
              </div>
            </div>
            <div className="p-4">
              <DiffViewer diff={job.patch_diff || ''} />
            </div>
          </div>
        </div>
      )}

      {/* ── TAB: Violations ─────────────────────────────────────────────── */}
      {tab === 'violations' && (
        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          <div className="px-5 py-3 border-b border-border flex items-center gap-2">
            <ShieldAlert size={14} className="text-amber-400" />
            <span className="text-white text-sm font-semibold">Policy Violations</span>
          </div>
          {job.violations && job.violations.length > 0 ? (
            <div className="divide-y divide-border">
              {job.violations.map((v, i) => (
                <div key={i} className="px-5 py-3 text-sm text-slate-300">{v}</div>
              ))}
            </div>
          ) : (
            <div className="px-5 py-8 text-center text-slate-600 text-sm">No policy violations recorded.</div>
          )}
        </div>
      )}

      {/* ── Actions bar ─────────────────────────────────────────────────── */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <h3 className="text-white font-semibold text-sm mb-4 flex items-center gap-2">
          <PenLine size={14} className="text-slate-400" /> Review Actions
        </h3>

        {isApproved && (
          <div className="flex items-center gap-2 text-green-400 text-sm">
            <CheckCircle2 size={16} /> Patch approved.
            {job.approved_pr_url && (
              <a href={job.approved_pr_url} target="_blank" rel="noreferrer"
                className="underline ml-1 flex items-center gap-1">
                View PR <ExternalLink size={11} />
              </a>
            )}
          </div>
        )}

        {isRejected && (
          <div className="flex items-center gap-2 text-red-400 text-sm">
            <XCircle size={16} /> Patch rejected. You can submit a custom patch below.
          </div>
        )}

        {(isPending || isRejected) && !showCustomForm && (
          <div className="flex flex-wrap gap-3">
            {isPending && hasPatch && (
              <button
                onClick={() => approveMutation.mutate()}
                disabled={approveMutation.isPending}
                className="flex items-center gap-2 px-5 py-2.5 bg-green-500/15 hover:bg-green-500/25 border border-green-500/30 text-green-400 text-sm font-bold rounded-lg transition-colors disabled:opacity-60"
              >
                <ThumbsUp size={14} />
                {approveMutation.isPending ? 'Approving…' : 'Approve & Merge'}
              </button>
            )}
            {isPending && (
              <button
                onClick={() => rejectMutation.mutate()}
                disabled={rejectMutation.isPending}
                className="flex items-center gap-2 px-5 py-2.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 text-sm font-bold rounded-lg transition-colors disabled:opacity-60"
              >
                <ThumbsDown size={14} />
                {rejectMutation.isPending ? 'Rejecting…' : 'Reject Patch'}
              </button>
            )}
            <button
              onClick={() => { setCustomPatch(job.patch_diff || ''); setShowCustomForm(true); }}
              className="flex items-center gap-2 px-5 py-2.5 bg-accent/10 hover:bg-accent/20 border border-accent/20 text-accent text-sm font-bold rounded-lg transition-colors"
            >
              <RotateCcw size={14} />
              Submit Custom Patch
            </button>
          </div>
        )}

        {showCustomForm && (
          <div className="space-y-3">
            <p className="text-xs text-slate-400">
              Paste your own diff below. DCSP will store it, mark the job as approved with your patch, and use it for this repair.
            </p>
            <textarea
              value={customPatch}
              onChange={e => setCustomPatch(e.target.value)}
              rows={14}
              placeholder={`--- a/src/your_file.py\n+++ b/src/your_file.py\n@@ -10,7 +10,7 @@\n-broken_line()\n+fixed_line()`}
              className="w-full bg-[#0d1117] border border-border rounded-lg px-4 py-3 text-xs font-mono text-white placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-accent resize-y"
            />
            <div className="flex gap-2">
              <button
                onClick={() => customPatchMutation.mutate(customPatch)}
                disabled={!customPatch.trim() || customPatchMutation.isPending}
                className="flex items-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-lg transition-colors disabled:opacity-60"
              >
                {customPatchMutation.isPending ? 'Saving…' : 'Save & Approve'}
              </button>
              <button
                onClick={() => setShowCustomForm(false)}
                className="px-4 py-2.5 text-slate-500 hover:text-white text-sm rounded-lg border border-border transition-colors"
              >
                Cancel
              </button>
            </div>
            {customPatchMutation.isError && (
              <p className="text-red-400 text-xs">Failed to save patch. Check format and try again.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
