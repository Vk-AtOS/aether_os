import React, { useEffect, useState } from 'react';
import { HelpCircle, Check } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';

// Clarifying questions from the architecture stage's domain model
// (phases.s02_architecture.output.clarifying_questions: [{field_path, confidence, question, options}]).
// Answers are sent to POST /factory/runs/{id}/clarifying-answers, recorded for this run, and used the
// next time the architecture stage runs ("Save and rebuild" restarts the run from there).
const ClarifyingQuestionsPanel = ({ runId, questions, answers, canRestart, onChanged }) => {
  const [draft, setDraft] = useState({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [saved, setSaved] = useState({});

  // The answers recorded for this run (they are used when the architecture stage next runs).
  useEffect(() => {
    if (!runId) return undefined;
    let cancelled = false;
    api.getClarifyingAnswers(runId)
      .then((r) => { if (!cancelled) setSaved(r.data?.answers || {}); })
      .catch((e) => console.debug('No recorded answers', e));
    return () => { cancelled = true; };
  }, [runId]);
  if (!Array.isArray(questions) || questions.length === 0) return null;

  const recorded = { ...(answers || {}), ...saved };
  const filled = Object.fromEntries(Object.entries(draft).filter(([, v]) => v && v.trim()));
  const submit = async (restart) => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await api.submitClarifyingAnswers(runId, filled, restart);
      setSaved(res.data?.answers || {});
      setDraft({});
      setMessage({ ok: true, text: restart ? 'Answers saved. Rebuilding from the architecture stage.' : 'Answers saved. They are used the next time the architecture stage runs.' });
      onChanged?.();
    } catch (e) {
      setMessage({ ok: false, text: apiError(e) || e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel p-5 border-accent/30 space-y-4" aria-labelledby="cq-h">
      <div className="flex items-start gap-3">
        <HelpCircle className="w-5 h-5 text-accent shrink-0 mt-0.5" aria-hidden="true" />
        <div>
          <h3 id="cq-h" className="text-sm font-bold text-accent">Open questions from the domain model</h3>
          <p className="text-xs text-muted mt-0.5">
            The architecture stage could not settle {questions.length} field{questions.length !== 1 ? 's' : ''} from
            the requirement and used its best guess. Answer them and rebuild from the architecture stage to settle them.
          </p>
        </div>
      </div>
      <ul className="space-y-3">
        {questions.map((q, i) => {
          const path = q.field_path || String(i);
          const id = `cq-${i}`;
          const hasOptions = Array.isArray(q.options) && q.options.length > 0;
          return (
            <li key={path} className="bg-surface/50 border border-border rounded-lg p-4 space-y-1.5">
              <label htmlFor={id} className="block text-sm font-medium text-bright">
                {q.field_path && <span className="text-xs text-muted mr-2 font-mono">{q.field_path}</span>}
                {q.question || 'No question text recorded.'}
              </label>
              {typeof q.confidence === 'number' && (
                <p className="text-[11px] text-muted">Model confidence: {Math.round(q.confidence * 100)}%</p>
              )}
              {recorded[q.field_path] && (
                <p className="text-[11px] text-emerald-400 flex items-center gap-1">
                  <Check className="w-3 h-3" aria-hidden="true" /> Recorded answer: <span className="font-mono">{recorded[q.field_path]}</span>
                </p>
              )}
              {hasOptions ? (
                <select id={id} value={draft[q.field_path] || ''} disabled={busy}
                  onChange={(e) => setDraft({ ...draft, [q.field_path]: e.target.value })}
                  className="w-full bg-surface border border-border rounded px-2 py-1.5 text-xs text-bright">
                  <option value="">Choose an answer...</option>
                  {q.options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <textarea id={id} rows={2} maxLength={2000} value={draft[q.field_path] || ''} disabled={busy}
                  onChange={(e) => setDraft({ ...draft, [q.field_path]: e.target.value })}
                  placeholder="Your answer"
                  className="w-full bg-surface border border-border rounded px-2 py-1.5 text-xs text-bright" />
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={() => submit(false)} disabled={busy || Object.keys(filled).length === 0}
          className="text-xs px-3 py-1.5 border border-accent/40 text-accent rounded-lg hover:bg-accent/10 disabled:opacity-40 transition-colors">
          Save answers
        </button>
        <button onClick={() => submit(true)} disabled={busy || !canRestart || Object.keys(filled).length === 0}
          title={canRestart ? 'Save and run again from the architecture stage' : 'Wait for the run to stop before rebuilding'}
          className="text-xs px-3 py-1.5 bg-accent text-black font-semibold rounded-lg hover:bg-accent/80 disabled:opacity-40 transition-colors">
          Save and rebuild from architecture
        </button>
        {message && <span role="status" className={`text-xs ${message.ok ? 'text-emerald-400' : 'text-red-300'}`}>{message.text}</span>}
      </div>
    </section>
  );
};

export default ClarifyingQuestionsPanel;
