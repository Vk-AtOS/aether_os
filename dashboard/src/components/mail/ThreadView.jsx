import React, { useCallback, useState } from 'react';
import { ShieldAlert, ImageOff, Paperclip, Sparkles } from 'lucide-react';
import { vc, vError, useVelaris, when, btn } from '../velaris/velarisApi';
import { LoadView, Notice, Card } from '../velaris/shared';
import { Json, inputClass } from '../prime/parts';

const authBits = (s) => ['spf', 'dkim', 'dmarc'].map((k) => {
  const m = new RegExp(`${k}=(\\w+)`, 'i').exec(s || '');
  return [k, m ? m[1].toLowerCase() : null];
});

// The body is rendered ONLY as the sanitised HTML Velaris returns, inside an iframe with an empty sandbox
// (no scripts, no same-origin, no forms, no popups, no top navigation), else as plain text.
const Body = ({ m }) => (m.body_html
  ? <iframe title={`Message ${m.id}`} sandbox="" referrerPolicy="no-referrer" srcDoc={m.body_html} className="w-full h-96 bg-white rounded border border-border" />
  : <pre className="whitespace-pre-wrap break-words text-sm text-bright font-sans">{m.body_text || '(no text)'}</pre>);

const Banners = ({ m }) => {
  const bits = authBits(m.auth_results);
  const bad = bits.filter(([, v]) => v && v !== 'pass');
  return (
    <div className="space-y-1">
      {bits.some(([, v]) => v) && (
        <p className={`text-[11px] ${bad.length ? 'text-warning' : 'text-success'}`}>
          Sender checks: {bits.map(([k, v]) => `${k.toUpperCase()} ${v || 'none'}`).join(', ')}
        </p>
      )}
      {bad.length > 0 && <Notice tone="warn"><ShieldAlert className="w-3.5 h-3.5 inline mr-1" aria-hidden="true" />This message failed {bad.map(([k]) => k.toUpperCase()).join(' and ')}. It may not be from who it says.</Notice>}
      {m.spam_score > 0 && (m.spam_report || []).length > 0 && (
        <Notice tone="warn"><ShieldAlert className="w-3.5 h-3.5 inline mr-1" aria-hidden="true" />Spam score {m.spam_score}: {m.spam_report.map((r) => (typeof r === 'string' ? r : r.rule || r.reason || JSON.stringify(r))).join('; ')}</Notice>
      )}
      {m.blocked_images > 0 && <Notice><ImageOff className="w-3.5 h-3.5 inline mr-1" aria-hidden="true" />{m.blocked_images} remote image{m.blocked_images === 1 ? ' was' : 's were'} blocked.</Notice>}
      {m.defects?.length > 0 && <Notice tone="warn">The message was malformed: {m.defects.join(', ')}.</Notice>}
    </div>
  );
};

