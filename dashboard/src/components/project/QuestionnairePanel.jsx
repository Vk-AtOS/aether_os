import React, { useState, useEffect, useCallback } from 'react';
import { ClipboardList, Loader2 } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';

const input = 'w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs text-bright';

// Agency side of client questionnaires for one run: sessions and whether the client answered, send a link by
// email, or fill the answers in on the client's behalf. The server needs member or above for all of it.
const QuestionnairePanel = ({ runId, isViewer }) => {
  const [sessions, setSessions] = useState([]);
  const [stages, setStages] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [send, setSend] = useState({ stage_id: '', respondent_email: '', respondent_name: '' });
  const [fillStage, setFillStage] = useState('');
  const [answers, setAnswers] = useState({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => Promise.all([api.listQuestionnaires(runId), api.getQuestionnaireStages()])
    .then(([s, st]) => { setSessions(s.data ?? []); setStages(st.data ?? []); setError(null); })
    .catch((e) => setError(apiError(e) || 'Could not load questionnaires.')), [runId]);
  useEffect(() => { load(); }, [load]);

  const act = async (fn, okMsg) => {
    setBusy(true); setError(null); setNotice(null);
    try { const res = await fn(); setNotice(okMsg(res.data)); await load(); return true; }
    catch (e) { setError(apiError(e) || 'The request failed.'); return false; }
    finally { setBusy(false); }
  };

  const onSend = (e) => {
    e.preventDefault();
    return act(() => api.sendQuestionnaire(runId, send), (d) => (d.email_sent
      ? `Sent. The link expires ${new Date(d.expires_at).toLocaleDateString()}.`
      : `Created, but no email was sent (email is not configured). Share this link yourself: ${d.share_url}`));
  };

  const questions = stages.find((s) => s.id === fillStage)?.questions ?? [];
  const onFill = async (e) => {
    e.preventDefault();
    if (await act(() => api.fillQuestionnaire(runId, { stage_id: fillStage, answers }), () => 'Saved on the client’s behalf; the run can continue.')) setAnswers({});
  };
  const field = (q) => {
    const set = (v) => setAnswers((p) => ({ ...p, [q.id]: v }));
    const val = answers[q.id] ?? '';
    if (q.type === 'textarea') return <textarea id={`q-${q.id}`} className={input} value={val} onChange={(e) => set(e.target.value)} />;
    if (q.type === 'boolean') return <input id={`q-${q.id}`} type="checkbox" checked={!!answers[q.id]} onChange={(e) => set(e.target.checked)} />;
    if (q.type === 'select') return (
      <select id={`q-${q.id}`} className={input} value={val} onChange={(e) => set(e.target.value)}>
        <option value="">Choose…</option>{(q.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
      </select>);
    if (q.type === 'multiselect') return (
      <select id={`q-${q.id}`} multiple className={input} value={answers[q.id] ?? []}
        onChange={(e) => set([...e.target.selectedOptions].map((o) => o.value))}>
        {(q.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
      </select>);
    return <input id={`q-${q.id}`} type={q.type === 'number' ? 'number' : 'text'} className={input} value={val}
      onChange={(e) => set(q.type === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value)} />;
  };

  return (
    <div className="p-4 space-y-5" style={{ minHeight: '420px' }}>
      <div className="flex items-center gap-2 text-xs font-bold text-muted uppercase tracking-wider">
        <ClipboardList className="w-4 h-4 text-accent" />Client questionnaires
      </div>
      {error && <div role="alert" className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-danger text-xs">{error}</div>}
      {notice && <div role="status" className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs break-all">{notice}</div>}

      {sessions.length === 0 ? <p className="text-xs text-muted">No questionnaires sent for this run yet.</p> : (
        <table className="w-full text-xs"><thead><tr className="text-left text-[10px] uppercase text-muted">
          <th>Stage</th><th>Respondent</th><th>Status</th><th>Expires</th><th /></tr></thead>
          <tbody>{sessions.map((s) => (
            <tr key={s.id} className="border-t border-border">
              <td className="py-1.5 text-bright">{s.stage_id}</td><td>{s.respondent_email || 'filled by agency'}</td>
              <td className={s.status === 'completed' ? 'text-emerald-400' : 'text-amber-400'}>{s.status}</td>
              <td>{s.expires_at ? new Date(s.expires_at).toLocaleDateString() : ''}</td>
              <td />
            </tr>))}</tbody></table>
      )}

      {!isViewer && (
        <>
          <form onSubmit={onSend} className="space-y-2">
            <h4 className="text-[10px] font-bold uppercase tracking-widest text-muted">Send to the client</h4>
            <select aria-label="Stage to send" required className={input} value={send.stage_id} onChange={(e) => setSend({ ...send, stage_id: e.target.value })}>
              <option value="">Stage…</option>{stages.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
            <input aria-label="Client email" type="email" required placeholder="client@example.com" className={input} value={send.respondent_email} onChange={(e) => setSend({ ...send, respondent_email: e.target.value })} />
            <input aria-label="Client name" placeholder="Client name" className={input} value={send.respondent_name} onChange={(e) => setSend({ ...send, respondent_name: e.target.value })} />
            <button disabled={busy} className="px-4 py-2 bg-accent text-white text-xs font-bold rounded-lg disabled:opacity-50">{busy ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Send questionnaire'}</button>
          </form>

          <form onSubmit={onFill} className="space-y-2">
            <h4 className="text-[10px] font-bold uppercase tracking-widest text-muted">Fill in on the client’s behalf</h4>
            <select aria-label="Stage to fill" required className={input} value={fillStage} onChange={(e) => { setFillStage(e.target.value); setAnswers({}); }}>
              <option value="">Stage…</option>{stages.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
            {questions.map((q) => (
              <div key={q.id}><label htmlFor={`q-${q.id}`} className="block text-[11px] text-muted mb-0.5">{q.label}{q.required ? ' *' : ''}</label>{field(q)}</div>
            ))}
            {fillStage && <button disabled={busy} className="px-4 py-2 bg-violet-700 text-white text-xs font-bold rounded-lg disabled:opacity-50">Save answers</button>}
          </form>
        </>
      )}
    </div>
  );
};

export default QuestionnairePanel;
