import React from 'react';
import { HelpCircle } from 'lucide-react';

// Clarifying questions from the architecture stage's domain model
// (phases.s02_architecture.output.clarifying_questions: [{field_path, confidence, question, options}]).
// Read-only: the server has no endpoint that feeds answers back into a run (POST /resume
// takes no body), so offering an answer form would pretend. To act on a question,
// edit the requirement and start a new run.
const ClarifyingQuestionsPanel = ({ questions }) => {
  if (!Array.isArray(questions) || questions.length === 0) return null;
  return (
    <section className="panel p-5 border-accent/30 space-y-4" aria-labelledby="cq-h">
      <div className="flex items-start gap-3">
        <HelpCircle className="w-5 h-5 text-accent shrink-0 mt-0.5" aria-hidden="true" />
        <div>
          <h3 id="cq-h" className="text-sm font-bold text-accent">Open questions from the domain model</h3>
          <p className="text-xs text-muted mt-0.5">
            The architecture stage could not settle {questions.length} field{questions.length !== 1 ? 's' : ''} from
            the requirement and used its best guess. These are for information: answers cannot be sent back into
            this run yet. To change the result, use Edit &amp; Restart with the answers written into the requirement.
          </p>
        </div>
      </div>
      <ul className="space-y-3">
        {questions.map((q, i) => (
          <li key={q.field_path || i} className="bg-surface/50 border border-border rounded-lg p-4 space-y-1.5">
            <p className="text-sm font-medium text-bright">
              {q.field_path && <span className="text-xs text-muted mr-2 font-mono">{q.field_path}</span>}
              {q.question || 'No question text recorded.'}
            </p>
            {typeof q.confidence === 'number' && (
              <p className="text-[11px] text-muted">Model confidence: {Math.round(q.confidence * 100)}%</p>
            )}
            {Array.isArray(q.options) && q.options.length > 0 && (
              <p className="text-[11px] text-muted">Options: {q.options.join(' · ')}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
};

export default ClarifyingQuestionsPanel;
