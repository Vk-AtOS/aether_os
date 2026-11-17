import React, { useState } from 'react';
import { hr, useHr, when, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table, SpecForm, Tabs } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { StateBadge, Detail } from './hrParts';

const Availability = () => {
  const q = useHr('INTERVIEW_SCHEDULER', 'list_interviewers');
  const act = useAct();
  const save = (v) => act.run(async () => { const out = await hr('INTERVIEW_SCHEDULER', 'set_availability', v); q.reload(); return out; },
    { title: 'Save availability?', message: `Weekly hours for ${v.name} (India time) are used when proposing slots.` });
  return (
    <div className="space-y-4">
      <Card title="Interviewers">
        <LoadView q={q} isEmpty={(d) => (d.interviewers || []).length === 0} emptyText="No interviewers have set availability.">
          {(d) => <Table rows={d.interviewers} cols={[['Name', (i) => i.name], ['Id', (i) => i.id], ['Buffer', (i) => `${i.buffer_min} min`], ['Max/day', (i) => i.max_per_day], ['Weekly', (i) => JSON.stringify(i.weekly)]]} />}
        </LoadView>
      </Card>
      <Card title="Set availability">
        <SpecForm submitLabel="Save" busy={act.busy} onSubmit={save} fields={[
          { name: 'interviewer_id', label: 'Interviewer id', type: 'text', required: true }, { name: 'name', label: 'Name', type: 'text', required: true },
          { name: 'email', label: 'Email (for the invitation)', type: 'text', required: true }, { name: 'buffer_min', label: 'Buffer (min)', type: 'number' }, { name: 'max_per_day', label: 'Max per day', type: 'number' },
          { name: 'weekly', label: 'Weekly hours (JSON)', type: 'json', required: true, placeholder: '{"mon":[["10:00","17:00"]],"tue":[["10:00","13:00"]]}' }]} />
        {act.view}
      </Card>
    </div>
  );
};

const Slots = () => {
  const [slots, setSlots] = useState(null);
  const [pick, setPick] = useState(null);
  const [panel, setPanel] = useState([]);
  const [dur, setDur] = useState(45);
  const act = useAct();
  const propose = (v) => act.run(async () => { const out = await hr('INTERVIEW_SCHEDULER', 'propose_slots', { ...v, duration_min: v.duration_min || 45 }); setSlots(out.result.slots || []); setPanel(v.interviewer_ids); setDur(v.duration_min || 45); return out; });
  const book = (v) => act.run(async () => hr('INTERVIEW_SCHEDULER', 'book_interview', { ...v, interviewer_ids: panel, start: new Date(pick.start * 1000).toISOString(), duration_min: dur }),
    { title: 'Book this interview?', message: `${pick.start_ist} for ${dur} minutes. The slot is re-checked against every current booking and an invitation is drafted (not sent).` });
  return (
    <div className="space-y-4">
      <Card title="Find slots where everyone is free">
        <SpecForm submitLabel="Propose slots" busy={act.busy} onSubmit={propose} fields={[
          { name: 'interviewer_ids', label: 'Interviewer ids', type: 'list', required: true, help: 'Comma separated' }, { name: 'duration_min', label: 'Duration (min)', type: 'number' },
          { name: 'from_date', label: 'From', type: 'date', required: true }, { name: 'to_date', label: 'To', type: 'date', required: true }]} />
        {act.view}
        {slots && (slots.length === 0 ? <p className="text-xs text-muted">No common free slots in that range.</p> : (
          <div className="flex flex-wrap gap-2">{slots.slice(0, 40).map((s) => (
            <button key={s.start} className={`${btn(pick?.start === s.start ? 'primary' : 'ghost')}`} onClick={() => setPick(s)}>{s.start_ist}</button>))}</div>
        ))}
      </Card>
      {pick && (
        <Card title={`Book ${pick.start_ist}`}>
          <SpecForm submitLabel="Book" busy={act.busy} onSubmit={book} fields={[
            { name: 'application_id', label: 'Application id', type: 'text', required: true }, { name: 'title', label: 'Title', type: 'text', required: true }, { name: 'location', label: 'Location / link', type: 'text' }]} />
        </Card>
      )}
    </div>
  );
};

