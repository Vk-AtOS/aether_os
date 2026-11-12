import React, { useState } from 'react';
import { hr, useHr, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table, SpecForm } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { StateBadge, Detail } from './hrParts';

const FIELDS = [
  { name: 'title', label: 'Title', type: 'text', required: true },
  { name: 'department', label: 'Department', type: 'text' },
  { name: 'openings', label: 'Openings', type: 'number' },
  { name: 'employment_type', label: 'Employment type', type: 'select', options: ['FULL_TIME', 'PART_TIME', 'CONTRACTOR', 'TEMPORARY', 'INTERN'] },
  { name: 'city', label: 'City', type: 'text', required: true },
  { name: 'state', label: 'State', type: 'text' },
  { name: 'requirements', label: 'Requirements (JSON)', type: 'json', required: true, placeholder: '{"must":[{"skill":"python","min_years":2}],"nice":[],"min_total_years":3}' },
  { name: 'description', label: 'Description', type: 'textarea' },
];

const Requisitions = () => {
  const q = useHr('ATS_CORE', 'list_requisitions');
  const act = useAct();
  const [open, setOpen] = useState(null);
  const detail = useHr('ATS_CORE', 'get_requisition', { requisition_id: open || '' });

  const move = (r, method, verb) => act.run(async () => { const out = await hr('ATS_CORE', method, { requisition_id: r.id, ...(method === 'approve_requisition' ? { note: '' } : {}) }); q.reload(); return out; },
    { title: `${verb} requisition?`, message: `${verb} "${r.title}". ${method === 'approve_requisition' ? 'Approval must come from someone other than its creator.' : 'It is recorded in the decision trail.'}` });
  const create = (v) => act.run(async () => {
    const { city, state, ...rest } = v;
    const out = await hr('ATS_CORE', 'create_requisition', { ...rest, location: { city, ...(state ? { state } : {}) } });
    q.reload();
    return out;
  }, { title: 'Create requisition?', message: `Draft "${v.title}". It must be approved by someone else before it can open.` });

  const next = { draft: ['approve_requisition', 'Approve'], approved: ['open_requisition', 'Open'], open: ['close_requisition', 'Close'] };
  return (
    <div className="space-y-4">
      {act.view}
      <Card title="Requisitions">
        <LoadView q={q} isEmpty={(d) => (d.requisitions || []).length === 0} emptyText="No requisitions yet. Draft one below.">
          {(d) => (
            <Table rows={d.requisitions} onRow={(r) => setOpen(r.id)} cols={[
              ['Title', (r) => r.title], ['State', (r) => <StateBadge state={r.state} />], ['Openings', (r) => r.openings], ['City', (r) => r.location?.city],
              ['', (r) => next[r.state] && <button className={btn('ghost')} disabled={act.busy} onClick={(e) => { e.stopPropagation(); move(r, ...next[r.state]); }}>{next[r.state][1]}</button>],
            ]} />
          )}
        </LoadView>
      </Card>
      {open && <Card title="Requisition detail"><LoadView q={detail}>{(d) => <Detail data={d.requisition} />}</LoadView></Card>}
      <Card title="Draft a requisition"><SpecForm fields={FIELDS} submitLabel="Create draft" onSubmit={create} busy={act.busy} /></Card>
    </div>
  );
};

export default Requisitions;
