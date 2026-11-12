import React, { useEffect, useRef, useState } from 'react';
import { Paperclip } from 'lucide-react';
import { vc, vError, btn } from '../velaris/velarisApi';
import { Notice, Card } from '../velaris/shared';
import { confirmAction } from '../confirmAction';
import { inputClass, labelClass } from '../prime/parts';

const list = (s) => s.split(/[,;\s]+/).map((x) => x.trim()).filter(Boolean);
const MAX_ATT = 45 * 1024;      // attachments travel inside the 64 KiB JSON body

const b64 = (file) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve(String(r.result).split(',')[1] || '');
  r.onerror = () => reject(new Error('The file could not be read.'));
  r.readAsDataURL(file);
});

// Submission tracking: sending is delayed by an undo window. While canCancel is true the person may cancel;
// a message that needs approval waits (with Velaris's reasons) until someone else decides.
export const SendStatus = ({ sub: first, mb, onDone }) => {
  const [sub, setSub] = useState(first);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [err, setErr] = useState('');
  const id = first.id;
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 500);
    const p = setInterval(() => vc.get(`/mail/submissions/${id}`).then((r) => setSub(r.data)).catch(() => {}), 2000);
    return () => { clearInterval(t); clearInterval(p); };
  }, [id]);
  const left = sub.sendAt ? Math.max(0, Math.ceil(sub.sendAt - now)) : null;
  const cancel = async () => {
    try { const r = await vc.post(`/mail/submissions/${id}/cancel`, {}); setSub(r.data); onDone?.('canceled'); } catch (e) { setErr(vError(e)); }
  };
  let text = `State: ${sub.state}`;
  if (sub.state === 'awaiting_approval') text = 'Waiting for approval before it can be sent.';
  else if (sub.state === 'approved' && sub.canCancel) text = `Sending in ${left}s.`;
  else if (sub.state === 'sent' || sub.sent_at) text = 'Sent.';
  else if (sub.state === 'canceled' || sub.undoStatus === 'canceled') text = 'Canceled. It was not sent.';
  return (
    <Notice tone={sub.state === 'canceled' ? 'info' : 'ok'}>
      <p>{text}</p>
      {(sub.reasons || []).length > 0 && <ul className="list-disc ml-5 mt-1">{sub.reasons.map((r) => <li key={r.code}>{r.text}</li>)}</ul>}
      {sub.error && <p className="text-danger mt-1">{sub.error}</p>}
      {sub.canCancel && <button className={`${btn('danger')} mt-2`} onClick={cancel} data-testid="undo-send">Undo send</button>}
      {err && <p role="alert" className="text-danger mt-1">{err}</p>}
      <span className="hidden" data-mb={mb} />
    </Notice>
  );
};

const Compose = ({ mb, reply, onClose }) => {
  const [f, setF] = useState({ to: reply?.to || '', cc: '', subject: reply?.subject || '', text: reply?.text || '' });
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [sub, setSub] = useState(null);
  const fileRef = useRef(null);

  const attach = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (file.size > MAX_ATT) { setErr('Attachments are limited to about 45 KB here (they are sent inside the message request).'); return; }
    try { setFiles([...files, { name: file.name, content_type: file.type || 'application/octet-stream', data_b64: await b64(file) }]); setErr(''); } catch (x) { setErr(x.message); }
  };

  const submit = async (e) => {
    e.preventDefault();
    const to = list(f.to);
    if (!to.length) { setErr('Add at least one recipient.'); return; }
    if (!(await confirmAction(`Send this message to ${to.join(', ')}? You will have a short window to undo it.`, 'Send message'))) return;
    setBusy(true); setErr('');
    try {
      const d = await vc.post(`/mail/mailboxes/${mb}/drafts`, { to, cc: list(f.cc), subject: f.subject, text: f.text,
        ...(files.length ? { attachments: files } : {}), ...(reply?.id ? { in_reply_to_id: reply.id } : {}) });
      const s = await vc.post(`/mail/mailboxes/${mb}/drafts/${d.data.id}/submit`, {});
      setSub(s.data);
    } catch (x) { setErr(vError(x)); } finally { setBusy(false); }
  };

  if (sub) return (
    <Card title="Message submitted">
      <SendStatus sub={sub} mb={mb} />
      <button className={btn('ghost')} onClick={onClose}>Close</button>
    </Card>
  );
  return (
    <Card title={reply ? 'Reply' : 'New message'}>
      <form onSubmit={submit} className="space-y-3">
        <label><span className={labelClass}>To</span><input className={inputClass} value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} aria-label="To" /></label>
        <label><span className={labelClass}>Cc</span><input className={inputClass} value={f.cc} onChange={(e) => setF({ ...f, cc: e.target.value })} aria-label="Cc" /></label>
        <label><span className={labelClass}>Subject</span><input className={inputClass} value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} aria-label="Subject" /></label>
        <label><span className={labelClass}>Message</span><textarea rows={8} className={inputClass} value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} aria-label="Message body" /></label>
        {files.map((x) => <span key={x.name} className="text-xs text-muted mr-2"><Paperclip className="w-3 h-3 inline" /> {x.name}</span>)}
        {err && <p role="alert" className="text-xs text-danger">{err}</p>}
        <div className="flex gap-2">
          <button className={btn()} disabled={busy}>Send</button>
          <input ref={fileRef} type="file" className="hidden" onChange={attach} aria-label="Attach a file" />
          <button type="button" className={btn('ghost')} onClick={() => fileRef.current?.click()}>Attach</button>
          <button type="button" className={btn('ghost')} onClick={onClose}>Discard</button>
        </div>
      </form>
    </Card>
  );
};

export default Compose;
