import React, { useState } from 'react';
import { api } from '../../api';
import { useVelaris, vc, btn, send } from './velarisApi';
import { LoadView, Card, Table, SpecForm, Notice } from './shared';
import { useAct } from './useAct';
import { decode } from '../../hooks/useRole';
import { Detail } from '../hr/hrParts';
import { inputClass } from '../prime/parts';

// One renderer for every Velaris gap screen (KAN-129..151). A screen is DATA (screens.js): sections of
//   {kind: 'load', call, args?, rows?: key, cols?}   read something and show it
//   {kind: 'form', call, fields, submit, typed?, danger?, download?, once?, text?}   send something
// call is one of {hr: [AGENT, method]} (the /hr proxy), {agent: [AGENT, method]} (generic /velaris/agents, for
// agents /hr does not serve) or {path, method} (chat / mail / flows proxies). Rules (role, typed word, caps) are the
// gateway's; this file only presents them. Secrets and tokens are shown from memory once and never stored.

// The signed-in organisation: library and memory scopes must be exactly it (Velaris refuses any other).
const orgScope = () => decode(api.getToken() || '')?.org_id || '';
const fill = (fixed = {}) => Object.fromEntries(Object.entries(fixed).map(([k, v]) => [k, v === '@org' ? orgScope() : v]));

const isScalar = (v) => v == null || ['string', 'number', 'boolean'].includes(typeof v);
// A list of records (compute_bulk: one result per employee) is a table of its simple fields; the rest is in Detail.
const ListTable = ({ list }) => {
  const keys = [...new Set(list.flatMap((r) => Object.keys(r || {}).filter((k) => isScalar(r[k]))))].slice(0, 12);
  return (
    <div className="space-y-2">
      <Table rows={list} cols={keys.map((k) => [k, (r) => String(r?.[k] ?? '')])} />
      <details><summary className="text-[11px] text-muted cursor-pointer">Full detail per row</summary><Detail data={list} /></details>
    </div>
  );
};

// Only http(s) addresses become links; anything else (javascript:, data:) stays plain text.
const safeHref = (u) => (typeof u === 'string' && /^https?:\/\//i.test(u) ? u : null);

// Sources of an answer (library, research, search) as a list of links, never as raw HTML.
export const Sources = ({ list }) => (
  <div className="space-y-1"><div className="text-[11px] font-bold text-muted uppercase">Sources</div>
    <ul className="text-xs list-disc pl-4 space-y-0.5">{list.map((x, i) => {
      const o = typeof x === 'string' ? { url: x } : (x || {});
      const href = safeHref(o.url || o.link || o.href);
      const label = o.title || o.name || o.url || o.source || o.id || `Source ${i + 1}`;
      return <li key={i}>{href ? <a className="text-accent underline break-all" href={href} target="_blank" rel="noopener noreferrer">{String(label)}</a> : <span className="break-all">{String(label)}</span>}</li>;
    })}</ul>
  </div>
);

// A Jira issue as a fixed layout (key, summary, status, people, description); unknown fields stay under Full detail.
export const IssueView = ({ data }) => {
  const i = data?.issue || data || {};
  const f = i.fields || i;
  const name = (v) => (v && typeof v === 'object' ? v.displayName || v.name || '' : v || '');
  const desc = typeof f.description === 'string' ? f.description : f.description ? JSON.stringify(f.description) : '';
  const comments = f.comment?.comments || i.comments || [];
  return (
    <div className="space-y-2 text-xs">
      <div className="text-sm font-bold text-bright"><span className="font-mono">{i.key}</span> {f.summary}</div>
      <div className="flex flex-wrap gap-3 text-muted">
        {[['Status', name(f.status)], ['Type', name(f.issuetype)], ['Priority', name(f.priority)], ['Assignee', name(f.assignee)], ['Reporter', name(f.reporter)]].filter(([, v]) => v).map(([k, v]) => <span key={k}>{k}: <b className="text-bright">{String(v)}</b></span>)}
      </div>
      {desc && <pre className="whitespace-pre-wrap break-words bg-surface p-2 rounded border border-border">{desc}</pre>}
      {comments.length > 0 && <div><div className="text-[11px] font-bold text-muted uppercase">Comments ({comments.length})</div>
        {comments.slice(0, 20).map((c, k) => <div key={k} className="border-l border-border pl-2 my-1"><b>{name(c.author)}</b> <span className="text-muted">{c.created}</span><pre className="whitespace-pre-wrap break-words">{typeof c.body === 'string' ? c.body : JSON.stringify(c.body)}</pre></div>)}</div>}
      <details><summary className="text-[11px] text-muted cursor-pointer">Full detail</summary><Detail data={data} /></details>
    </div>
  );
};

// Side-by-side horizontal bars for one number per row (calibration: agreement per competency, -1..1).
export const BarChart = ({ list, label, value, min = 0, max = 1 }) => (
  <div className="space-y-1" role="img" aria-label="Chart">
    {list.map((r, i) => {
      const v = Number(r?.[value]);
      const ok = Number.isFinite(v);
      const pct = ok ? Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100)) : 0;
      return (
        <div key={i} className="grid grid-cols-[12rem_1fr_4rem] items-center gap-2 text-xs">
          <span className="truncate" title={String(r?.[label] ?? '')}>{String(r?.[label] ?? '')}</span>
          <div className="h-3 bg-surface border border-border rounded"><div className={`h-full rounded ${ok && v >= 0.667 ? 'bg-success' : ok && v >= 0.4 ? 'bg-warning' : 'bg-danger'}`} style={{ width: `${pct}%` }} /></div>
          <span className="font-mono text-right">{ok ? v.toFixed(2) : 'n/a'}</span>
        </div>
      );
    })}
  </div>
);