const Bookings = () => {
  const q = useHr('INTERVIEW_SCHEDULER', 'list_bookings', { upcoming_only: false });
  const act = useAct();
  const doit = (b, method, title, message) => act.run(async () => { const out = await hr('INTERVIEW_SCHEDULER', method, { booking_id: b.id }); q.reload(); return out; }, { title, message });
  return (
    <Card title="Bookings">
      {act.view}
      <LoadView q={q} isEmpty={(d) => (d.bookings || []).length === 0} emptyText="No interviews are booked.">
        {(d) => <Table rows={d.bookings} cols={[['When', (b) => when(b.start)], ['Title', (b) => b.title], ['Application', (b) => b.application_id], ['Status', (b) => <StateBadge state={b.status || 'booked'} />],
          ['', (b) => <span className="flex gap-2"><button className={btn('ghost')} disabled={act.busy} onClick={() => doit(b, 'complete_interview', 'Mark as held?', 'Record that this interview took place.')}>Held</button>
            <button className={btn('danger')} disabled={act.busy} onClick={() => doit(b, 'cancel_interview', 'Cancel this interview?', 'The booking is cancelled and a cancellation notice is drafted.')}>Cancel</button></span>]]} />}
      </LoadView>
    </Card>
  );
};

const Drafts = () => {
  const q = useHr('INTERVIEW_SCHEDULER', 'list_drafts', { status: 'draft' });
  const act = useAct();
  const [preview, setPreview] = useState(null);
  const approve = (x) => act.run(async () => { const out = await hr('INTERVIEW_SCHEDULER', 'approve_draft', { draft_id: x.id }); q.reload(); return out; },
    { title: 'Approve this message?', message: 'Approving marks the draft ready to send. Velaris does not send it by itself.' });
  const render = (x) => act.run(async () => { const out = await hr('INTERVIEW_SCHEDULER', 'render_invitation', { draft_id: x.id, candidate_name: 'Candidate', candidate_email: 'candidate@example.com' }); setPreview(out.result); return out; });
  return (
    <Card title="Draft inbox (invitations and notices)">
      {act.view}
      <LoadView q={q} isEmpty={(d) => (d.drafts || []).length === 0} emptyText="No drafts are waiting.">
        {(d) => d.drafts.map((x) => (
          <div key={x.id} className="border border-border rounded-lg p-3 space-y-2">
            <p className="text-sm text-bright font-semibold">{x.subject}</p>
            <pre className="whitespace-pre-wrap text-xs text-bright bg-surface rounded p-2 max-h-40 overflow-auto">{x.body}</pre>
            <div className="flex gap-2"><button className={btn()} disabled={act.busy} onClick={() => approve(x)}>Approve</button><button className={btn('ghost')} disabled={act.busy} onClick={() => render(x)}>Preview</button></div>
          </div>
        ))}
      </LoadView>
      {preview && <><p className="text-[11px] text-warning">Preview only: the name and address below are placeholders, not the real candidate.</p><Detail data={{ subject: preview.subject, body: preview.body }} /></>}
    </Card>
  );
};

const Interviews = () => {
  const [tab, setTab] = useState('bookings');
  return (
    <div className="space-y-4">
      <Tabs tabs={[['bookings', 'Bookings'], ['slots', 'Find slots'], ['availability', 'Availability'], ['drafts', 'Draft inbox']]} value={tab} onChange={setTab} />
      {tab === 'bookings' && <Bookings />}{tab === 'slots' && <Slots />}{tab === 'availability' && <Availability />}{tab === 'drafts' && <Drafts />}
    </div>
  );
};

export default Interviews;
