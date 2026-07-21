import React from 'react';
import { api } from '../../api';

const ClarifyingQuestionsPanel = ({ runId, questionCount, onAnswered }) => {
  const [answers, setAnswers] = React.useState({});
  const [submitting, setSubmitting] = React.useState(false);
  const [questions, setQuestions] = React.useState(null);

  React.useEffect(() => {
    api.getRun(runId).then(res => {
      const meta = res.data?.phases?.p02b_domain_ir?.metadata
                || res.data?.phases?.p02b_domain_ir?.output?.metadata;
      const qs = meta?.clarifying_questions_detail || [];
      if (qs.length > 0) {
        setQuestions(qs);
      } else {
        setQuestions(Array.from({ length: questionCount }, (_, i) => ({
          field_path: `field_${i + 1}`,
          question: `Please clarify ambiguous field ${i + 1}`,
          options: [],
        })));
      }
    }).catch(() => {
      setQuestions([]);
    });
  }, [runId, questionCount]);

  if (!questions || questions.length === 0) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onAnswered(answers);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel p-5 border-accent/30 space-y-4">
      <div className="flex items-start gap-3">
        <span className="text-xl">🤔</span>
        <div>
          <h3 className="text-sm font-bold text-accent">Clarification Needed</h3>
          <p className="text-xs text-muted mt-0.5">
            The IR extraction found {questions.length} ambiguous field{questions.length !== 1 ? 's' : ''}.
            Answer these before the pipeline continues.
          </p>
        </div>
      </div>
      <form onSubmit={handleSubmit} className="space-y-4">
        {questions.map((q, i) => (
          <div key={i} className="bg-surface/50 border border-border rounded-lg p-4 space-y-2">
            <p className="text-sm font-medium text-bright">
              <span className="text-xs text-muted mr-2 font-mono">{q.field_path}</span>
              {q.question}
            </p>
            {q.options && q.options.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {q.options.map((opt, j) => (
                  <label key={j} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name={q.field_path}
                      value={opt}
                      checked={answers[q.field_path] === opt}
                      onChange={() => setAnswers(a => ({ ...a, [q.field_path]: opt }))}
                      className="accent-accent"
                    />
                    <span className="text-sm text-bright">{opt}</span>
                  </label>
                ))}
              </div>
            ) : (
              <input
                type="text"
                placeholder="Your answer…"
                value={answers[q.field_path] || ''}
                onChange={e => setAnswers(a => ({ ...a, [q.field_path]: e.target.value }))}
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
              />
            )}
          </div>
        ))}
        <button
          type="submit"
          disabled={submitting}
          className="px-5 py-2.5 bg-accent hover:bg-accent/90 disabled:opacity-40 text-white text-sm font-bold rounded-lg transition-colors"
        >
          {submitting ? 'Submitting…' : '✅ Submit Answers & Resume Pipeline'}
        </button>
      </form>
    </section>
  );
};

export default ClarifyingQuestionsPanel;
