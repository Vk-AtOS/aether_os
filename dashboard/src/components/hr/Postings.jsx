import React, { useState } from 'react';
import { hr, useHr, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table, SpecForm } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { ReqSelect, Detail, StateBadge } from './hrParts';
import { inputClass } from '../prime/parts';

// The JSON-LD and any HTML are shown as text, never rendered as markup.
const Posting = ({ id }) => {
  const q = useHr('JOB_POSTINGS', 'get_posting', { posting_id: id });
  const packs = useHr('JOB_POSTINGS', 'list_packs', { posting_id: id });
  const act = useAct();
  const doit = (method, args, title, message, after) => act.run(async () => { const out = await hr('JOB_POSTINGS', method, args); (after || (() => { q.reload(); packs.reload(); }))(); return out; }, { title, message });
  return (
    <div className="space-y-3">
      {act.view}
      <LoadView q={q}>
        {(d) => {
          const p = d.posting || {};
          return (
            <Card title={`Posting ${id.slice(0, 12)}`} actions={<StateBadge state={p.status || p.state || 'draft'} />}>
              <div className="flex flex-wrap gap-2">
                <button className={btn()} disabled={act.busy} onClick={() => doit('approve_posting', { posting_id: id }, 'Approve posting?', 'A hiring manager approves what will be public.')}>Approve</button>
                <button className={btn('ghost')} disabled={act.busy} onClick={() => doit('mark_posting_live', { posting_id: id }, 'Mark live?', 'Record that this posting is now public on the careers page.')}>Mark live</button>
                <button className={btn('danger')} disabled={act.busy} onClick={() => doit('take_down_posting', { posting_id: id }, 'Take the posting down?', 'The posting is withdrawn from the careers page.')}>Take down</button>
              </div>
              <p className="text-xs font-bold text-muted uppercase tracking-wider">Preview (JSON-LD)</p>
              <pre className="bg-surface border border-border rounded-lg p-3 text-xs text-bright font-mono overflow-auto max-h-72 whitespace-pre-wrap break-all">{JSON.stringify(p.json_ld || p.jsonld || p.structured_data || p, null, 2)}</pre>
              {(p.html || d.html) && <><p className="text-xs font-bold text-muted uppercase tracking-wider">HTML (as source)</p><pre className="bg-surface border border-border rounded-lg p-3 text-xs text-bright font-mono overflow-auto max-h-48 whitespace-pre-wrap break-all">{p.html || d.html}</pre></>}
            </Card>
          );
        }}
      </LoadView>
      <Card title="Posting packs (job boards)">
        <PackForm id={id} doit={doit} busy={act.busy} />
        <LoadView q={packs} isEmpty={(d) => (d.packs || []).length === 0} emptyText="No packs yet. Prepare one for a board.">
          {(d) => d.packs.map((k) => (
            <div key={k.id} className="border border-border rounded-lg p-3 space-y-2">
              <p className="text-sm text-bright font-semibold">{k.board_name || k.board} <StateBadge state={k.status || k.state || 'prepared'} /></p>
              {(k.checklist || []).length > 0 && <ul className="text-xs text-bright">{k.checklist.map((c, i) => <li key={i}>[{c.done ? 'x' : ' '}] {typeof c === 'string' ? c : c.item || c.text || JSON.stringify(c)}</li>)}</ul>}
              <Detail data={{ takedown_date: k.takedown_date, takedown_task: k.takedown_task, live_url: k.live_url }} />
              <div className="flex gap-2">
                <button className={btn('ghost')} disabled={act.busy} onClick={() => doit('approve_pack', { pack_id: k.id }, 'Approve this pack?', 'Approve the content for this board.')}>Approve</button>
                <button className={btn('ghost')} disabled={act.busy} onClick={() => doit('mark_pack_posted', { pack_id: k.id }, 'Mark as posted?', 'You have posted it on the board yourself; this records that.')}>Mark posted</button>
                <button className={btn('danger')} disabled={act.busy} onClick={() => doit('mark_pack_taken_down', { pack_id: k.id }, 'Mark as taken down?', 'You removed it from the board; this records that.')}>Taken down</button>
              </div>
            </div>
          ))}
        </LoadView>
      </Card>
    </div>
  );
};

const PackForm = ({ id, doit, busy }) => {
  const [board, setBoard] = useState('');
  return (
    <div className="flex gap-2">
      <input className={`${inputClass} max-w-xs`} placeholder="Board name" aria-label="Board" value={board} onChange={(e) => setBoard(e.target.value)} />
      <button className={btn()} disabled={!board || busy} onClick={() => doit('prepare_pack', { posting_id: id, board }, 'Prepare a pack?', `Prepare the posting text and checklist for ${board}.`)}>Prepare pack</button>
    </div>
  );
};

const Postings = () => {
  const [req, setReq] = useState('');
  const [posting, setPosting] = useState('');
  const act = useAct();
  const due = useHr('JOB_POSTINGS', 'takedown_due', { within_days: 7 });
  const prepare = (v) => act.run(async () => { const out = await hr('JOB_POSTINGS', 'prepare_careers_posting', { requisition_id: req, ...v }); if (out.result?.posting?.id) setPosting(out.result.posting.id); return out; },
    { title: 'Prepare a careers posting?', message: 'A posting draft is made from the requisition. Nothing is public until it is approved and marked live.' });
  return (
    <div className="space-y-4">
      <Card title="Prepare a posting">
        <ReqSelect value={req} onChange={setReq} />
        {req && <SpecForm submitLabel="Prepare posting" busy={act.busy} onSubmit={prepare} fields={[{ name: 'valid_through', label: 'Valid through', type: 'date', required: true }, { name: 'salary', label: 'Salary (JSON, optional)', type: 'json' }]} />}
        {act.view}
        <div className="flex gap-2 items-center">
          <input className={`${inputClass} max-w-xs`} placeholder="Open a posting by id" aria-label="Posting id" value={posting} onChange={(e) => setPosting(e.target.value)} />
        </div>
      </Card>
      {posting && <Posting key={posting} id={posting} />}
      <Card title="Take-downs due in 7 days">
        <LoadView q={due} isEmpty={(d) => (d.tasks || []).length === 0} emptyText="Nothing is due.">
          {(d) => <Table rows={d.tasks} cols={[['Board', (t) => t.board], ['Pack', (t) => t.pack_id], ['Date', (t) => t.takedown_date], ['Task', (t) => t.task]]} />}
        </LoadView>
      </Card>
    </div>
  );
};

export default Postings;
