import React, { useState } from 'react';
import { hr, useHr, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table, SpecForm } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { Detail } from './hrParts';

const Report = ({ policyKey }) => {
  const q = useHr('POLICY_ACKS', 'compliance_report', policyKey ? { policy_key: policyKey } : {});
  return <LoadView q={q} isEmpty={(d) => !d.report || (Array.isArray(d.report) ? d.report.length === 0 : Object.keys(d.report).length === 0)} emptyText="No acknowledgement data yet.">{(d) => <Detail data={d.report} />}</LoadView>;
};

const Policies = () => {
  const q = useHr('POLICY_ACKS', 'list_policies');
  const [key, setKey] = useState('');
  const act = useAct();
  const publish = (v) => act.run(async () => { const out = await hr('POLICY_ACKS', 'publish_policy', v); q.reload(); return out; },
    { title: 'Publish this policy?', message: 'This becomes the current version and supersedes the previous one. The audience is asked to acknowledge it.' });
  const retire = (p) => act.run(async () => { const out = await hr('POLICY_ACKS', 'retire_policy', { policy_key: p.key, reason: 'Retired from the dashboard' }); q.reload(); return out; },
    { title: 'Retire this policy?', message: `"${p.title}" is no longer current and stops asking for acknowledgements.` });
  return (
    <div className="space-y-4">
      {act.view}
      <Card title="Policies">
        <LoadView q={q} isEmpty={(d) => (d.policies || []).length === 0} emptyText="No policies are published.">
          {(d) => <Table rows={d.policies} onRow={(p) => setKey(p.key)} cols={[['Policy', (p) => p.title], ['Key', (p) => p.key], ['Version', (p) => p.version], ['Effective', (p) => p.effective_date], ['Due', (p) => `${p.due_days} days`],
            ['', (p) => <button className={btn('danger')} disabled={act.busy} onClick={(e) => { e.stopPropagation(); retire(p); }}>Retire</button>]]} />}
        </LoadView>
      </Card>
      <Card title={key ? `Acknowledgements: ${key}` : 'Acknowledgements'}><Report key={key} policyKey={key} /></Card>
      <Card title="Publish a policy">
        <SpecForm submitLabel="Publish" busy={act.busy} onSubmit={publish} fields={[
          { name: 'policy_key', label: 'Key', type: 'text', required: true }, { name: 'title', label: 'Title', type: 'text', required: true }, { name: 'effective_date', label: 'Effective date', type: 'date', required: true },
          { name: 'due_days', label: 'Acknowledge within (days)', type: 'number' }, { name: 'departments', label: 'Departments (blank = everyone)', type: 'list' }, { name: 'text', label: 'Policy text', type: 'textarea', required: true }]} />
      </Card>
    </div>
  );
};

export default Policies;
