import React, { useCallback, useState } from 'react';
import EmptyState from '../EmptyState';
import { confirmAction } from '../confirmAction';
import { primeApi, errText, useLoad } from './primeApi';
import { Spinner, ErrorBox } from './parts';

const short = (text) => (text.length > 160 ? `${text.slice(0, 160)}...` : text);

// KAN-25: every edit an approver made is a test case for the agent that proposed it. A person can take one out
// (a wrong or one-off correction); it stays in correction memory, only the evaluation stops using it.
const EvalSet = () => {
  const load = useCallback(() => primeApi.evalSet({ limit: 100 }), []);
  const { data, error, loading, reload } = useLoad(load, 'Could not load the evaluation set.');
  const [problem, setProblem] = useState('');

  const remove = async (c) => {
    if (!(await confirmAction('Remove this case from the evaluation set? The correction stays in memory.', 'Remove case'))) return;
    setProblem('');
    try { await primeApi.setInEval(c.id, false); reload(); } catch (e) { setProblem(errText(e, 'Could not remove it.')); }
  };

  if (loading && !data) return <Spinner />;
  const cases = data?.cases || [];
  return (
    <section className="space-y-4" aria-label="Evaluation set">
      <p className="text-xs text-muted">
        Each edit an approver made becomes a test case for the agent that proposed it: its input and the corrected output.
        Remove the ones that should not count.
      </p>
      {(error || problem) && <ErrorBox>{error || problem}</ErrorBox>}
      {cases.length === 0 && !error ? (
        <EmptyState title="No cases yet" description="Cases appear when an approver edits a request." />
      ) : (
        <ul className="space-y-2">
          {cases.map((c) => (
            <li key={c.id} className="bg-panel border border-border rounded-xl px-5 py-3 flex flex-wrap items-center gap-3">
              <div className="flex-1 min-w-[14rem]">
                <p className="text-sm text-bright font-mono">{c.agent} · {c.action_type}</p>
                <p className="text-xs text-muted mt-0.5 break-all">Expected: {short(c.expected)}</p>
              </div>
              <button onClick={() => remove(c)} aria-label={`Remove ${c.agent} ${c.action_type} case`}
                      className="px-3 py-1.5 text-xs font-bold text-danger border border-danger/40 hover:bg-danger/10 rounded-lg">
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};

export default EvalSet;
