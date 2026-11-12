import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { RotateCcw, Play, GitBranch, Loader2 } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';
import { confirmAction } from '../confirmAction';
import { PHASE_NAMES } from './projectConstants';

// Re-run controls for one stage of a run (the per-stage edit-and-re-run screen).
//  - Restart this run: POST /restart — same run, same folder, continues at its checkpoint.
//  - Re-run from this stage: POST /rerun {from_phase} — a NEW run from the original requirement.
//  - Re-run from here as a new branch: POST /branch {branch_phase, extra_input}.
// /rerun and /branch do not copy this run's outputs or edited files into the new run
// (the server starts the new run with an empty project folder), so the screen says so.
const StageActions = ({ runId, stage, runStatus, canWrite }) => {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState('');
  const [extra, setExtra] = useState('');
  const name = PHASE_NAMES[stage] || stage;
  const canRestart = runStatus === 'failed' || runStatus === 'cancelled';
  const stopped = !['running', 'paused', 'queued'].includes(runStatus);

  const go = async (kind) => {
    const ask = {
      restart: 'Restart this run? It continues in place from the stage that stopped it, using the files in this run (including any you edited).',
      rerun: `Start a new run from ${name}? It starts from the original requirement on a copy of this run's project folder, including your edits (secrets, .env, node_modules and the running app's state are not copied).`,
      branch: `Start a new branch run from ${name}${extra.trim() ? ' with your added requirement' : ''}? It starts on a copy of this run's project folder, including your edits (secrets, .env, node_modules and the running app's state are not copied).`,
    }[kind];
    if (!(await confirmAction(ask, 'Re-run'))) return;
    setBusy(kind); setError('');
    try {
      if (kind === 'restart') {
        await api.restartRun(runId);
        navigate(`/project/${runId}`);
      } else {
        const res = kind === 'rerun'
          ? await api.rerunFromPhase(runId, stage)
          : await api.branchRun(runId, stage, extra.trim());
        navigate(`/project/${res.data.run_id}`);
      }
    } catch (e) {
      setError(apiError(e) || e.message || 'The run could not be started.');
    } finally {
      setBusy(null);
    }
  };

  if (!canWrite) return null;
  const btn = 'flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-bold border disabled:opacity-50';
  return (
    <section className="panel p-5 space-y-3" aria-labelledby="stage-actions-h">
      <h2 id="stage-actions-h" className="text-xs font-bold text-muted uppercase tracking-widest">Re-run</h2>
      {!stopped && <p className="text-xs text-muted">This run is still in progress. Re-run options open once it stops.</p>}
      <div className="flex flex-wrap gap-2">
        {canRestart && (
          <button onClick={() => go('restart')} disabled={Boolean(busy)} className={`${btn} bg-success/15 text-success border-success/30`}>
            {busy === 'restart' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />} Restart this run
          </button>
        )}
        <button onClick={() => go('rerun')} disabled={Boolean(busy) || !stopped} className={`${btn} bg-indigo-500/15 text-indigo-300 border-indigo-500/30`}>
          {busy === 'rerun' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />} Re-run from {name} (new run)
        </button>
      </div>
      <div className="space-y-2 pt-2 border-t border-border/50">
        <label htmlFor="branch-extra" className="block text-[11px] text-muted">
          Or start a branch from {name} with an added requirement (optional):
        </label>
        <textarea id="branch-extra" value={extra} onChange={(e) => setExtra(e.target.value)} rows={2}
          placeholder="e.g. Add CSV export to the reports page"
          className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs text-bright focus:outline-none focus:border-accent" />
        <button onClick={() => go('branch')} disabled={Boolean(busy) || !stopped} className={`${btn} bg-violet-500/15 text-violet-300 border-violet-500/30`}>
          {busy === 'branch' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <GitBranch className="w-3.5 h-3.5" />} Branch from {name}
        </button>
      </div>
      <p className="text-[11px] text-muted">
        Edits saved under Artifacts change this run&apos;s files. &quot;Restart this run&quot; continues with them, and a new rerun or branch starts on a copy of them (secrets, .env and node_modules are not copied).
      </p>
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
    </section>
  );
};

export default StageActions;
