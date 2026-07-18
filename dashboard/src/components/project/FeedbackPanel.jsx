import React, { useState } from 'react';
import { Star, CheckCircle2 } from 'lucide-react';
import { api } from '../../api';

const FEEDBACK_TAGS = ['great-ui', 'clean-models', 'fast-api', 'good-seed-data', 'production-ready', 'needs-work'];

const FeedbackPanel = ({ run }) => {
  const [feedbackRating, setFeedbackRating]         = useState(0);
  const [feedbackHover, setFeedbackHover]           = useState(0);
  const [feedbackTags, setFeedbackTags]             = useState([]);
  const [feedbackComment, setFeedbackComment]       = useState('');
  const [feedbackSubmitted, setFeedbackSubmitted]   = useState(false);
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [feedbackError, setFeedbackError]           = useState(null);

  if (run?.status !== 'completed') return null;

  if (feedbackSubmitted) {
    return (
      <section className="panel p-4 flex items-center gap-3">
        <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
        <div>
          <p className="text-sm font-bold text-bright">Thanks for your rating!</p>
          <p className="text-xs text-muted">
            {feedbackRating >= 4
              ? 'This build may be promoted to a golden example to improve future generations.'
              : 'Your feedback helps AetherOS learn.'}
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="panel p-5 space-y-4">
      <div className="flex items-center space-x-2">
        <Star className="w-4 h-4 text-yellow-400" />
        <span className="text-xs font-bold text-muted uppercase tracking-wider">Rate This Build</span>
      </div>
      <p className="text-xs text-muted">Your rating teaches AetherOS to generate better apps over time. 4★+ builds become golden examples.</p>
      {/* Stars */}
      <div className="flex items-center gap-1">
        {[1,2,3,4,5].map(n => (
          <button
            key={n}
            onMouseEnter={() => setFeedbackHover(n)}
            onMouseLeave={() => setFeedbackHover(0)}
            onClick={() => setFeedbackRating(n)}
            className="p-0.5 transition-transform hover:scale-110"
            aria-label={`Rate ${n} star${n !== 1 ? 's' : ''}`}
          >
            <Star
              className={`w-7 h-7 transition-colors ${
                n <= (feedbackHover || feedbackRating) ? 'text-yellow-400 fill-yellow-400' : 'text-slate-600'
              }`}
            />
          </button>
        ))}
        {feedbackRating > 0 && (
          <span className="ml-2 text-sm font-bold text-yellow-400">
            {['', 'Poor', 'Fair', 'Good', 'Great', 'Excellent'][feedbackRating]}
          </span>
        )}
      </div>
      {/* Tags + comment + submit */}
      {feedbackRating > 0 && (
        <>
          <div className="flex flex-wrap gap-2">
            {FEEDBACK_TAGS.map(tag => (
              <button
                key={tag}
                onClick={() => setFeedbackTags(ts => ts.includes(tag) ? ts.filter(t => t !== tag) : [...ts, tag])}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  feedbackTags.includes(tag)
                    ? 'bg-accent/20 border-accent text-accent'
                    : 'bg-surface border-border text-muted hover:border-accent/40'
                }`}
              >
                {tag}
              </button>
            ))}
          </div>
          <input
            type="text"
            value={feedbackComment}
            onChange={e => setFeedbackComment(e.target.value)}
            placeholder="Optional comment…"
            className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
          />
          <button
            disabled={feedbackSubmitting}
            onClick={async () => {
              setFeedbackSubmitting(true);
              setFeedbackError(null);
              try {
                await api.client.post(`/factory/runs/${run.id}/feedback`, {
                  rating: feedbackRating,
                  tags: feedbackTags,
                  comment: feedbackComment || null,
                });
                setFeedbackSubmitted(true);
              } catch (e) {
                console.warn('Feedback submission failed:', e);
                setFeedbackError('Could not submit rating. Please try again.');
              } finally {
                setFeedbackSubmitting(false);
              }
            }}
            className="flex items-center gap-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-sm font-bold px-4 py-2 rounded-lg transition-colors"
          >
            <Star className="w-3.5 h-3.5" />
            {feedbackSubmitting ? 'Saving…' : 'Submit Rating'}
          </button>
          {feedbackError && (
            <p className="text-xs text-danger mt-1">{feedbackError}</p>
          )}
        </>
      )}
    </section>
  );
};

export default FeedbackPanel;
