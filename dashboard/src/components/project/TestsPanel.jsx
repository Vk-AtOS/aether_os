import React, { useState, useEffect } from 'react';
import { CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';

// Test result of a run (unit-test phase): counts and the failure messages.
const TestsPanel = ({ runId }) => {
  const [state, setState] = useState({ loading: true, report: null, error: null });
  useEffect(() => {
    let live = true;
    api.getTestReport(runId)
      .then((res) => live && setState({ loading: false, report: res.data, error: null }))
      .catch((e) => live && setState({ loading: false, report: null, error: e?.response?.status === 404 ? null : (apiError(e) || 'Could not load the test report.') }));
    return () => { live = false; };
  }, [runId]);

  if (state.loading) return <div className="p-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-accent" /></div>;
  if (state.error) return <div role="alert" className="m-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-danger text-xs">{state.error}</div>;
  if (!state.report) return <p className="p-8 text-center text-sm text-muted">No test report was recorded for this run yet. It appears once the unit-test stage has run.</p>;
  const { passed = 0, failed = 0, errors = [], tests_written: written } = state.report;
  return (
    <div className="p-4 space-y-4" style={{ minHeight: '420px' }}>
      <div className="flex gap-6 text-sm">
        <span className="flex items-center gap-2 text-emerald-400"><CheckCircle2 className="w-4 h-4" />{passed} passed</span>
        <span className={`flex items-center gap-2 ${failed ? 'text-danger' : 'text-muted'}`}><XCircle className="w-4 h-4" />{failed} failed</span>
        {written != null && <span className="text-muted">{written} tests written</span>}
      </div>
      {errors.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-[10px] font-bold uppercase tracking-widest text-muted">Failures and errors</h4>
          {errors.map((e, i) => <pre key={i} className="bg-surface border border-border rounded-lg p-3 text-[11px] text-danger whitespace-pre-wrap break-words">{String(e)}</pre>)}
        </div>
      )}
    </div>
  );
};

export default TestsPanel;
