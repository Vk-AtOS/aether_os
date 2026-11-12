import React, { useCallback, useState } from 'react';
import { vc, vError, useVelaris, btn } from '../velaris/velarisApi';
import { LoadView, Card, Notice } from '../velaris/shared';
import { confirmAction } from '../confirmAction';
import { inputClass, labelClass } from '../prime/parts';

const FIELDS = ['from', 'from_domain', 'to', 'cc', 'subject', 'body', 'list_id', 'has_attachment', 'size', 'spam_score', 'spf', 'dmarc'];
const OPS = ['==', '!=', 'contains', 'matches', '>', '>=', '<', '<=', 'exists', 'absent'];
const ACTIONS = ['move', 'label', 'forward', 'auto_reply', 'mark_read', 'flag', 'stop'];
const blank = { name: '', field: 'from', op: 'contains', value: '', action: 'label', arg: '' };

const toRule = (f) => {
  const a = { type: f.action };
  if (f.action === 'move') a.folder = f.arg;
  if (f.action === 'label') a.label = f.arg;
  if (f.action === 'forward') a.to = f.arg.split(/[,\s]+/).filter(Boolean);
  if (f.action === 'auto_reply') a.body = f.arg;
  return { name: f.name, enabled: true, conditions: f.value ? [{ field: f.field, op: f.op, value: f.value }] : [], actions: [a] };
};

const Rules = ({ mb }) => {
  const f = useCallback(() => vc.get(`/mail/mailboxes/${mb}/rules`), [mb]);
  const q = useVelaris(f);
  const [form, setForm] = useState(blank);
  const [dry, setDry] = useState(null);
  const [msg, setMsg] = useState('');
  const run = async (fn) => { try { await fn(); setMsg(''); q.reload(); } catch (e) { setMsg(vError(e)); } };
  const dryRun = async () => { try { const r = await vc.post(`/mail/mailboxes/${mb}/rules/dry-run`, toRule(form)); setDry(r.data); setMsg(''); } catch (e) { setDry(null); setMsg(vError(e)); } };
  const save = async () => {
    if (await confirmAction('Save this rule? It runs on every message that arrives from now on. Forwarding rules need a second approver.', 'Save rule')) run(async () => { await vc.post(`/mail/mailboxes/${mb}/rules`, toRule(form)); setForm(blank); setDry(null); });
  };
  const sel = (k, opts) => <select className={inputClass} aria-label={k} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })}>{opts.map((o) => <option key={o}>{o}</option>)}</select>;
  return (
    <div className="space-y-4 max-w-3xl">
      <Card title="New rule">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <label className="col-span-2 sm:col-span-4"><span className={labelClass}>Name</span><input className={inputClass} aria-label="Rule name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label><span className={labelClass}>When</span>{sel('field', FIELDS)}</label>
          <label><span className={labelClass}>Is</span>{sel('op', OPS)}</label>
          <label className="col-span-2"><span className={labelClass}>Value</span><input className={inputClass} aria-label="Condition value" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} /></label>
          <label><span className={labelClass}>Then</span>{sel('action', ACTIONS)}</label>
          <label className="col-span-3"><span className={labelClass}>Folder / label / addresses / reply text</span><input className={inputClass} aria-label="Action detail" value={form.arg} onChange={(e) => setForm({ ...form, arg: e.target.value })} /></label>
        </div>
        <div className="flex gap-2"><button className={btn('ghost')} onClick={dryRun}>Dry run</button><button className={btn()} disabled={!form.name} onClick={save}>Save rule</button></div>
        {dry && <Notice>Checked the latest {dry.checked_latest} messages: {dry.would_match.length} would match and get: {dry.would_do.join(', ')}. Nothing was changed.{dry.forward_needs_second_approver && ' Forwarding needs a second approver.'}</Notice>}
        {msg && <p role="alert" className="text-xs text-danger">{msg}</p>}
      </Card>
      <LoadView q={q} isEmpty={(d) => d.rules.length === 0} emptyText="No rules yet.">
        {(d) => d.rules.map((r) => (
          <Card key={r.id} title={r.name}>
            <p className="text-xs text-muted">{r.conditions.map((c) => `${c.field} ${c.op || '=='} "${c.value}"`).join(' and ') || 'every message'} → {r.actions.map((a) => a.type).join(', ')} · {r.enabled ? 'on' : 'off'}</p>
            <div className="flex gap-2">
              <button className={btn('ghost')} onClick={() => run(() => vc.put(`/mail/mailboxes/${mb}/rules/${r.id}`, { name: r.name, enabled: !r.enabled, conditions: r.conditions, actions: r.actions }))}>{r.enabled ? 'Turn off' : 'Turn on'}</button>
              <button className={btn('danger')} onClick={async () => { if (await confirmAction(`Delete the rule "${r.name}"?`, 'Delete rule')) run(() => vc.delete(`/mail/mailboxes/${mb}/rules/${r.id}`)); }}>Delete</button>
            </div>
          </Card>
        ))}
      </LoadView>
    </div>
  );
};

export default Rules;
