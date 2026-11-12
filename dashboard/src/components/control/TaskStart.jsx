import React, { useState } from 'react';
import { vc, vError } from '../velaris/velarisApi';
import { Card, SpecForm } from '../velaris/shared';
import { confirmAction } from '../confirmAction';
import { Pill } from '../prime/parts';

// Start-run form generated from the task's parameter schema when Velaris publishes one (task.params_schema /
// schema / params: JSON-schema-like {properties: {name: {type, enum, description}}, required: []}). This Velaris
// version lists no schema, so a task without one gets a JSON parameter editor instead.
const schemaOf = (t) => t.params_schema || t.schema || t.params || null;

const fieldsFrom = (schema) => Object.entries(schema.properties || {}).map(([name, p]) => ({
  name, label: p.title || name, required: (schema.required || []).includes(name), help: p.description,
  type: p.enum ? 'select' : p.type === 'integer' || p.type === 'number' ? 'number' : p.type === 'boolean' ? 'checkbox' : p.type === 'array' ? 'list' : 'text',
  options: p.enum,
}));

const TaskCard = ({ t, onStarted }) => {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const schema = schemaOf(t);
  const fields = schema?.properties ? fieldsFrom(schema) : [{ name: 'params', label: 'Parameters (JSON object)', type: 'json', placeholder: '{}' }];
  const start = async (values) => {
    const params = schema?.properties ? values : (values.params ?? {});
    if (!(await confirmAction(`Start "${t.title}"? ${t.approval_steps?.length ? `Steps that need approval: ${t.approval_steps.join(', ')}.` : 'It has no steps that need approval.'} It acts on the ${t.surface}.`, 'Start run'))) return;
    setBusy(true); setErr('');
    try {
      const r = await vc.post('/control/runs', { task_id: t.id, params });
      onStarted(r.data.task_id);
    } catch (e) { setErr(vError(e)); } finally { setBusy(false); }
  };
  return (
    <Card title={t.title} actions={<Pill className="bg-surface text-muted">{t.surface}</Pill>}>
      <p className="text-xs text-muted">{t.description}</p>
      <p className="text-[11px] text-muted">Actions: {(t.actions || []).join(', ')} · approval needed: {(t.approval_steps || []).join(', ') || 'none'} · up to {t.max_steps} steps</p>
      {open ? (
        <>
          <SpecForm fields={fields} submitLabel="Start run" onSubmit={start} busy={busy} />
          {err && <p role="alert" className="text-xs text-danger">{err}</p>}
        </>
      ) : <button className="text-xs font-bold text-accent" onClick={() => setOpen(true)}>Set up a run</button>}
    </Card>
  );
};

const TaskStart = ({ tasks, onStarted }) => (
  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
    {tasks.map((t) => <TaskCard key={t.id} t={t} onStarted={onStarted} />)}
  </div>
);

export default TaskStart;
