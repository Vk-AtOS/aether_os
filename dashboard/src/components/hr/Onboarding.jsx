import React, { useState } from 'react';
import { hr, useHr, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table, SpecForm, Notice } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { StateBadge, Masked } from './hrParts';
import { confirmAction } from '../confirmAction';

// Identifiers arrive masked from Velaris. "Reveal" asks Velaris for the clear value (it checks access) after a confirmation.
const Identifiers = ({ id }) => {
  const [reveal, setReveal] = useState(false);
  const q = useHr('ONBOARDING_FLOW', 'get_identifiers', { case_id: id, reveal });
  const ask = async () => { if (await confirmAction('Reveal the clear PAN and bank account of this joiner? The access is recorded under your name.', 'Reveal identifiers')) setReveal(true); };
  return (
    <Card title="Identifiers" actions={!reveal && <button className={btn('ghost')} onClick={ask}>Reveal</button>}>
      <LoadView q={q} isEmpty={(d) => Object.keys(d.identifiers || {}).length === 0} emptyText="No identifiers were submitted.">
        {(d) => Object.entries(d.identifiers).map(([k, v]) => (
          <p key={k} className="text-xs text-bright">{k.toUpperCase()}: {v.denied ? <span className="text-warning">{v.denied}</span> : reveal && v.value ? <Masked value={v.value} /> : <span className="font-mono">{v.masked}</span>}
            {v.verified && <span className="text-success ml-2">verified</span>}</p>
        ))}
      </LoadView>
    </Card>
  );
};

const Case = ({ id }) => {
  const q = useHr('ONBOARDING_FLOW', 'case_status', { case_id: id });
  const act = useAct();
  const task = (t, method, extra, title, message) => act.run(async () => { const out = await hr('ONBOARDING_FLOW', method, { case_id: id, task_key: t.key, ...extra }); q.reload(); return out; }, { title, message });
  return (
    <div className="space-y-3">
      <LoadView q={q}>
        {(d) => (
          <Card title={`Case ${id.slice(0, 10)}: ${d.completion_percent}% of required tasks done`}>
            <div className="h-1.5 w-full rounded-full bg-border/30 overflow-hidden" aria-hidden="true"><div className="h-full bg-success" style={{ width: `${d.completion_percent}%` }} /></div>
            {(d.overdue || []).length > 0 && <Notice tone="warn">Overdue: {d.overdue.join(', ')}</Notice>}
            {(d.blocked || []).length > 0 && <Notice tone="warn">Blocked: {d.blocked.map((b) => `${b.task} (waiting for ${(b.waiting_for || []).join(', ')})`).join('; ')}</Notice>}
            {act.view}
            <Table rows={d.tasks} cols={[['Task', (t) => t.title || t.key], ['Owner', (t) => t.owner], ['Due', (t) => t.due_date], ['State', (t) => <StateBadge state={t.state} />],
              ['', (t) => !['done', 'waived'].includes(t.state) && (
                <span className="flex gap-2">
                  <button className={btn('ghost')} disabled={act.busy || t.state === 'blocked'} onClick={() => task(t, 'complete_task', {}, 'Mark this task done?', `Record "${t.title || t.key}" as completed by you.`)}>Done</button>
                  <button className={btn('ghost')} disabled={act.busy} onClick={() => task(t, 'waive_task', { reason: 'Waived from the dashboard' }, 'Waive this task?', 'The task no longer counts toward completion. The waiver is recorded.')}>Waive</button></span>)]]} />
          </Card>
        )}
      </LoadView>
      <Identifiers id={id} />
    </div>
  );
};

const Onboarding = () => {
  const q = useHr('ONBOARDING_FLOW', 'list_cases', { status: 'open' });
  const [open, setOpen] = useState(null);
  const act = useAct();
  const start = (v) => act.run(async () => { const out = await hr('ONBOARDING_FLOW', 'start_onboarding', v); q.reload(); return out; },
    { title: 'Start onboarding?', message: `A checklist for ${v.name} is built from the base list plus the role's and location's items, due relative to the join date.` });
  return (
    <div className="space-y-4">
      <Card title="Open onboarding cases">
        <LoadView q={q} isEmpty={(d) => (d.cases || []).length === 0} emptyText="No onboarding cases are open.">
          {(d) => <Table rows={d.cases} onRow={(c) => setOpen(c.id)} cols={[['Joiner', (c) => c.name || c.subject_id], ['Joins', (c) => c.join_date], ['Role group', (c) => c.role_group], ['Status', (c) => <StateBadge state={c.status || 'open'} />]]} />}
        </LoadView>
      </Card>
      {open && <Case key={open} id={open} />}
      <Card title="Start onboarding">
        <SpecForm submitLabel="Start" busy={act.busy} onSubmit={start} fields={[
          { name: 'subject_id', label: 'Employee id', type: 'text', required: true }, { name: 'name', label: 'Name', type: 'text', required: true }, { name: 'email', label: 'Email', type: 'text', required: true },
          { name: 'join_date', label: 'Join date', type: 'date', required: true }, { name: 'role_group', label: 'Role group', type: 'text', required: true }, { name: 'location', label: 'Location', type: 'text', required: true },
          { name: 'manager_id', label: 'Manager (user id)', type: 'text', required: true }, { name: 'offer_id', label: 'Offer id', type: 'text' }]} />
        {act.view}
      </Card>
    </div>
  );
};

export default Onboarding;
