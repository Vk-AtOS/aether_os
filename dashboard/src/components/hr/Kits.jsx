import React, { useState } from 'react';
import { hr, useHr, btn } from '../velaris/velarisApi';
import { LoadView, Card, SpecForm, Notice } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { ReqSelect, Detail } from './hrParts';
import { inputClass } from '../prime/parts';

// Scorecards stay hidden until you have submitted your own (Velaris decides; "visible: false" is shown as such).
const Scorecards = ({ app }) => {
  const q = useHr('INTERVIEW_KIT', 'scorecards', { application_id: app });
  return (
    <LoadView q={q}>
      {(d) => (
        <div className="space-y-3">
          <p className="text-xs text-muted">Expected: {(d.expected || []).join(', ') || 'nobody'} · submitted: {(d.submitted_by || []).join(', ') || 'nobody'}</p>
          {!d.visible ? <Notice tone="warn">{d.reason || 'Other interviewers\' scorecards are hidden until you submit yours.'}</Notice> : (
            <>
              {(d.competencies || []).map((c) => (
                <div key={c.competency} className="border border-border rounded-lg p-3 text-xs space-y-1">
                  <p className="text-sm font-bold text-bright">{c.competency} <span className="text-muted font-normal">mean {c.mean} from {c.n_raters} rater(s)</span></p>
                  <p className="font-mono text-muted">{c.working}</p>
                  {c.discuss && <Notice tone="warn">Disagreement: {c.discuss}</Notice>}
                  {c.ratings.map((r, i) => <p key={i} className="text-bright"><b>{r.interviewer}</b>: {r.score}, {r.evidence}</p>)}
                </div>
              ))}
              <p className="text-[11px] text-muted">{d.note}</p>
            </>
          )}
        </div>
      )}
    </LoadView>
  );
};

const Agreement = ({ req }) => {
  const q = useHr('INTERVIEW_KIT', 'agreement_report', { requisition_id: req });
  return <LoadView q={q}>{(d) => <><Detail data={{ rated_items: d.rated_items, raters: d.raters, krippendorff_alpha: d.krippendorff_alpha_ordinal }} />{d.statement && <p className="text-[11px] text-muted mt-2">{d.statement}</p>}</>}</LoadView>;
};

const Kits = () => {
  const [req, setReq] = useState('');
  const [app, setApp] = useState('');
  const [shown, setShown] = useState('');
  const kit = useHr('INTERVIEW_KIT', 'get_kit', { requisition_id: req });
  const act = useAct();
  const [ratings, setRatings] = useState([{ competency: '', score: 3, evidence: '' }]);
  const set = (i, p) => setRatings(ratings.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const submit = () => act.run(async () => { const out = await hr('INTERVIEW_KIT', 'submit_scorecard', { application_id: app, ratings: ratings.map((r) => ({ ...r, score: Number(r.score) })) }); setShown(app); return out; },
    { title: 'Submit your scorecard?', message: 'It is locked once submitted and cannot be changed. You may see other interviewers\' cards only after this.' });
  const create = (v) => act.run(async () => hr('INTERVIEW_KIT', 'create_kit', { requisition_id: req, ...v }).then((o) => { kit.reload(); return o; }),
    { title: 'Create the interview kit?', message: 'The competencies and questions become the kit every interviewer of this requisition scores against.' });
  return (
    <div className="space-y-4">
      {act.view}
      <Card title="Interview kit">
        <ReqSelect value={req} onChange={setReq} />
        {req && <LoadView q={kit} emptyText="No kit for this requisition yet.">{(d) => (<><Detail data={d.kit} />{(d.questions || []).map((x) => <p key={x.id} className="text-xs text-bright">• {x.text} <span className="text-muted">({x.competency})</span></p>)}</>)}</LoadView>}
        {req && <SpecForm submitLabel="Create kit" busy={act.busy} onSubmit={create} fields={[{ name: 'competencies', label: 'Competencies', type: 'list', required: true }, { name: 'question_ids', label: 'Question ids', type: 'list', required: true }]} />}
      </Card>
      <Card title="Submit your scorecard">
        <input className={`${inputClass} max-w-sm`} placeholder="Application id" aria-label="Application id" value={app} onChange={(e) => setApp(e.target.value)} />
        {ratings.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_5rem_2fr] gap-2">
            <input className={inputClass} placeholder="Competency" aria-label={`Competency ${i + 1}`} value={r.competency} onChange={(e) => set(i, { competency: e.target.value })} />
            <input type="number" min="1" max="5" className={inputClass} aria-label={`Score ${i + 1}`} value={r.score} onChange={(e) => set(i, { score: e.target.value })} />
            <input className={inputClass} placeholder="Evidence (what you saw)" aria-label={`Evidence ${i + 1}`} value={r.evidence} onChange={(e) => set(i, { evidence: e.target.value })} />
          </div>
        ))}
        <div className="flex gap-2"><button className={btn('ghost')} onClick={() => setRatings([...ratings, { competency: '', score: 3, evidence: '' }])}>Add competency</button><button className={btn()} disabled={!app || act.busy} onClick={submit}>Submit scorecard</button></div>
      </Card>
      <Card title="Scorecards of an application">
        <div className="flex gap-2"><input className={`${inputClass} max-w-sm`} placeholder="Application id" aria-label="Application id to view" value={app} onChange={(e) => setApp(e.target.value)} /><button className={btn()} disabled={!app} onClick={() => setShown(app)}>View</button></div>
        {shown && <Scorecards key={shown} app={shown} />}
      </Card>
      {req && <Card title="Interviewer agreement"><Agreement key={req} req={req} /></Card>}
    </div>
  );
};

export default Kits;
