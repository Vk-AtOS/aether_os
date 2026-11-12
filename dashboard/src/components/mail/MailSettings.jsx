import React, { useCallback, useState } from 'react';
import { vc, vError, useVelaris, btn } from '../velaris/velarisApi';
import { LoadView, Card, Notice } from '../velaris/shared';
import { confirmAction } from '../confirmAction';
import { inputClass, labelClass, Facts } from '../prime/parts';

const Mailbox = ({ mb }) => {
  const f = useCallback(() => vc.get(`/mail/mailboxes/${mb}/settings`), [mb]);
  const q = useVelaris(f);
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);
  const save = async (cur) => {
    if (!(await confirmAction('Save the signature and vacation reply? A vacation reply answers senders automatically.', 'Save mail settings'))) return;
    try {
      await vc.put(`/mail/mailboxes/${mb}/settings`, { signature: cur.signature, vacation: { enabled: Boolean(cur.vacation?.enabled), subject: cur.vacation?.subject || '', body: cur.vacation?.body || '' } });
      setMsg({ tone: 'ok', text: 'Saved.' }); q.reload(); setForm(null);
    } catch (e) { setMsg({ tone: 'warn', text: vError(e) }); }
  };
  return (
    <LoadView q={q}>
      {(d) => {
        const cur = form || d;
        const v = cur.vacation || {};
        return (
          <Card title="Signature and vacation reply">
            <label><span className={labelClass}>Signature</span><textarea rows={3} className={inputClass} value={cur.signature || ''} onChange={(e) => setForm({ ...cur, signature: e.target.value })} aria-label="Signature" /></label>
            <label className="flex gap-2 text-xs text-bright"><input type="checkbox" checked={Boolean(v.enabled)} onChange={(e) => setForm({ ...cur, vacation: { ...v, enabled: e.target.checked } })} />Vacation reply on</label>
            <input className={inputClass} placeholder="Subject" aria-label="Vacation subject" value={v.subject || ''} onChange={(e) => setForm({ ...cur, vacation: { ...v, subject: e.target.value } })} />
            <textarea rows={3} className={inputClass} placeholder="Reply text" aria-label="Vacation text" value={v.body || ''} onChange={(e) => setForm({ ...cur, vacation: { ...v, body: e.target.value } })} />
            <button className={btn()} onClick={() => save(cur)}>Save</button>
            {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
          </Card>
        );
      }}
    </LoadView>
  );
};

// Claim a domain, publish the TXT value, then verify. Needs the mail_admin role (Velaris says so when it is missing).
const Domains = () => {
  const f = useCallback(() => vc.get('/mail/domains'), []);
  const q = useVelaris(f);
  const [domain, setDomain] = useState('');
  const [msg, setMsg] = useState(null);
  const run = async (fn, ok) => { try { const r = await fn(); setMsg({ tone: 'ok', text: ok(r.data) }); q.reload(); } catch (e) { setMsg({ tone: 'warn', text: vError(e) }); } };
  return (
    <Card title="Sending domains">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); run(() => vc.post('/mail/domains', { domain: domain.trim() }), (d) => `Claimed ${d.domain}. Publish the TXT record below, then verify.`); setDomain(''); }}>
        <input className={inputClass} placeholder="example.com" aria-label="Domain" value={domain} onChange={(e) => setDomain(e.target.value)} />
        <button className={btn()} disabled={!domain.trim()}>Claim</button>
      </form>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      <LoadView q={q} isEmpty={(d) => d.domains.length === 0} emptyText="No domains claimed yet.">
        {(d) => d.domains.map((x) => (
          <div key={x.domain} className="border border-border rounded-lg p-3 space-y-2">
            <p className="text-sm text-bright font-semibold">{x.domain} <span className={x.status === 'verified' ? 'text-success text-xs' : 'text-warning text-xs'}>{x.status}</span></p>
            {x.status !== 'verified' && (
              <>
                <Facts rows={[['DNS record', x.record?.type], ['Name', x.record?.name], ['Value', x.record?.value]]} />
                <button className={btn()} onClick={() => run(() => vc.post('/mail/domains/verify', { domain: x.domain }), (r) => (r.status === 'verified' ? `${x.domain} is verified.` : 'The TXT record was not found yet. DNS can take a while; try again.'))}>Verify</button>
              </>
            )}
          </div>
        ))}
      </LoadView>
    </Card>
  );
};

const MailSettings = ({ mb }) => (
  <div className="space-y-4 max-w-2xl"><Mailbox mb={mb} /><Domains /></div>
);

export default MailSettings;
