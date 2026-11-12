import React, { useState } from 'react';
import { Users, Loader2, AlertTriangle, Star } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';

const CouncilPanel = ({ runId }) => {
  const [councilReport, setCouncilReport] = useState(null);
  const [councilLoading, setCouncilLoading] = useState(false);
  const [councilError, setCouncilError] = useState(null);

  const runCouncil = async () => {
    setCouncilLoading(true);
    setCouncilError(null);
    try {
      const res = await api.client.post(`/factory/runs/${runId}/council-review`);
      setCouncilReport(res.data);
    } catch (e) {
      setCouncilError(apiError(e) || e.message || 'Council review failed');
    } finally {
      setCouncilLoading(false);
    }
  };

  return (
    <div className="flex flex-col" style={{ minHeight: '420px' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-border/10 shrink-0">
        <div className="flex items-center space-x-2">
          <Users className="w-4 h-4 text-accent" />
          <span className="text-xs font-bold text-muted uppercase tracking-wider">LLM Council Review</span>
          <span className="text-[10px] text-muted">Multi-model code analysis</span>
        </div>
        <button
          onClick={runCouncil}
          disabled={councilLoading}
          className="flex items-center space-x-1.5 px-3 py-1.5 bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition-colors"
        >
          {councilLoading
            ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /><span>Running…</span></>
            : <><Users className="w-3.5 h-3.5" /><span>Run Council Review</span></>
          }
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
        {/* Not yet run */}
        {!councilReport && !councilLoading && !councilError && (
          <div className="h-full flex flex-col items-center justify-center text-muted space-y-3 py-12">
            <Users className="w-10 h-10 opacity-30" />
            <p className="text-sm font-medium">No council review yet</p>
            <p className="text-xs text-center max-w-sm opacity-70">
              Click "Run Council Review" to have Claude, Gemini, and Ollama independently
              review your generated code from different perspectives.
            </p>
          </div>
        )}

        {councilLoading && (
          <div className="h-full flex flex-col items-center justify-center space-y-4 py-12">
            <Loader2 className="w-8 h-8 text-violet-400 animate-spin" />
            <p className="text-sm text-muted">Council reviewing your code…</p>
            <p className="text-xs text-muted opacity-60">This takes 30-60 seconds</p>
          </div>
        )}

        {councilError && !councilLoading && (
          <div className="flex items-start space-x-3 p-4 bg-red-900/20 border border-red-700/40 rounded-lg">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-red-300">Council review failed</p>
              <p className="text-xs text-red-400 mt-1">{councilError}</p>
            </div>
          </div>
        )}

        {councilReport && !councilLoading && (
          <div className="space-y-4">
            {councilReport.consensus_issues && councilReport.consensus_issues.length > 0 && (
              <div className="p-4 bg-amber-900/20 border border-amber-700/40 rounded-lg">
                <div className="flex items-center space-x-2 mb-3">
                  <AlertTriangle className="w-4 h-4 text-amber-400" />
                  <span className="text-sm font-bold text-amber-300">
                    Consensus Issues ({councilReport.consensus_issues.length} found by multiple models)
                  </span>
                </div>
                <ul className="space-y-1.5">
                  {councilReport.consensus_issues.map((issue, i) => (
                    <li key={i} className="flex items-start space-x-2 text-xs text-amber-200">
                      <span className="shrink-0 w-4 h-4 rounded-full bg-amber-600 text-amber-100 flex items-center justify-center text-[9px] font-bold mt-0.5">{i + 1}</span>
                      <span>{issue}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="grid gap-3">
              {(councilReport.reviews || []).map((review, i) => {
                const modelColors = {
                  claude: { bg: 'bg-orange-900/20', border: 'border-orange-700/40', badge: 'bg-orange-700', text: 'text-orange-300' },
                  gemini: { bg: 'bg-blue-900/20', border: 'border-blue-700/40', badge: 'bg-blue-700', text: 'text-blue-300' },
                  ollama: { bg: 'bg-green-900/20', border: 'border-green-700/40', badge: 'bg-green-700', text: 'text-green-300' },
                };
                const c = modelColors[review.model] || modelColors.ollama;
                const scoreColor = review.score >= 7 ? 'text-emerald-400' : review.score >= 4 ? 'text-amber-400' : 'text-red-400';
                return (
                  <div key={i} className={`p-4 ${c.bg} border ${c.border} rounded-lg`}>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center space-x-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider text-white ${c.badge}`}>
                          {review.model}
                        </span>
                        <span className={`text-xs ${c.text}`}>{review.focus}</span>
                      </div>
                      <div className="flex items-center space-x-1">
                        <Star className="w-3.5 h-3.5 text-muted" />
                        <span className={`text-sm font-bold ${scoreColor}`}>{review.score}/10</span>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      {review.issues && review.issues.length > 0 && (
                        <div>
                          <p className="text-[10px] font-bold text-red-400 uppercase tracking-wider mb-1.5">Issues ({review.issues.length})</p>
                          <ul className="space-y-1">
                            {review.issues.map((issue, j) => (
                              <li key={j} className="flex items-start space-x-1.5 text-xs text-slate-300">
                                <span className="text-red-400 shrink-0 mt-0.5">•</span>
                                <span>{issue}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {review.strengths && review.strengths.length > 0 && (
                        <div>
                          <p className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider mb-1.5">Strengths ({review.strengths.length})</p>
                          <ul className="space-y-1">
                            {review.strengths.map((s, j) => (
                              <li key={j} className="flex items-start space-x-1.5 text-xs text-slate-300">
                                <span className="text-emerald-400 shrink-0 mt-0.5">•</span>
                                <span>{s}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {councilReport.reviews && councilReport.reviews.length === 0 && (
              <div className="mt-2 p-4 rounded-lg bg-amber-900/20 border border-amber-700/30">
                <p className="text-sm font-medium text-amber-400 mb-1">No model responses received</p>
                <p className="text-xs text-amber-300/70">
                  Add API keys in{' '}
                  <a href="/dashboard/settings" className="underline text-amber-300 hover:text-amber-200">
                    Settings → API Keys
                  </a>{' '}
                  to enable Claude and Gemini reviews, or start Ollama locally for a free offline review.
                </p>
              </div>
            )}

            <p className="text-[10px] text-muted text-right">
              Generated {councilReport.created_at ? new Date(councilReport.created_at).toLocaleString() : ''}
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default CouncilPanel;
