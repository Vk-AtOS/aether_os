import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'

interface Trace {
  id: string
  phase: string
  task_type: string
  model: string
  attempt: number
  duration_ms: number
  tokens_in: number
  tokens_out: number
  parsed_ok: boolean
  error: string | null
  created_at: string
  has_prompt: boolean
  has_response: boolean
}

interface TraceDetail extends Trace {
  prompt: string
  raw_response: string
}

export function TraceTab({ runId }: { runId: string }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [detail, setDetail] = useState<Record<string, TraceDetail>>({})

  const { data: traces = [], isLoading } = useQuery<Trace[]>({
    queryKey: ['traces', runId],
    queryFn: () => apiClient.get(`/runs/${runId}/traces`).then(r => r.data),
    staleTime: 30_000,
  })

  const loadDetail = async (traceId: string) => {
    if (detail[traceId]) { setExpanded(traceId); return }
    const r = await apiClient.get(`/runs/${runId}/traces/${traceId}`)
    setDetail(d => ({ ...d, [traceId]: r.data }))
    setExpanded(traceId)
  }

  if (isLoading) {
    return (
      <div className="p-6 space-y-2" role="status" aria-label="Loading traces">
        {[1,2,3,4,5].map(i => <div key={i} className="h-14 bg-gray-100 rounded-lg animate-pulse" />)}
      </div>
    )
  }

  if (traces.length === 0) {
    return (
      <div className="p-12 text-center text-gray-400" role="status">
        <div className="text-4xl mb-3">🔍</div>
        <p className="text-sm">No LLM traces recorded for this run.</p>
        <p className="text-xs mt-1 text-gray-300">Traces are captured from core/llm/client.py after each call.</p>
      </div>
    )
  }

  // Group by phase for timeline display
  const byPhase: Record<string, Trace[]> = {}
  for (const t of traces) {
    if (!byPhase[t.phase]) byPhase[t.phase] = []
    byPhase[t.phase].push(t)
  }

  return (
    <div className="p-4 space-y-4" role="log" aria-label="LLM call trace timeline">
      {Object.entries(byPhase).map(([phase, phaseTraces]) => (
        <div key={phase} className="border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 flex items-center gap-3">
            <span className="text-xs font-mono font-bold text-gray-600 uppercase">{phase}</span>
            <span className="text-xs text-gray-400">{phaseTraces.length} call{phaseTraces.length !== 1 ? 's' : ''}</span>
            <span className="ml-auto text-xs text-gray-400">
              {phaseTraces.reduce((s, t) => s + (t.tokens_in + t.tokens_out), 0).toLocaleString()} total tokens
            </span>
          </div>
          <div className="divide-y divide-gray-100">
            {phaseTraces.map(trace => (
              <div key={trace.id} className="p-3">
                <button
                  onClick={() => expanded === trace.id ? setExpanded(null) : loadDetail(trace.id)}
                  className="w-full text-left flex items-center gap-3"
                  aria-expanded={expanded === trace.id}
                  aria-controls={`trace-detail-${trace.id}`}
                >
                  {/* Status dot */}
                  <span
                    className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                      !trace.parsed_ok ? 'bg-red-500' :
                      trace.attempt > 1 ? 'bg-yellow-400' : 'bg-green-500'
                    }`}
                    aria-label={trace.parsed_ok ? 'success' : 'failed'}
                  />
                  <span className="text-xs font-mono text-gray-500 flex-shrink-0 w-28">{trace.task_type}</span>
                  <span className="text-xs text-gray-400 flex-shrink-0">{trace.model}</span>
                  {trace.attempt > 1 && (
                    <span className="text-xs bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded font-medium">
                      attempt {trace.attempt}
                    </span>
                  )}
                  {trace.error && (
                    <span className="text-xs text-red-600 truncate flex-1">{trace.error}</span>
                  )}
                  <span className="ml-auto text-xs text-gray-400 flex-shrink-0">
                    {trace.duration_ms}ms · ↑{trace.tokens_in ?? '?'} ↓{trace.tokens_out ?? '?'}
                  </span>
                  <span className="text-gray-400 text-xs">{expanded === trace.id ? '▲' : '▼'}</span>
                </button>

                {expanded === trace.id && detail[trace.id] && (
                  <div
                    id={`trace-detail-${trace.id}`}
                    className="mt-3 space-y-3"
                  >
                    <div>
                      <div className="text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">Prompt</div>
                      <pre className="text-xs bg-gray-900 text-green-300 p-3 rounded-lg overflow-x-auto whitespace-pre-wrap max-h-64">
                        {detail[trace.id].prompt}
                      </pre>
                    </div>
                    <div>
                      <div className="text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
                        Response {trace.parsed_ok ? '✓ parsed' : '✗ parse failed'}
                      </div>
                      <pre className="text-xs bg-gray-900 text-blue-200 p-3 rounded-lg overflow-x-auto whitespace-pre-wrap max-h-64">
                        {detail[trace.id].raw_response}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
