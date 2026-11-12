import React, { useCallback, useState } from 'react';
import { Cpu } from 'lucide-react';
import { vc, useVelaris, btn } from '../components/velaris/velarisApi';
import { LoadView, PageHead, Tabs, Card } from '../components/velaris/shared';
import TaskStart from '../components/control/TaskStart';
import RunView from '../components/control/RunView';

const KEY = 'aether_control_runs';
const recent = () => { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; } };
const remember = (id) => { try { localStorage.setItem(KEY, JSON.stringify([id, ...recent().filter((x) => x !== id)].slice(0, 10))); } catch { /* storage may be blocked; the run still opens */ } };

const Pending = ({ onOpen }) => {
  const f = useCallback(() => vc.get('/control/pending'), []);
  const q = useVelaris(f);
  return (
    <LoadView q={q} isEmpty={(d) => d.runs.length === 0} emptyText="No runs are waiting for a decision.">
      {(d) => (
        <>
          {d.approval === 'prime' && <p className="text-xs text-muted">Steps on this deployment are approved in Prime.</p>}
          {d.runs.map((r) => (
            <Card key={r.task_id} title={r.task}>
              <p className="text-xs text-bright">Waiting: {r.pending?.tool} · call hash {r.pending?.call_hash}</p>
              <button className={btn()} onClick={() => onOpen(r.task_id)}>Open run</button>
            </Card>
          ))}
        </>
      )}
    </LoadView>
  );
};

const Control = () => {
  const [tab, setTab] = useState('tasks');
  const [run, setRun] = useState(null);
  const [ids, setIds] = useState(recent);
  const f = useCallback(() => vc.get('/control/tasks'), []);
  const q = useVelaris(f);
  const open = (id) => { remember(id); setIds(recent()); setRun(id); setTab('run'); };
  return (
    <div className="space-y-4">
      <PageHead icon={Cpu} title="Control" sub="Narrow scripted tasks on files, terminal and browser, with approvals, verification and undo" />
      <Tabs tabs={[['tasks', 'Tasks'], ['run', 'Run'], ['pending', 'Waiting for approval']]} value={tab} onChange={setTab} />
      {tab === 'tasks' && (
        <LoadView q={q} isEmpty={(d) => d.tasks.length === 0} emptyText="Velaris has no control tasks.">
          {(d) => <TaskStart tasks={d.tasks} onStarted={open} />}
        </LoadView>
      )}
      {tab === 'run' && (
        <div className="space-y-3">
          {ids.length > 0 && <div className="flex flex-wrap gap-2 text-xs text-muted">Recent: {ids.map((id) => <button key={id} className={`underline ${id === run ? 'text-bright' : ''}`} onClick={() => setRun(id)}>{id.slice(0, 8)}</button>)}</div>}
          {run ? <RunView key={run} id={run} /> : <p className="text-sm text-muted">Start a task, or pick a recent run.</p>}
        </div>
      )}
      {tab === 'pending' && <Pending onOpen={open} />}
    </div>
  );
};

export default Control;
