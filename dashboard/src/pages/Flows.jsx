import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Workflow } from 'lucide-react';
import { api } from '../api';
import { vc, vError, useVelaris, btn } from '../components/velaris/velarisApi';
import { PageHead, Card, LoadView, Table, SpecForm, Notice } from '../components/velaris/shared';
import { Detail } from '../components/hr/hrParts';
import { useAct } from '../components/velaris/useAct';

const FINAL = ['done', 'completed', 'failed', 'rejected', 'cancelled', 'killed', 'expired'];
const toolNames = (agents) => (agents || []).flatMap((a) => (a.methods || []).map((m) => `${a.name}.${typeof m === 'string' ? m : m.name}`));

// Run detail: polls until a final status. A waiting step links to the Prime inbox.
const Run = ({ id }) => {
  const [run, setRun] = useState(null);
  const [error, setError] = useState('');
  const [chain, setChain] = useState(null);
  useEffect(() => {
    let alive = true;
    let timer;
    const tick = async () => {
      try {
        const { data } = await vc.get(`/velaris/flows/${id}`);
        if (!alive) return;
        setRun(data); setError('');
        if (!FINAL.includes(String(data.status))) timer = setTimeout(tick, 3000);   // bounded by the run ending
      } catch (e) { if (alive) setError(vError(e)); }
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [id]);
  const verify = async () => {
    try { setChain((await vc.get(`/velaris/flows/${id}/verify`)).data); } catch (e) { setChain({ error: vError(e) }); }
  };
  return (
    <Card title={`Run ${id}`} actions={<button className={btn('ghost')} onClick={verify}>Verify hash chain</button>}>
      {error && <Notice tone="warn">{error}</Notice>}
      {run && String(run.status).includes('waiting') && <Notice tone="warn">Waiting for approval. Decide it in <Link to="/prime/inbox" className="underline font-bold">Prime</Link>.</Notice>}
      {chain && <Notice tone={chain.ok ? 'ok' : 'warn'}>{chain.error || (chain.ok ? 'Chain OK: no step was changed.' : `Chain broken at step ${chain.broken_index ?? chain.index ?? '?'}.`)}</Notice>}
      {run && <Detail data={run} />}
    </Card>
  );
};

const Flows = () => {
  const act = useAct();
  const [open, setOpen] = useState('');
  const agents = useVelaris(useCallback(() => api.getVelarisAgents(), []));
  const pending = useVelaris(useCallback(() => vc.get('/velaris/flows/pending'), []));
  const tools = useMemo(() => toolNames(agents.data?.agents), [agents.data]);
  const start = (v) => act.run(async () => {
    const res = await vc.post('/velaris/flows', { task: v.task, tools: v.tools }).catch((e) => { throw new Error(vError(e)); });
    setOpen(res.data.run_id || res.data.run?.run_id || '');
    pending.reload();
    return { pending: false };
  });
  return (
    <div className="space-y-4">
      <PageHead icon={Workflow} title="Flows" sub="Give a task and the tools a model may use. Steps that change something wait for approval." />
      <Card title="Start a flow">
        {act.view}
        <SpecForm submitLabel="Start" busy={act.busy} onSubmit={start} fields={[
          { name: 'task', label: 'Task', type: 'textarea', required: true },
          { name: 'tools', label: 'Tools (AGENT.method, one per line)', type: 'list', required: true, help: tools.length ? `${tools.length} tools available. Export, erasure and HR methods are not available to flows.` : undefined }]} />
      </Card>
      <Card title="Waiting for a decision">
        <LoadView q={pending} isEmpty={(d) => !(d.runs || d.pending || []).length} emptyText="No runs are waiting.">
          {(d) => <Table rows={d.runs || d.pending} onRow={(r) => setOpen(r.run_id)} cols={[['Run', (r) => r.run_id], ['Status', (r) => r.status], ['Task', (r) => String(r.task || '').slice(0, 80)]]} />}
        </LoadView>
      </Card>
      {open && <Run key={open} id={open} />}
    </div>
  );
};

export default Flows;
