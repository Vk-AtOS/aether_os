import React, { useCallback, useState } from 'react';
import { vc, vError, useVelaris, btn } from '../velaris/velarisApi';
import { LoadView, Card, Notice } from '../velaris/shared';
import { confirmAction } from '../confirmAction';
import { inputClass, labelClass } from '../prime/parts';

// Chat administration: retention, AI switch, legal hold, export, sweep. Velaris answers 403 unless the person is a chat admin.
const AdminPanel = ({ channels }) => {
  const f = useCallback(() => vc.get('/chat/admin/settings'), []);
  const q = useVelaris(f);
  const [msg, setMsg] = useState({ tone: 'info', text: '' });
  const [form, setForm] = useState(null);
  const [ch, setCh] = useState('');
  const say = (text, tone = 'ok') => setMsg({ tone, text });
  const run = async (fn, ok) => { try { await fn(); say(ok); q.reload(); } catch (e) { say(vError(e), 'warn'); } };
  const cur = form || q.data;
  const channel = channels.find((c) => String(c.id) === ch);

  const save = async () => {
    const body = { retention_days: cur.retention_days === '' || cur.retention_days == null ? null : Number(cur.retention_days),
      purge_grace_days: Number(cur.purge_grace_days), ai_enabled: Boolean(cur.ai_enabled) };
    if (!(await confirmAction('Change the organisation-wide chat settings? Shorter retention deletes older messages at the next sweep.', 'Save chat settings'))) return;
    run(() => vc.put('/chat/admin/settings', body), 'Settings saved.');
  };
  const exportChannel = async () => {
    try {
      const r = await vc.get(`/chat/admin/channels/${ch}/export`);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([JSON.stringify(r.data, null, 2)], { type: 'application/json' }));
      a.download = `channel-${ch}-export.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { say(vError(e), 'warn'); }
  };

  return (
    <div className="space-y-4 max-w-2xl">
      {msg.text && <Notice tone={msg.tone}>{msg.text}</Notice>}
      <LoadView q={q}>
        {() => (
          <Card title="Organisation settings">
            <div className="grid grid-cols-2 gap-3">
              <label><span className={labelClass}>Retention (days, blank = keep)</span>
                <input type="number" className={inputClass} value={cur.retention_days ?? ''} onChange={(e) => setForm({ ...cur, retention_days: e.target.value })} /></label>
              <label><span className={labelClass}>Purge grace (days)</span>
                <input type="number" className={inputClass} value={cur.purge_grace_days ?? 0} onChange={(e) => setForm({ ...cur, purge_grace_days: e.target.value })} /></label>
            </div>
            <label className="flex gap-2 text-xs text-bright"><input type="checkbox" checked={Boolean(cur.ai_enabled)} onChange={(e) => setForm({ ...cur, ai_enabled: e.target.checked })} />Assistant switched on for the organisation (the AI switch)</label>
            <button className={btn()} onClick={save}>Save settings</button>
          </Card>
        )}
      </LoadView>
      <Card title="Channel compliance">
        <select className={inputClass} aria-label="Channel" value={ch} onChange={(e) => setCh(e.target.value)}>
          <option value="">Choose a channel</option>
          {channels.map((c) => <option key={c.id} value={c.id}>{c.name || `${c.kind} ${c.id}`}</option>)}
        </select>
        {channel && (
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-xs text-muted">Legal hold is {channel.legal_hold ? 'ON' : 'off'}.</span>
            <button className={btn(channel.legal_hold ? 'ghost' : 'danger')} onClick={async () => {
              const on = !channel.legal_hold;
              if (await confirmAction(on ? 'Place a legal hold? Nothing in this channel can be deleted or purged until it is lifted.' : 'Lift the legal hold? Retention applies again.', 'Legal hold')) {
                run(() => vc.put(`/chat/admin/channels/${ch}/hold`, { hold: on }), on ? 'Legal hold set.' : 'Legal hold lifted.');
              }
            }}>{channel.legal_hold ? 'Lift hold' : 'Place hold'}</button>
            <button className={btn('ghost')} onClick={async () => { if (await confirmAction('Export every message of this channel? The export is recorded in the ledger.', 'Export channel')) exportChannel(); }}>Export</button>
          </div>
        )}
        <button className={btn('danger')} onClick={async () => { if (await confirmAction('Apply retention now? Messages past retention are removed for good.', 'Run retention sweep')) run(() => vc.post('/chat/admin/sweep', {}), 'Retention sweep done.'); }}>Run retention sweep</button>
      </Card>
    </div>
  );
};

export default AdminPanel;
