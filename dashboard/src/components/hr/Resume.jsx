import React, { useState } from 'react';
import { hr, useHr, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table, SpecForm, Notice } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { ReqSelect, Detail, ScreenLink } from './hrParts';
import { inputClass } from '../prime/parts';

// Evidence, not a score: quotes from the résumé, gaps, and the arithmetic. Velaris makes no ranking and neither do we.
const Match = ({ evidence, req }) => {
  const q = useHr('RESUME_EVIDENCE', 'match_requisition', { evidence_id: evidence, requisition_id: req });
  return (
    <LoadView q={q}>
      {(m) => (
        <div className="space-y-3">
          {[['Must-have', m.must_have], ['Nice-to-have', m.nice_to_have]].map(([title, rows]) => (
            <div key={title}>
              <p className="text-xs font-bold text-muted uppercase tracking-wider mb-1">{title}: {title === 'Must-have' ? m.fit_summary?.must_have_with_evidence : m.fit_summary?.nice_to_have_with_evidence}</p>
              {(rows || []).map((e) => (
                <div key={e.skill_id} className="border border-border rounded-lg p-2 mb-2 text-xs">
                  <p className={e.found ? 'text-success' : 'text-warning'}>{e.label}: {e.found ? 'evidence found' : 'no mention found'}{e.min_years != null && ` (asks ${e.min_years}y, stated ${e.years_stated ?? 'none'})`}</p>
                  {(e.evidence || []).map((x, i) => <blockquote key={i} className="text-bright border-l-2 border-accent pl-2 mt-1">&ldquo;{x.quote}&rdquo; <span className="text-muted">({x.section})</span></blockquote>)}
                </div>
              ))}
            </div>
          ))}
          <Card title="Gaps">
            {(m.gaps || []).length === 0 ? <p className="text-xs text-muted">No gaps against the requisition.</p> : <ul className="text-xs text-bright list-disc ml-5">{m.gaps.map((g) => <li key={`${g.kind}-${g.skill_id}`}>{g.kind}: {g.label}, {g.reason}</li>)}</ul>}
          </Card>
          <Card title="The arithmetic"><ul className="text-xs text-bright list-disc ml-5">{(m.fit_summary?.arithmetic || []).map((a) => <li key={a}>{a}</li>)}</ul></Card>
          {(m['résumé_flags'] || []).length > 0 && <Notice tone="warn">Flags: {m['résumé_flags'].join('; ')}</Notice>}
          <p className="text-[11px] text-muted">{m.statement}</p>
        </div>
      )}
    </LoadView>
  );
};

const Unknown = () => {
  const q = useHr('RESUME_EVIDENCE', 'unknown_skills');
  const props = useHr('RESUME_EVIDENCE', 'alias_proposals', { status: 'proposed' });
  const act = useAct();
  const review = (p, approve) => act.run(async () => { const out = await hr('RESUME_EVIDENCE', 'review_alias', { proposal_id: p.id, approve }); props.reload(); return out; },
    { title: approve ? 'Approve this alias?' : 'Reject this alias?', message: `"${p.surface}" ${approve ? 'will be treated as the proposed skill in every future résumé' : 'stays unknown'}.` });
  return (
    <Card title="Unknown skills queue">
      {act.view}
      <LoadView q={q} isEmpty={(d) => !d.unknown || (Array.isArray(d.unknown) ? d.unknown.length === 0 : Object.keys(d.unknown).length === 0)} emptyText="No unknown skill phrases are waiting.">
        {(d) => <Detail data={d.unknown} />}
      </LoadView>
      <p className="text-xs font-bold text-muted uppercase tracking-wider pt-2">Proposed aliases</p>
      <LoadView q={props} isEmpty={(d) => (d.proposals || []).length === 0} emptyText="No alias proposals.">
        {(d) => <Table rows={d.proposals} cols={[['Phrase', (p) => p.surface], ['Skill', (p) => p.skill_id || p.new_skill], ['By', (p) => p.proposed_by],
          ['', (p) => <span className="flex gap-2"><button className={btn()} disabled={act.busy} onClick={() => review(p, true)}>Approve</button><button className={btn('ghost')} disabled={act.busy} onClick={() => review(p, false)}>Reject</button></span>]]} />}
      </LoadView>
    </Card>
  );
};

const Resume = () => {
  const [evid, setEvid] = useState('');
  const [req, setReq] = useState('');
  const [shown, setShown] = useState(null);
  const act = useAct();
  const parse = (v) => act.run(async () => { const out = await hr('RESUME_EVIDENCE', 'parse_resume', v); if (out.result?.evidence_id) setEvid(out.result.evidence_id); return out; },
    { title: 'Parse this résumé?', message: 'The text is parsed into facts with source quotes and stored for this candidate. Unknown skill phrases are queued for review, never guessed.' });
  return (
    <div className="space-y-4">
      <ScreenLink to="hiring-admin">The bias audit for a requisition is under Hiring intake admin.</ScreenLink>
      <Card title="Parse a résumé">
        <SpecForm submitLabel="Parse" busy={act.busy} onSubmit={parse} fields={[
          { name: 'candidate_id', label: 'Candidate id', type: 'text', required: true },
          { name: 'filename', label: 'File name', type: 'text', placeholder: 'resume.txt' },
          { name: 'text', label: 'Résumé text', type: 'textarea', required: true }]} />
        {act.view}
      </Card>
      <Card title="Evidence against a requisition">
        <div className="flex flex-wrap gap-2 items-center">
          <input className={`${inputClass} max-w-xs`} placeholder="Evidence id" aria-label="Evidence id" value={evid} onChange={(e) => setEvid(e.target.value)} />
          <ReqSelect value={req} onChange={setReq} />
          <button className={btn()} disabled={!evid || !req} onClick={() => setShown({ evid, req })}>Show evidence</button>
        </div>
        {shown && <Match key={`${shown.evid}-${shown.req}`} evidence={shown.evid} req={shown.req} />}
      </Card>
      <Unknown />
    </div>
  );
};

export default Resume;
