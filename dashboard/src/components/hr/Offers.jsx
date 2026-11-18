import React, { useState } from 'react';
import { hr, useHr, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table, SpecForm, Notice, Tabs } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { StateBadge, Detail } from './hrParts';
import { inputClass } from '../prime/parts';

const Render = ({ id }) => {
  const [fmt, setFmt] = useState('html');
  const q = useHr('OFFER_LETTERS', 'render_offer', { offer_id: id, fmt });
  return (
    <div className="space-y-2">
      <select className={`${inputClass} w-32`} aria-label="Format" value={fmt} onChange={(e) => setFmt(e.target.value)}><option>html</option><option>text</option></select>
      <LoadView q={q}>
        {(d) => (fmt === 'html'
          ? <iframe title="Offer letter" sandbox="" srcDoc={d.content} className="w-full h-96 bg-white rounded border border-border" />
          : <pre className="whitespace-pre-wrap text-xs text-bright bg-surface rounded p-3 max-h-96 overflow-auto">{d.content}</pre>)}
      </LoadView>
    </div>
  );
};

const Offer = ({ id, done }) => {
  const q = useHr('OFFER_LETTERS', 'get_offer', { offer_id: id });
  const act = useAct();
  const [ack, setAck] = useState(false);
  const [note, setNote] = useState('');
  const [show, setShow] = useState(false);
  const [evidence, setEvidence] = useState('');
  const doit = (method, args, title, message) => act.run(async () => { const out = await hr('OFFER_LETTERS', method, { offer_id: id, ...args }); done(); q.reload(); return out; }, { title, message });
  return (
    <Card title={`Offer ${id.slice(0, 10)}`}>
      <LoadView q={q}>
        {(d) => {
          const o = d.offer;
          const review = o.comp?.status === 'needs_review';
          return (
            <div className="space-y-3">
              <StateBadge state={o.status} />
              {review && <Notice tone="warn">This offer needs review before approval: {(o.comp.review_reasons || o.comp.reasons || o.comp.flags || ['the compensation breakdown could not be fully checked']).join('; ')}</Notice>}
              <Detail data={{ candidate: o.candidate, terms: o.terms, compensation: o.comp, approvers: o.approvers, approvals: o.approvals }} />
              <input className={inputClass} placeholder="Note" aria-label="Decision note" value={note} onChange={(e) => setNote(e.target.value)} />
              {review && <label className="flex gap-2 text-xs text-bright"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />I have read the review reasons and acknowledge them</label>}
              <div className="flex flex-wrap gap-2">
                {['draft', 'rejected'].includes(o.status) && <button className={btn()} disabled={act.busy} onClick={() => doit('submit_for_approval', {}, 'Submit for approval?', 'The first approver is asked to decide. You cannot approve your own offer.')}>Submit for approval</button>}
                {o.status === 'pending_approval' && <>
                  <button className={btn()} disabled={act.busy || (review && !ack)} onClick={() => doit('approve', { note, acknowledge_review: ack }, 'Approve this offer?', 'Only the named approver for the current step can approve. It is recorded under your name.')}>Approve</button>
                  <button className={btn('danger')} disabled={act.busy || !note} onClick={() => doit('reject', { note }, 'Reject this offer?', 'A note is required. The drafter will see it.')}>Reject</button></>}
                {o.status === 'approved' && <button className={btn()} disabled={act.busy} onClick={() => doit('send_offer', { delivered_manually: true }, 'Mark the offer as sent?', 'Records that the approved letter was delivered to the candidate by you.')}>Mark sent</button>}
                {o.status === 'sent' && <>
                  <input className={`${inputClass} max-w-[14rem]`} placeholder="E-sign request id (optional)" aria-label="E-sign request id" value={evidence} onChange={(e) => setEvidence(e.target.value)} />
                  <button className={btn()} disabled={act.busy} onClick={() => doit('record_response', { response: 'accept', evidence_ref: evidence, note }, 'Record that the candidate accepted?', 'Records the acceptance under your name. With an e-sign request id Velaris checks it is sealed and made for this offer; without one it is recorded as entered by HR.')}>Candidate accepted</button>
                  <button className={btn('danger')} disabled={act.busy} onClick={() => doit('record_response', { response: 'decline', evidence_ref: evidence, note }, 'Record that the candidate declined?', 'Records the decline under your name. It cannot be undone.')}>Candidate declined</button></>}
                {['approved', 'sent'].includes(o.status) && <button className={btn('danger')} disabled={act.busy || !note} onClick={() => doit('withdraw_offer', { reason: note }, 'Withdraw this offer?', 'A reason (the note) is required.')}>Withdraw</button>}
                <button className={btn('ghost')} onClick={() => setShow(!show)}>{show ? 'Hide letter' : 'Render letter'}</button>
              </div>
              {act.view}
              {show && <Render id={id} />}
            </div>
          );
        }}
      </LoadView>
    </Card>
  );
};

const Offers = () => {
  const [tab, setTab] = useState('all');
  const [open, setOpen] = useState(null);
  const q = useHr('OFFER_LETTERS', 'list_offers', tab === 'inbox' ? { status: 'pending_approval' } : {});
  const act = useAct();
  const templates = useHr('OFFER_LETTERS', 'list_templates');     // the picker (KAN-139): built-in and this organisation's own
  const templateIds = (templates.data?.templates || []).map((t) => (typeof t === 'string' ? t : t.id || t.name)).filter(Boolean);
  const create = (v) => act.run(async () => { const out = await hr('OFFER_LETTERS', 'create_offer', v); q.reload(); return out; },
    { title: 'Draft this offer?', message: `A draft for ${v.candidate_name} is created. It needs two different approvers and you cannot approve it yourself.` });
  return (
    <div className="space-y-4">
      <Tabs tabs={[['all', 'All offers'], ['inbox', 'Approval inbox']]} value={tab} onChange={setTab} />
      <LoadView q={q} isEmpty={(d) => (d.offers || []).length === 0} emptyText={tab === 'inbox' ? 'No offers are waiting for approval.' : 'No offers yet.'}>
        {(d) => <Table rows={d.offers} onRow={(o) => setOpen(o.id)} cols={[['Candidate', (o) => o.candidate_name], ['Role', (o) => o.role_title], ['Joins', (o) => o.join_date], ['Status', (o) => <StateBadge state={o.status} />],
          ['Review', (o) => o.needs_review && <span className="text-warning text-[10px] font-bold">NEEDS REVIEW</span>]]} />}
      </LoadView>
      {open && <Offer key={open} id={open} done={q.reload} />}
      <Card title="Draft an offer">
        <SpecForm submitLabel="Create draft" busy={act.busy} onSubmit={create} fields={[
          { name: 'candidate_name', label: 'Candidate name', type: 'text', required: true }, { name: 'candidate_email', label: 'Candidate email', type: 'text', required: true },
          { name: 'role_title', label: 'Role title', type: 'text', required: true }, { name: 'department', label: 'Department', type: 'text', required: true }, { name: 'location', label: 'Location', type: 'text', required: true },
          { name: 'join_date', label: 'Join date', type: 'date', required: true }, { name: 'annual_ctc', label: 'Annual CTC', type: 'number', required: true },
          { name: 'hiring_manager_id', label: 'Hiring manager (user id)', type: 'text', required: true }, { name: 'hr_approver_id', label: 'HR approver (user id)', type: 'text', required: true },
          { name: 'application_id', label: 'Application id', type: 'text' },
          ...(templateIds.length ? [{ name: 'template_id', label: 'Template', type: 'select', options: templateIds }] : [])]} />
        {act.view}
      </Card>
    </div>
  );
};

export default Offers;
