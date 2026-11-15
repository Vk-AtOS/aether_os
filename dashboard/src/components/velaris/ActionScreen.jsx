import React, { useState } from 'react';
import { api } from '../../api';
import { hr, useVelaris, vc, vError, isDown, btn } from './velarisApi';
import { LoadView, Card, Table, SpecForm, Notice } from './shared';
import { useAct } from './useAct';
import { Detail } from '../hr/hrParts';
import { inputClass } from '../prime/parts';

// One renderer for every Velaris gap screen (KAN-129..151). A screen is DATA (screens.js): sections of
//   {kind: 'load', call, args?, rows?: key, cols?}   read something and show it
//   {kind: 'form', call, fields, submit, typed?, danger?, download?, once?, text?}   send something
// call is one of {hr: [AGENT, method]} (the /hr proxy), {agent: [AGENT, method]} (generic /velaris/agents, for
// agents /hr does not serve) or {path, method} (chat / mail / flows proxies). Rules (role, typed word, caps) are the
// gateway's; this file only presents them. Secrets and tokens are shown from memory once and never stored.

const urlOf = (c) => (c.hr ? `/hr/${c.hr[0]}/${c.hr[1]}` : c.agent ? `/velaris/agents/${c.agent[0]}/${c.agent[1]}` : c.path);

const save = (name, data) => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

// -> {pending, run, result}. Throws Error(plain message) with .down for 503.
export const send = async (call, args = {}, { download } = {}) => {
  const method = (call.method || 'post').toLowerCase();
  if (call.hr && !download) return hr(call.hr[0], call.hr[1], args);
  let res;
  try {
    res = await vc.request({ method, url: urlOf(call), data: method === 'get' || call.asQuery ? undefined : args, params: method === 'get' || call.asQuery ? args : undefined });
  } catch (e) {
    const err = new Error(vError(e));
    err.down = isDown(e);
    throw err;
  }
  if (res.status === 202) return { pending: true, run: res.data.run || null, result: null };
  if (download) { save(download, res.data); return { pending: false, result: { saved: download } }; }
  const body = res.data;
  const result = call.agent || call.hr ? (body.result ?? {}) : body;
  if (result && result.status && result.status !== 'ok' && (call.agent || call.hr)) {
    throw new Error(result.reason || (result.errors || []).join('; ') || String(result.status).replace(/_/g, ' '));
  }
  return { pending: false, run: null, result };
};

const ExtraJson = { name: '_extra', label: 'Other fields (JSON, optional)', type: 'json', help: 'Anything else the method accepts, as {"name": value}. Organisation and actor fields are refused by the gateway.' };

const Out = ({ data, rows, cols }) => {
  const list = rows ? (data?.[rows] ?? []) : null;
  if (list && cols) return <Table rows={list} cols={cols.map(([h, k]) => [h, (r) => String(r[k] ?? '')])} />;
  if (typeof data === 'string') return <pre className="text-xs whitespace-pre-wrap break-words">{data}</pre>;   // text, never HTML
  return <Detail data={data} />;
};

const Load = ({ s }) => {
  const [n, setN] = useState(0);
  const fetcher = React.useMemo(() => () => send(s.call, s.args || {}).then((r) => ({ data: r.result })), [s, n]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useVelaris(fetcher);
  return (
    <Card title={s.title} actions={<button className={btn('ghost')} onClick={() => setN(n + 1)}>Refresh</button>}>
      {s.note && <p className="text-xs text-muted">{s.note}</p>}
      <LoadView q={q} isEmpty={(d) => d == null || (typeof d === 'object' && Object.keys(d).length === 0)} emptyText={s.empty || 'Nothing here yet.'}>
        {(d) => <Out data={d} rows={s.rows} cols={s.cols} />}
      </LoadView>
    </Card>
  );
};

const Form = ({ s }) => {
  const act = useAct();
  const [typed, setTyped] = useState('');
  const [out, setOut] = useState(null);
  const fields = s.raw ? s.fields : [...s.fields, ExtraJson];
  const submit = (v) => {
    const { _extra, ...named } = v;
    const args = { ...(_extra || {}), ...named, ...(s.fixed || {}) };
    if (s.typed) args.confirm = typed;
    // {name} segments of the path come from the form; the rest is the body (or the query string when asQuery)
    let call = s.call;
    if (s.path_params) {
      const pp = Object.fromEntries(s.path_params.map((k) => [k, encodeURIComponent(String(args[k]))]));
      s.path_params.forEach((k) => delete args[k]);
      call = { ...call, path: call.path.replace(/\{(\w+)\}/g, (_, k) => pp[k]), asQuery: Boolean(s.query) };
    }
    return act.run(async () => {
      const r = await send(call, args, { download: s.download });
      setOut(r.pending ? null : r.result);
      setTyped('');
      return r;
    }, s.danger ? { title: s.submit, message: s.warn || 'This cannot be undone.' } : undefined);
  };
  return (
    <Card title={s.title}>
      {s.note && <p className="text-xs text-muted">{s.note}</p>}
      {act.view}
      <SpecForm fields={fields} submitLabel={s.submit} busy={act.busy} disabled={Boolean(s.typed) && typed !== s.typed} onSubmit={submit} />
      {s.typed && (
        <label className="block text-xs text-muted">Type <b className="text-bright">{s.typed}</b> to enable the button
          <input aria-label={`Type ${s.typed}`} className={`${inputClass} max-w-[10rem] ml-2`} value={typed} onChange={(e) => setTyped(e.target.value)} />
        </label>
      )}
      {out != null && !s.once && <Out data={out} />}
      {out != null && s.once && (
        <Notice tone="warn">Shown once. Copy it now: it is not stored and cannot be shown again.<div className="mt-2 break-all font-mono"><Detail data={out} /></div>
          <button className={`${btn('ghost')} mt-2`} onClick={() => setOut(null)}>Hide</button></Notice>
      )}
    </Card>
  );
};

// The agent's own status class (real / rule_based / not_implemented) so a thin agent is not shown as authoritative.
const Status = ({ agents, names }) => {
  const f = React.useMemo(() => () => api.getVelarisAgents(), []);
  const q = useVelaris(f);
  const by = Object.fromEntries((q.data?.agents || []).map((a) => [a.name, a.status]));
  const shown = names.filter((n) => by[n]);
  if (!shown.length) return null;
  return <p className="text-[10px] text-muted">{shown.map((n) => `${n}: ${String(by[n]).replace(/_/g, ' ')}`).join(' · ')}{agents}</p>;
};

const ActionScreen = ({ screen }) => {
  const agents = [...new Set(screen.sections.map((s) => (s.call.hr || s.call.agent || [])[0]).filter(Boolean))];
  return (
    <div className="space-y-4">
      {screen.banner && <Notice tone="warn">{screen.banner}</Notice>}
      {agents.length > 0 && <Status names={agents} agents="" />}
      {screen.sections.map((s) => (s.kind === 'load' ? <Load key={s.title} s={s} /> : <Form key={s.title} s={s} />))}
    </div>
  );
};

export default ActionScreen;
