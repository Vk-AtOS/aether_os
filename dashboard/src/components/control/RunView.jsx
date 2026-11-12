import React, { useCallback, useEffect, useState } from 'react';
import { vc, vError, useVelaris, btn } from '../velaris/velarisApi';
import { LoadView, Card, Notice } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { Facts, Json, Pill, inputClass } from '../prime/parts';

const LIVE = ['running', 'waiting_approval'];
const tone = (s) => (s === 'succeeded' ? 'bg-success/15 text-success' : /fail|stopped|killed/.test(s) ? 'bg-danger/15 text-danger' : 'bg-warning/15 text-warning');

const Pending = ({ id, p, reload }) => {
  const [note, setNote] = useState('');
  const act = useAct();
  const a = p.args || {};
  const decide = (approve) => act.run(async () => {
    try { await vc.post(`/control/runs/${id}/decide`, { call_hash: p.call_hash, approve, note }); } catch (e) { throw new Error(vError(e)); }
    reload();
    return {};
  }, { title: approve ? 'Approve this step?' : 'Reject this step?', message: `${p.tool} ${JSON.stringify(a)}\nsnapshot ${a.snapshot_id ?? '?'} · call hash ${p.call_hash}\nRecorded under your name.` });
  return (
    <Card title="Waiting for approval">
      <Facts rows={[['Action', p.tool], ['Target', a.ref], ['Snapshot', a.snapshot_id], ['Call hash', p.call_hash], ['Why', p.reason]]} />
      <Json value={a} />
      <input className={inputClass} placeholder="Note (optional)" aria-label="Decision note" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="flex gap-2"><button className={btn()} disabled={act.busy} onClick={() => decide(true)}>Approve</button><button className={btn('danger')} disabled={act.busy} onClick={() => decide(false)}>Reject</button></div>
      {act.view}
    </Card>
  );
};

const Report = ({ id }) => {
  const f = useCallback(() => vc.get(`/control/runs/${id}/report`), [id]);
  const q = useVelaris(f);
  return (
    <LoadView q={q}>
      {(r) => (
        <div className="space-y-3">
          <Facts rows={[['Owner', r.owner], ['Active seconds', r.active_seconds], ['Observations', (r.observations || []).length], ['Journal chain', r.flow_chain ? JSON.stringify(r.flow_chain) : 'none']]} />
          <table className="w-full text-xs"><thead><tr className="text-left text-muted"><th>#</th><th>Action</th><th>Target</th><th>Snapshot</th><th>Verdict</th><th>Approval</th><th>Result</th></tr></thead>
            <tbody>{(r.actions || []).map((a) => (
              <tr key={a.n} className="border-t border-border"><td>{a.n}</td><td>{a.action}</td><td>{a.ref}</td><td>{a.snapshot_id}</td><td>{a.verdict}: {a.reason}</td>
                <td>{a.approver ? `${a.approved ? 'approved' : 'rejected'} by ${a.approver}` : ''}</td><td>{a.result_ok == null ? '' : a.result_ok ? 'ok' : 'failed'}</td></tr>
            ))}</tbody></table>
          {(r.denied || []).length > 0 && <Notice tone="warn">{r.denied.length} action(s) were refused by policy.</Notice>}
          {(r.irreversible || []).length > 0 && <Notice tone="warn">Irreversible effects that need a person: {r.irreversible.map((i) => i.kind).join(', ')}.</Notice>}
          <p className="text-xs text-muted">Changes journaled: {(r.changes || []).length} (undone: {(r.changes || []).filter((c) => c.undone).length})</p>
        </div>
      )}
    </LoadView>
  );
};

const RunView = ({ id }) => {
  const f = useCallback(() => vc.get(`/control/runs/${id}`), [id]);
  const q = useVelaris(f);
  const { reload } = q;
  const act = useAct();
  const live = q.data && LIVE.includes(q.data.status);
  useEffect(() => {
    if (!live) return undefined;
    const t = setInterval(reload, 3000);
    return () => clearInterval(t);
  }, [live, reload]);
  const post = (what, title, message) => act.run(async () => {
    try { await vc.post(`/control/runs/${id}/${what}`, {}); } catch (e) { throw new Error(vError(e)); }
    reload();
    return {};
  }, { title, message });

  return (
    <div className="space-y-3">
      <LoadView q={q}>
        {(s) => (
          <>
            <Card title={`Run ${s.task}`} actions={<Pill className={tone(s.status)}>{s.status}</Pill>}>
              <Facts rows={[['Run id', s.task_id], ['Owner', s.owner], ['Turns', s.turns], ['Claim', s.claim], ['Note', s.note]]} />
              {live && <p className="text-xs text-muted">Updating every few seconds.</p>}
              <div className="flex gap-2">
                {live && <button className={btn('danger')} disabled={act.busy} onClick={() => post('kill', 'Stop this run?', 'The run stops now. Changes already made stay until you undo them.')}>Kill run</button>}
                {!live && <button className={btn('ghost')} disabled={act.busy} onClick={() => post('undo', 'Undo this run?', 'The journal of changes is replayed backwards. Irreversible effects are not undone.')}>Undo changes</button>}
              </div>
              {act.view}
            </Card>
            {s.pending && <Pending id={id} p={s.pending} reload={reload} />}
            <Card title="Observations (what the run saw)">
              {(s.observations || []).length === 0 ? <p className="text-xs text-muted">Nothing observed yet.</p> : (
                <ul className="text-xs text-bright">{s.observations.map((o) => <li key={o.snapshot_id}>snapshot {o.snapshot_id}: {o.elements} elements</li>)}</ul>
              )}
            </Card>
            <Card title="Verification">
              {!s.verification ? <p className="text-xs text-muted">Not run yet. It runs when the work is done, reading the result back from the system of record.</p> : (
                <>
                  <Pill className={s.verification.ok ? 'bg-success/15 text-success' : 'bg-danger/15 text-danger'}>{s.verification.ok ? 'verified' : 'not verified'}</Pill>
                  <ul className="text-xs text-bright mt-2">{(s.verification.checks || []).map((c) => <li key={c.name}>{c.ok ? 'PASS' : 'FAIL'} {c.name} {c.detail}</li>)}</ul>
                </>
              )}
            </Card>
            <Card title="Report and steps"><Report id={id} key={s.status} /></Card>
          </>
        )}
      </LoadView>
    </div>
  );
};

export default RunView;
