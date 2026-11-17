import React, { useRef, useState } from 'react';
import { hr, useHr, btn } from '../velaris/velarisApi';
import { LoadView, Card, Table, SpecForm } from '../velaris/shared';
import { useAct } from '../velaris/useAct';
import { StateBadge, Detail } from './hrParts';

const MAX = 45 * 1024;      // the document travels base64 inside a 64 KiB request
const b64 = (f) => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] || ''); r.onerror = () => rej(new Error('The file could not be read.')); r.readAsDataURL(f); });

// The document hash from the request is shown next to the verdict so it can be compared with a sealed download.
const Verify = ({ id, hash }) => {
  const q = useHr('ESIGN', 'verify', { request_id: id });
  return (
    <LoadView q={q}>{(v) => (
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-xs">
          <StateBadge state={v.valid ? 'approved' : 'rejected'} /><span>{v.valid ? 'Every check passed' : 'At least one check failed'}</span>
        </div>
        {hash && <div className="text-xs">Document SHA-256: <code data-testid="doc-hash" className="font-mono break-all">{hash}</code></div>}
        <Detail data={v} />
      </div>
    )}</LoadView>
  );
};

const Request = ({ id, done }) => {
  const q = useHr('ESIGN', 'get_request', { request_id: id });
  const [check, setCheck] = useState(false);
  const act = useAct();
  const doit = (method, args, title, message) => act.run(async () => { const out = await hr('ESIGN', method, { request_id: id, ...args }); done(); q.reload(); return out; }, { title, message });
  return (
    <Card title={`Request ${id.slice(0, 10)}`}>
      <LoadView q={q}>{(d) => (
        <div className="space-y-3">
          <Detail data={d.request || d} />
          <div className="flex flex-wrap gap-2">
            <button className={btn()} disabled={act.busy} onClick={() => doit('send_request', {}, 'Send for signature?', 'Each signer receives their personal signing code. Anyone holding a code can act as that signer.')}>Send</button>
            <button className={btn('danger')} disabled={act.busy} onClick={() => doit('void_request', { reason: 'Voided from the dashboard' }, 'Void this request?', 'Signing codes stop working. This cannot be undone.')}>Void</button>
            <button className={btn('ghost')} onClick={() => setCheck(true)}>Verify integrity</button>
          </div>
          {act.view}
          {check && <Verify id={id} hash={(d.request || d).document_sha256} />}
        </div>
      )}</LoadView>
    </Card>
  );
};

const ESign = () => {
  const q = useHr('ESIGN', 'list_requests');
  const [open, setOpen] = useState(null);
  const [doc, setDoc] = useState(null);
  const [err, setErr] = useState('');
  const fileRef = useRef(null);
  const act = useAct();
  const pick = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    if (f.size > MAX) { setErr('Documents are limited to about 45 KB here.'); return; }
    try { setDoc({ name: f.name, data: await b64(f) }); setErr(''); } catch (x) { setErr(x.message); }
  };
  const create = (v) => act.run(async () => { const out = await hr('ESIGN', 'create_request', { title: v.title, document_base64: doc.data, signers: v.signers, ...(v.valid_days ? { valid_days: v.valid_days } : {}) }); q.reload(); return out; },
    { title: 'Create this signature request?', message: 'The document is registered with its hash. Nothing is sent to signers until you send it.' });
  return (
    <div className="space-y-4">
      <Card title="Signature requests">
        <LoadView q={q} isEmpty={(d) => (d.requests || []).length === 0} emptyText="No signature requests yet.">
          {(d) => <Table rows={d.requests} onRow={(r) => setOpen(r.id)} cols={[['Title', (r) => r.title], ['Status', (r) => <StateBadge state={r.status} />], ['Signers', (r) => (r.signers || []).length], ['Expires', (r) => r.expires_at]]} />}
        </LoadView>
      </Card>
      {open && <Request key={open} id={open} done={q.reload} />}
      <Card title="New request">
        <input ref={fileRef} type="file" className="hidden" onChange={pick} aria-label="Document to sign" />
        <button className={btn('ghost')} onClick={() => fileRef.current?.click()}>{doc ? `Document: ${doc.name}` : 'Choose the document'}</button>
        {err && <p role="alert" className="text-xs text-danger">{err}</p>}
        {doc && <SpecForm submitLabel="Create request" busy={act.busy} onSubmit={create} fields={[
          { name: 'title', label: 'Title', type: 'text', required: true }, { name: 'valid_days', label: 'Valid for (days)', type: 'number' },
          { name: 'signers', label: 'Signers (JSON)', type: 'json', required: true, placeholder: '[{"name":"A Person","email":"a@example.com"}]' }]} />}
        {act.view}
      </Card>
    </div>
  );
};

export default ESign;
