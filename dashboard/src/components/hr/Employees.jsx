import React, { useState } from 'react';
import { hr, useHr, when, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table, SpecForm } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { StateBadge, Detail } from './hrParts';
import { inputClass } from '../prime/parts';

const Exit = ({ id }) => {
  const q = useHr('EMPLOYEE_RECORDS', 'exit_status', { exit_id: id });
  const act = useAct();
  const doit = (method, args, title, message) => act.run(async () => { const out = await hr('EMPLOYEE_RECORDS', method, { exit_id: id, ...args }); q.reload(); return out; }, { title, message });
  return (
    <Card title={`Exit ${id.slice(0, 10)}`}>
      <LoadView q={q}>{(d) => (
        <div className="space-y-3">
          <Detail data={d.exit || d} />
          {((d.exit || d).tasks || []).filter((t) => t.state !== 'done').map((t) => (
            <button key={t.key} className={`${btn('ghost')} mr-2`} disabled={act.busy} onClick={() => doit('complete_exit_task', { task_key: t.key }, 'Mark this exit task done?', `Record "${t.title || t.key}" as done. Access is not revoked by Velaris; a person does the task.`)}>Done: {t.title || t.key}</button>
          ))}
          <button className={btn('danger')} disabled={act.busy} onClick={() => doit('finalise_exit', {}, 'Finalise this exit?', 'The employee is marked as exited and retention starts. This cannot be undone.')}>Finalise exit</button>
          {act.view}
        </div>
      )}</LoadView>
    </Card>
  );
};

const Employee = ({ id }) => {
  const q = useHr('EMPLOYEE_RECORDS', 'get_employee', { employee_id: id });
  const [hist, setHist] = useState(false);
  return (
    <Card title={`Employee ${id}`} actions={<button className={btn('ghost')} onClick={() => setHist(!hist)}>{hist ? 'Hide history' : 'History'}</button>}>
      <LoadView q={q}>{(d) => <Detail data={d.employee || d} />}</LoadView>
      {hist && <History id={id} />}
    </Card>
  );
};

const History = ({ id }) => {
  const q = useHr('EMPLOYEE_RECORDS', 'employee_history', { employee_id: id });
  return <LoadView q={q} isEmpty={(d) => (d.history || []).length === 0} emptyText="No changes recorded.">{(d) => <Table rows={d.history} cols={[['When', (h) => when(h.at)], ['By', (h) => h.by], ['Field', (h) => h.field], ['Change', (h) => `${h.old ?? ''} → ${h.new ?? ''}`], ['Reason', (h) => h.reason]]} />}</LoadView>;
};

const Employees = () => {
  const [status, setStatus] = useState('');
  const q = useHr('EMPLOYEE_RECORDS', 'list_employees', status ? { status } : {});
  const [open, setOpen] = useState(null);
  const [exit, setExit] = useState('');
  const act = useAct();
  const startExit = (v) => act.run(async () => { const out = await hr('EMPLOYEE_RECORDS', 'start_exit', v); const id = out.result?.exit?.id || out.result?.exit_id; if (id) setExit(id); q.reload(); return out; },
    { title: 'Start this exit?', message: `${v.employee_id} goes on notice and an exit checklist is produced (one access-revocation task per system).` });
  const convert = (v) => act.run(async () => hr('EMPLOYEE_RECORDS', 'propose_conversion', v),
    { title: 'Propose conversion to employee?', message: 'A different HR administrator must approve before the candidate becomes an employee.' });
  return (
    <div className="space-y-4">
      <Card title="Employees" actions={<select className={`${inputClass} w-32`} aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option><option>active</option><option>on_notice</option><option>exited</option></select>}>
        <LoadView q={q} isEmpty={(d) => (d.employees || []).length === 0} emptyText="No employee records.">
          {(d) => <Table rows={d.employees} onRow={(e) => setOpen(e.id)} cols={[['Name', (e) => e.name], ['Department', (e) => e.department], ['Designation', (e) => e.designation], ['Joined', (e) => e.join_date], ['Status', (e) => <StateBadge state={e.status} />]]} />}
        </LoadView>
      </Card>
      {open && <Employee key={open} id={open} />}
      {exit && <Exit key={exit} id={exit} />}
      <Card title="Start an exit">
        <SpecForm submitLabel="Start exit" busy={act.busy} onSubmit={startExit} fields={[
          { name: 'employee_id', label: 'Employee id', type: 'text', required: true }, { name: 'last_working_day', label: 'Last working day', type: 'date', required: true },
          { name: 'reason_code', label: 'Reason code', type: 'text', required: true }, { name: 'systems', label: 'Systems to revoke', type: 'list' }]} />
        <div className="flex gap-2 items-center"><input className={`${inputClass} max-w-xs`} placeholder="Open an exit by id" aria-label="Exit id" value={exit} onChange={(e) => setExit(e.target.value)} /></div>
      </Card>
      <Card title="Convert a candidate to an employee (proposal)">
        <SpecForm submitLabel="Propose" busy={act.busy} onSubmit={convert} fields={[
          { name: 'application_id', label: 'Application id', type: 'text', required: true }, { name: 'department', label: 'Department', type: 'text', required: true }, { name: 'designation', label: 'Designation', type: 'text', required: true },
          { name: 'manager_id', label: 'Manager (user id)', type: 'text', required: true }, { name: 'join_date', label: 'Join date', type: 'date', required: true }, { name: 'offer_id', label: 'Offer id', type: 'text' }]} />
      </Card>
      {act.view}
    </div>
  );
};

export default Employees;
