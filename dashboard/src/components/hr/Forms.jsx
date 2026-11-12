import React, { useState } from 'react';
import { hr, useHr, when, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { ReqSelect, Detail, StateBadge } from './hrParts';
import { inputClass, labelClass } from '../prime/parts';

const TYPES = ['text', 'longtext', 'email', 'phone', 'number', 'choice', 'url', 'checkbox', 'file'];
const blankField = () => ({ name: '', label: '', type: 'text', required: false, choices: '' });

// Builder: rows of fields + consent text. Velaris validates the definition (needs a name field and email or phone).
const Builder = ({ onCreated }) => {
  const [req, setReq] = useState('');
  const [title, setTitle] = useState('Job application');
  const [fields, setFields] = useState([{ name: 'name', label: 'Full name', type: 'text', required: true, choices: '' }, { name: 'email', label: 'Email', type: 'text', required: true, choices: '' }]);
  const [consent, setConsent] = useState('');
  const [days, setDays] = useState(180);
  const act = useAct();
  const set = (i, patch) => setFields(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  const create = () => act.run(async () => {
    const definition = { title, consent_text: consent, retention_days: Number(days),
      fields: fields.map((f) => ({ name: f.name, label: f.label || f.name, type: f.type, required: f.required, ...(f.type === 'choice' ? { choices: f.choices.split(',').map((c) => c.trim()).filter(Boolean) } : {}) })) };
    const out = await hr('SCREENING_FORMS', 'create_form', { requisition_id: req, definition });
    onCreated();
    return out;
  }, { title: 'Create this intake form?', message: 'The form is created as a draft. Publishing it is a separate step and makes a public application page available.' });
  return (
    <Card title="Intake form builder">
      <ReqSelect value={req} onChange={setReq} />
      <label><span className={labelClass}>Form title</span><input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Form title" /></label>
      {fields.map((f, i) => (
        <div key={i} className="grid grid-cols-2 sm:grid-cols-5 gap-2 items-end">
          <input className={inputClass} placeholder="name" aria-label={`Field ${i + 1} name`} value={f.name} onChange={(e) => set(i, { name: e.target.value })} />
          <input className={inputClass} placeholder="label" aria-label={`Field ${i + 1} label`} value={f.label} onChange={(e) => set(i, { label: e.target.value })} />
          <select className={inputClass} aria-label={`Field ${i + 1} type`} value={f.type} onChange={(e) => set(i, { type: e.target.value })}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select>
          {f.type === 'choice' ? <input className={inputClass} placeholder="a, b, c" aria-label={`Field ${i + 1} choices`} value={f.choices} onChange={(e) => set(i, { choices: e.target.value })} /> : <label className="text-xs text-muted"><input type="checkbox" checked={f.required} onChange={(e) => set(i, { required: e.target.checked })} /> required</label>}
          <button className={btn('ghost')} onClick={() => setFields(fields.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <button className={btn('ghost')} onClick={() => setFields([...fields, blankField()])}>Add field</button>
      <label><span className={labelClass}>Consent text (what is collected, why, how long, how to withdraw; at least 40 characters)</span><textarea rows={3} className={inputClass} value={consent} onChange={(e) => setConsent(e.target.value)} aria-label="Consent text" /></label>
      <label><span className={labelClass}>Retention (days, up to 730)</span><input type="number" className={inputClass} value={days} onChange={(e) => setDays(e.target.value)} aria-label="Retention days" /></label>
      <button className={btn()} disabled={!req || act.busy} onClick={create}>Create form</button>
      {act.view}
    </Card>
  );
};

const Submissions = () => {
  const q = useHr('SCREENING_FORMS', 'pending_submissions');
  const act = useAct();
  const [open, setOpen] = useState(null);
  const detail = useHr('SCREENING_FORMS', 'get_submission', { submission_id: open || '' });
  const decide = (s, method, title, message) => act.run(async () => { const out = await hr('SCREENING_FORMS', method, { submission_id: s.id }); q.reload(); return out; }, { title, message });
  return (
    <Card title="Pending submissions">
      {act.view}
      <LoadView q={q} isEmpty={(d) => (d.submissions || []).length === 0} emptyText="No submissions are waiting for review.">
        {(d) => <Table rows={d.submissions} onRow={(s) => setOpen(s.id)} cols={[['Received', (s) => s.received_at && when(Date.parse(s.received_at) / 1000)], ['Form', (s) => s.form_id], ['Requisition', (s) => s.requisition_id],
          ['', (s) => <span className="flex gap-2">
            <button className={btn()} disabled={act.busy} onClick={(e) => { e.stopPropagation(); decide(s, 'accept_submission', 'Accept this submission?', 'The candidate is added to the pipeline. Possible duplicates go to review, nothing merges.'); }}>Accept</button>
            <button className={btn('danger')} disabled={act.busy} onClick={(e) => { e.stopPropagation(); decide(s, 'discard_submission', 'Discard this submission?', 'The submission and its file are deleted.'); }}>Discard</button></span>]]} />}
      </LoadView>
      {open && <LoadView q={detail}>{(d) => <Detail data={d.submission} />}</LoadView>}
    </Card>
  );
};

const Forms = () => {
  const q = useHr('SCREENING_FORMS', 'list_forms');
  const act = useAct();
  const toggle = (f) => act.run(async () => { const out = await hr('SCREENING_FORMS', f.status === 'published' ? 'unpublish_form' : 'publish_form', { form_id: f.id }); q.reload(); return out; },
    { title: f.status === 'published' ? 'Unpublish this form?' : 'Publish this form?', message: f.status === 'published' ? 'Candidates can no longer apply through it.' : 'A public application page becomes available to candidates, with the consent text you wrote.' });
  return (
    <div className="space-y-4">
      <Card title="Forms">
        {act.view}
        <LoadView q={q} isEmpty={(d) => (d.forms || []).length === 0} emptyText="No forms yet.">
          {(d) => <Table rows={d.forms} cols={[['Title', (f) => f.title], ['Status', (f) => <StateBadge state={f.status} />], ['Requisition', (f) => f.requisition_id],
            ['', (f) => <button className={btn('ghost')} disabled={act.busy} onClick={() => toggle(f)}>{f.status === 'published' ? 'Unpublish' : 'Publish'}</button>]]} />}
        </LoadView>
      </Card>
      <Builder onCreated={q.reload} />
      <Submissions />
    </div>
  );
};

export default Forms;
