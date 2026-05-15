import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { Brain, CheckCircle, HelpCircle, Loader2 } from 'lucide-react';

const Learning = () => {
  const [patterns, setPatterns] = useState([]);
  const [clarifications, setClarifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [answers, setAnswers] = useState({});
  const [submitting, setSubmitting] = useState({});
  const [toast, setToast] = useState('');

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  const load = async () => {
    setLoading(true);
    try {
      const [ctx, clr] = await Promise.all([
        api.client.get('/learning/context').catch(() => ({ data: { patterns: [] } })),
        api.client.get('/learning/clarifications').catch(() => ({ data: { clarifications: [] } })),
      ]);
      const raw = ctx.data?.patterns;
      setPatterns(Array.isArray(raw) ? raw : Object.entries(raw || {}).map(([k, v]) => ({ description: typeof v === 'string' ? v : JSON.stringify(v), domain: k })));
      setClarifications(clr.data?.clarifications || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleAnswer = async (id) => {
    const answer = answers[id];
    if (!answer?.trim()) return showToast('Please enter an answer');
    setSubmitting(s => ({ ...s, [id]: true }));
    try {
      await api.client.post(`/learning/clarifications/${id}/answer`, { answer });
      showToast('✅ Answer saved');
      setClarifications(c => c.filter(q => q.id !== id));
    } catch (e) {
      showToast('Failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setSubmitting(s => ({ ...s, [id]: false }));
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-muted">
      <Loader2 className="w-6 h-6 animate-spin mr-2" /> Loading learning data…
    </div>
  );

  return (
    <div className="max-w-3xl mx-auto py-6 space-y-8">
      {toast && (
        <div className="fixed top-4 right-4 bg-panel border border-border rounded-lg px-4 py-2 text-sm text-bright shadow-xl z-50">{toast}</div>
      )}

      <div>
        <h1 className="text-2xl font-bold text-bright flex items-center gap-2">
          <Brain className="w-6 h-6 text-accent" /> Learning & Personalisation
        </h1>
        <p className="text-sm text-muted mt-1">AetherOS learns from your past runs and preferences to generate better results over time.</p>
      </div>

      {/* Pending clarification questions */}
      {clarifications.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-base font-semibold text-bright flex items-center gap-2">
            <HelpCircle className="w-4 h-4 text-yellow-400" /> Pending Questions
          </h2>
          <p className="text-xs text-muted">Answering these helps AetherOS generate better code for your specific context.</p>
          {clarifications.map(q => (
            <div key={q.id} className="bg-surface border border-border rounded-xl p-4 space-y-3">
              <p className="text-sm text-bright">{q.question}</p>
              {q.context && <p className="text-xs text-muted italic">{q.context}</p>}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={answers[q.id] || ''}
                  onChange={e => setAnswers(a => ({ ...a, [q.id]: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && handleAnswer(q.id)}
                  placeholder="Your answer…"
                  className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                />
                <button
                  onClick={() => handleAnswer(q.id)}
                  disabled={submitting[q.id]}
                  className="px-4 py-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-sm font-bold rounded-lg transition-colors"
                >
                  {submitting[q.id] ? '…' : 'Save'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Learned patterns */}
      <div className="space-y-4">
        <h2 className="text-base font-semibold text-bright flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-emerald-400" /> Learned Patterns
        </h2>
        {patterns.length === 0 ? (
          <div className="bg-surface border border-border rounded-xl p-8 text-center">
            <Brain className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-muted text-sm">No learned patterns yet. Run a few pipelines and AetherOS will start personalising results.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {patterns.map((p, i) => (
              <div key={i} className="bg-surface border border-border rounded-lg px-4 py-3 flex items-start gap-3">
                <span className="text-xs text-accent font-mono mt-0.5">{String(i + 1).padStart(2, '0')}</span>
                <div className="flex-1">
                  <p className="text-sm text-bright">{typeof p === 'string' ? p : p.description || JSON.stringify(p)}</p>
                  {p.domain && <span className="text-[10px] text-muted">{p.domain}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default Learning;