const Out = ({ data, rows, cols, view, chart }) => {
  const list = rows ? (data?.[rows] ?? []) : null;
  if (view === 'issue' && data && typeof data === 'object') return <IssueView data={data} />;
  if (chart && list?.length) return <div className="space-y-3"><BarChart list={list} {...chart} /><ListTable list={list} /></div>;
  if (list && cols) return <Table rows={list} cols={cols.map(([h, k]) => [h, (r) => String(r[k] ?? '')])} />;
  if (data && typeof data === 'object' && !Array.isArray(data) && Array.isArray(data.sources) && data.sources.length) {
    const { sources, ...rest } = data;
    return <div className="space-y-3">{Object.keys(rest).length > 0 && <Out data={rest} />}<Sources list={sources} /></div>;
  }
  const arr = Array.isArray(data) ? data : Object.values(data || {}).length === 1 && Array.isArray(Object.values(data)[0]) ? Object.values(data)[0] : null;
  if (arr && arr.length && arr.every((r) => r && typeof r === 'object' && !Array.isArray(r))) return <ListTable list={arr} />;
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
        {(d) => <Out data={d} rows={s.rows} cols={s.cols} view={s.view} chart={s.chart} />}
      </LoadView>
    </Card>
  );
};

const Form = ({ s }) => {
  const act = useAct();
  const [typed, setTyped] = useState('');
  const [out, setOut] = useState(null);
  const submit = (v) => {
    const args = { ...v, ...fill(s.fixed) };
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
      <SpecForm fields={s.fields} submitLabel={s.submit} busy={act.busy} disabled={Boolean(s.typed) && typed !== s.typed} onSubmit={submit} />
      {s.typed && (
        <label className="block text-xs text-muted">Type <b className="text-bright">{s.typed}</b> to enable the button
          <input aria-label={`Type ${s.typed}`} className={`${inputClass} max-w-[10rem] ml-2`} value={typed} onChange={(e) => setTyped(e.target.value)} />
        </label>
      )}
      {out != null && !s.once && <Out data={out} view={s.view} />}
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

// Which sign-in is which Velaris employee record (admin). Own-record screens need this link.
const Links = () => {
  const [n, setN] = useState(0);
  const fetcher = React.useMemo(() => () => vc.get('/hr/links'), [n]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useVelaris(fetcher);
  const act = useAct();
  const [draft, setDraft] = useState({});
  const set = (u) => act.run(async () => {
    await vc.put(`/hr/links/${encodeURIComponent(u.user_id)}`, { employee_id: (draft[u.user_id] ?? u.employee_id ?? '').trim() || null });
    setN(n + 1);
    return {};
  });
  return (
    <Card title="Sign-ins and employee records">
      {act.view}
      <LoadView q={q} isEmpty={(d) => !d?.links?.length} emptyText="No users.">
        {(d) => <Table rows={d.links} cols={[['User', (u) => u.email], ['Employee id', (u) => (
          <input aria-label={`Employee id of ${u.email}`} className={`${inputClass} max-w-[14rem]`} defaultValue={u.employee_id || ''} onChange={(e) => setDraft({ ...draft, [u.user_id]: e.target.value })} />
        )], ['', (u) => <button className={btn('ghost')} disabled={act.busy} onClick={() => set(u)}>Save</button>]]} />}
      </LoadView>
    </Card>
  );
};

const ActionScreen = ({ screen }) => {
  const agents = [...new Set(screen.sections.map((s) => ((s.call || {}).hr || (s.call || {}).agent || [])[0]).filter(Boolean))];
  return (
    <div className="space-y-4">
      {screen.banner && <Notice tone="warn">{screen.banner}</Notice>}
      {agents.length > 0 && <Status names={agents} agents="" />}
      {screen.sections.map((s) => (s.kind === 'links' ? <Links key="links" /> : s.kind === 'load' ? <Load key={s.title} s={s} /> : <Form key={s.title} s={s} />))}
    </div>
  );
};

export default ActionScreen;