const Assistant = ({ mb, thread, last, onReply }) => {
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState('');
  const [instr, setInstr] = useState('');
  const go = async (kind, body) => {
    setBusy(kind); setOut(null);
    try { const r = await vc.post(`/mail/mailboxes/${mb}/assistant/${kind}`, body); setOut({ kind, data: r.data }); } catch (e) { setOut({ error: vError(e) }); } finally { setBusy(''); }
  };
  return (
    <Card title="Assistant">
      <div className="flex flex-wrap gap-2">
        <button className={btn('ghost')} disabled={Boolean(busy)} onClick={() => go('summarise', { thread_id: thread })}><Sparkles className="w-3 h-3 inline mr-1" />Summarise</button>
        <button className={btn('ghost')} disabled={Boolean(busy)} onClick={() => go('action-items', { thread_id: thread })}>Action items</button>
        <button className={btn('ghost')} disabled={Boolean(busy)} onClick={() => go('triage', { message_id: last })}>Triage</button>
      </div>
      <div className="flex gap-2">
        <input className={inputClass} placeholder="Instruction for the reply (optional)" aria-label="Reply instruction" value={instr} onChange={(e) => setInstr(e.target.value)} />
        <button className={btn()} disabled={Boolean(busy)} onClick={() => go('draft-reply', { message_id: last, instruction: instr })}>Draft reply</button>
      </div>
      {busy && <p className="text-xs text-muted">Working…</p>}
      {out?.error && <p role="alert" className="text-xs text-danger">{out.error}</p>}
      {out?.data && (out.data.status && out.data.status !== 'ok'
        ? <Notice tone="warn">{out.data.reason || out.data.status}</Notice>
        : (
          <div className="space-y-2 text-xs text-bright">
            {out.data.summary && <p className="whitespace-pre-wrap">{out.data.summary}</p>}
            {out.data.items && <ul className="list-disc ml-5">{out.data.items.map((i, k) => <li key={k}>{typeof i === 'string' ? i : i.text || JSON.stringify(i)}</li>)}</ul>}
            {out.data.action && <p>Suggested: <b>{out.data.action}</b> ({out.data.category}). {out.data.reason} Nothing was applied.</p>}
            {out.data.draft && <p>A draft was saved ({out.data.draft.subject}). <button className="underline" onClick={() => onReply({ id: last, to: (out.data.draft.to || []).join(', '), subject: out.data.draft.subject })}>Open as a reply</button> (review before sending).</p>}
            {out.data.warnings?.length > 0 && <Notice tone="warn">{out.data.warnings.join('; ')}</Notice>}
            {!out.data.summary && !out.data.items && !out.data.action && !out.data.draft && <Json value={out.data} />}
          </div>
        ))}
    </Card>
  );
};

const ThreadView = ({ mb, threadId, onReply, onChanged }) => {
  const f = useCallback(() => vc.get(`/mail/mailboxes/${mb}/threads/${threadId}`), [mb, threadId]);
  const q = useVelaris(f);
  const [err, setErr] = useState('');
  const download = async (m, a) => {
    try {
      const r = await vc.get(`/mail/mailboxes/${mb}/messages/${m.id}/attachments/${a.sha256}`, { responseType: 'blob' });
      const el = document.createElement('a');
      el.href = URL.createObjectURL(r.data); el.download = a.name; el.click(); URL.revokeObjectURL(el.href);
    } catch (e) { setErr(vError(e)); }
  };
  const mark = async (m, patch) => { try { await vc.patch(`/mail/mailboxes/${mb}/messages/${m.id}`, patch); onChanged(); q.reload(); } catch (e) { setErr(vError(e)); } };
  return (
    <LoadView q={q}>
      {(t) => (
        <div className="space-y-3">
          <h2 className="text-base font-bold text-bright">{t.subject || '(no subject)'}</h2>
          {err && <p role="alert" className="text-xs text-danger">{err}</p>}
          {t.messages.map((m) => (
            <article key={m.id} className="bg-panel border border-border rounded-xl p-4 space-y-2" aria-label={`Message from ${m.from}`}>
              <div className="flex flex-wrap justify-between text-xs text-muted gap-2">
                <span><b className="text-bright">{m.from_name || m.from}</b> &lt;{m.from}&gt; to {(m.to || []).join(', ')}</span>
                <span>{when(m.date || m.received)}</span>
              </div>
              <Banners m={m} />
              <Body m={m} />
              {(m.attachment_list || []).filter((a) => !a.inline).map((a) => (
                <button key={a.sha256} className="text-xs text-accent underline mr-3" onClick={() => download(m, a)}><Paperclip className="w-3 h-3 inline" /> {a.name}</button>
              ))}
              <div className="flex gap-2">
                <button className={btn('ghost')} onClick={() => onReply({ id: m.id, to: m.from, subject: m.subject, text: '' })}>Reply</button>
                <button className={btn('ghost')} onClick={() => mark(m, { flagged: !m.flagged })}>{m.flagged ? 'Unflag' : 'Flag'}</button>
                <button className={btn('ghost')} onClick={() => mark(m, { seen: !m.seen })}>{m.seen ? 'Mark unread' : 'Mark read'}</button>
              </div>
            </article>
          ))}
          <Assistant mb={mb} thread={threadId} last={t.messages.at(-1).id} onReply={onReply} />
        </div>
      )}
    </LoadView>
  );
};

export default ThreadView;
