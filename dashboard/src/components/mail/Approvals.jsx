import React, { useCallback, useState } from 'react';
import { vc, useVelaris, btn } from '../velaris/velarisApi';
import { LoadView, Card } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { inputClass } from '../prime/parts';

// Sends held for a second person. The decision names the payload hash that is shown, so a changed message cannot be approved by mistake.
const Row = ({ a, done }) => {
  const [note, setNote] = useState('');
  const act = useAct();
  const p = a.preview || {};
  const decide = (approve) => act.run(async () => {
    await vc.post(`/mail/submissions/${a.id}/decide`, { approve, payload_hash: a.payload_hash, note }).catch((e) => { throw new Error(e?.response?.data?.error?.message || 'The decision was refused.'); });
    done();
    return {};
  }, { title: approve ? 'Approve this send?' : 'Reject this send?', message: `${approve ? 'The message will be sent' : 'The message will not be sent'}. Payload hash ${a.payload_hash}. Recorded under your name.` });
  return (
    <Card title={`To ${(p.to || []).join(', ') || '?'}`}>
      <p className="text-sm text-bright font-semibold">{p.subject || '(no subject)'}</p>
      <p className="text-xs text-muted">From {p.from} · submitted by {a.submitted_by}</p>
      <p className="text-xs font-bold text-warning mt-1">Why it needs approval</p>
      <ul className="list-disc ml-5 text-xs text-bright">{(a.reasons || []).map((r) => <li key={r.code}>{r.text}</li>)}</ul>
      <pre className="whitespace-pre-wrap text-xs text-bright bg-surface rounded p-2 max-h-48 overflow-auto">{p.text}</pre>
      {(p.attachments || []).length > 0 && <p className="text-xs text-muted">Attachments: {p.attachments.map((x) => x.name).join(', ')}</p>}
      <p className="text-[10px] font-mono text-muted break-all">payload hash {a.payload_hash}</p>
      <input className={inputClass} placeholder="Note (optional)" aria-label="Decision note" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="flex gap-2"><button className={btn()} disabled={act.busy} onClick={() => decide(true)}>Approve</button><button className={btn('danger')} disabled={act.busy} onClick={() => decide(false)}>Reject</button></div>
      {act.view}
    </Card>
  );
};

const Approvals = () => {
  const f = useCallback(() => vc.get('/mail/approvals'), []);
  const q = useVelaris(f);
  return (
    <LoadView q={q} isEmpty={(d) => d.approvals.length === 0} emptyText="No messages are waiting for your approval.">
      {(d) => <div className="space-y-3">{d.approvals.map((a) => <Row key={a.id} a={a} done={q.reload} />)}</div>}
    </LoadView>
  );
};

export default Approvals;
