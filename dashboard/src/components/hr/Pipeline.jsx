import React, { useState } from 'react';
import { hr, useHr, when, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table, SpecForm } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { ReqSelect, Detail, ScreenLink } from './hrParts';

const REASONS = ['must_have_not_evidenced', 'interview_evaluation', 'work_sample_evaluation', 'position_closed', 'candidate_declined', 'no_response', 'other_documented'];

const Duplicates = () => {
  const q = useHr('ATS_CORE', 'duplicate_review', { status: 'pending' });
  const act = useAct();
  const resolve = (x, same) => act.run(async () => { const out = await hr('ATS_CORE', 'resolve_duplicate', { review_id: x.id, same_person: same }); q.reload(); return out; },
    { title: same ? 'Mark as the same person?' : 'Mark as different people?', message: 'This records the link. Nothing is merged or deleted.' });
  return (
    <Card title="Duplicate review">
      {act.view}
      <LoadView q={q} isEmpty={(d) => (d.items || []).length === 0} emptyText="No possible duplicates are waiting.">
        {(d) => d.items.map((x) => (
          <div key={x.id} className="border border-border rounded-lg p-3 space-y-2">
            <Detail data={{ candidates: x.candidate_ids || x.pair, matched_on: x.reasons || x.fields, score: x.score }} />
            <div className="flex gap-2"><button className={btn()} disabled={act.busy} onClick={() => resolve(x, true)}>Same person</button><button className={btn('ghost')} disabled={act.busy} onClick={() => resolve(x, false)}>Different people</button></div>
          </div>
        ))}
      </LoadView>
    </Card>
  );
};

const Application = ({ id, stages, done }) => {
  const q = useHr('ATS_CORE', 'get_application', { application_id: id });
  const act = useAct();
  const move = (v) => act.run(async () => { const out = await hr('ATS_CORE', 'move_stage', { application_id: id, ...v }); done(); q.reload(); return out; },
    { title: `Move to ${v.to_stage}?`, message: `The move is written to the decision log under your name${v.reason_code ? ` with reason ${v.reason_code}` : ''}.` });
  return (
    <Card title="Application">
      <LoadView q={q}>
        {(d) => (
          <div className="space-y-3">
            <Detail data={{ stage: d.application?.stage, source: d.application?.source, candidate_id: d.application?.candidate_id }} />
            <SpecForm submitLabel="Move" busy={act.busy} onSubmit={move} fields={[
              { name: 'to_stage', label: 'To stage', type: 'select', options: stages, required: true },
              { name: 'reason_code', label: 'Reason (needed to reject)', type: 'select', options: REASONS },
              { name: 'note', label: 'Note', type: 'text' },
            ]} />
            {act.view}
          </div>
        )}
      </LoadView>
    </Card>
  );
};

const Board = ({ req }) => {
  const q = useHr('ATS_CORE', 'pipeline', { requisition_id: req });
  const log = useHr('ATS_CORE', 'decision_log', { requisition_id: req });
  const [app, setApp] = useState(null);
  return (
    <>
      <LoadView q={q}>
        {(d) => {
          const stages = Object.keys(d.stages || {});
          return (
            <>
              <p className="text-[11px] text-muted">{d.order}</p>
              <div className="flex gap-3 overflow-x-auto pb-2" aria-label="Pipeline board">
                {stages.map((s) => (
                  <div key={s} className="w-44 shrink-0 bg-panel border border-border rounded-xl p-2 space-y-2">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-muted">{s} · {d.stages[s].length}</p>
                    {d.stages[s].map((a) => (
                      <button key={a.application_id} onClick={() => setApp(a.application_id)} className={`w-full text-left bg-surface border rounded-lg p-2 text-xs ${app === a.application_id ? 'border-accent' : 'border-border'}`}>
                        <span className="font-mono text-bright">{a.application_id.slice(0, 12)}</span><br /><span className="text-muted">{a.source} · {a.days_in_stage}d</span>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
              {app && <Application id={app} stages={stages} done={() => { q.reload(); log.reload(); }} />}
            </>
          );
        }}
      </LoadView>
      <Card title="Decision log">
        <LoadView q={log} isEmpty={(d) => (d.entries || []).length === 0} emptyText="No decisions recorded yet.">
          {(d) => <Table rows={d.entries} cols={[['When', (e) => when(e.at)], ['By', (e) => e.by], ['From', (e) => e.from], ['To', (e) => e.to], ['Reason', (e) => e.reason_code || ''], ['Note', (e) => e.note]]} />}
        </LoadView>
      </Card>
    </>
  );
};

const Pipeline = () => {
  const [req, setReq] = useState('');
  return (
    <div className="space-y-4">
      <ScreenLink to="candidates">Add a candidate or application by hand, record an offer outcome, a consent withdrawal, a data export or an erasure:</ScreenLink>
      <ReqSelect value={req} onChange={setReq} />
      {req ? <Board key={req} req={req} /> : <p className="text-sm text-muted">Choose a requisition to see its pipeline.</p>}
      <Duplicates />
    </div>
  );
};

export default Pipeline;
