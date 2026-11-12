import React, { useRef, useState } from 'react';
import { Paperclip, Send, X } from 'lucide-react';
import { vc, vError, btn } from '../velaris/velarisApi';
import { inputClass } from '../prime/parts';

// Composer: @mention suggestions from the channel's members, attachments (raw upload, then named by sha256),
// topic. onSend(payload) must resolve true when the message was accepted for sending.
const Composer = ({ members, topic, setTopic, replyTo, onCancelReply, onSend, disabled }) => {
  const [text, setText] = useState('');
  const [files, setFiles] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const at = /(?:^|\s)@([\w:.-]*)$/.exec(text);
  const suggestions = at ? [...members.map((m) => m.id), 'all'].filter((id) => id.toLowerCase().startsWith(at[1].toLowerCase())).slice(0, 6) : [];

  const attach = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    if (f.size > 10 * 1024 * 1024) { setError('Files may be at most 10 MiB.'); return; }
    setBusy(true); setError('');
    try {
      const r = await vc.post(`/chat/files?name=${encodeURIComponent(f.name)}&content_type=${encodeURIComponent(f.type || 'application/octet-stream')}`,
        f, { headers: { 'Content-Type': f.type || 'application/octet-stream' } });
      setFiles((x) => [...x, { hash: r.data.hash, name: r.data.name }]);
    } catch (err) { setError(vError(err, 'The upload failed.')); } finally { setBusy(false); }
  };

  const send = async (e) => {
    e.preventDefault();
    if (!text.trim() && files.length === 0) return;
    const ok = await onSend({ body: text.trim() || '(attachment)', attachments: files.map((f) => f.hash), names: files });
    if (ok) { setText(''); setFiles([]); setError(''); }
  };

  return (
    <form onSubmit={send} className="border-t border-border p-3 space-y-2" aria-label="Write a message">
      {replyTo && (
        <div className="flex items-center justify-between text-xs text-muted bg-surface rounded px-2 py-1">
          <span>Replying to {replyTo.sender}: {(replyTo.body || '').slice(0, 60)}</span>
          <button type="button" onClick={onCancelReply} aria-label="Cancel reply"><X className="w-3 h-3" /></button>
        </div>
      )}
      {files.length > 0 && <div className="flex gap-2 flex-wrap">{files.map((f) => (
        <span key={f.hash} className="text-[11px] bg-surface border border-border rounded px-2 py-0.5">{f.name}
          <button type="button" className="ml-1" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((x) => x !== f))}>×</button></span>))}</div>}
      {suggestions.length > 0 && (
        <div className="flex gap-1 flex-wrap" role="listbox" aria-label="Mention suggestions">
          {suggestions.map((id) => (
            <button key={id} type="button" role="option" aria-selected="false" className="text-[11px] border border-border rounded px-2 py-0.5 text-bright hover:border-accent"
              onClick={() => setText(text.replace(/@[\w:.-]*$/, `@${id} `))}>@{id}</button>
          ))}
        </div>
      )}
      <div className="flex gap-2 items-end">
        <input className={`${inputClass} w-28`} placeholder="topic" aria-label="Topic" value={topic} onChange={(e) => setTopic(e.target.value)} />
        <textarea rows={1} className={`${inputClass} flex-1 resize-none`} placeholder="Write a message. Type @ to mention." aria-label="Message"
          value={text} onChange={(e) => setText(e.target.value)} disabled={disabled}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) send(e); }} />
        <input ref={fileRef} type="file" className="hidden" onChange={attach} aria-label="Attach a file" />
        <button type="button" className={btn('ghost')} disabled={busy} onClick={() => fileRef.current?.click()} aria-label="Choose a file"><Paperclip className="w-3.5 h-3.5" /></button>
        <button type="submit" className={btn()} disabled={disabled || busy} aria-label="Send"><Send className="w-3.5 h-3.5" /></button>
      </div>
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
    </form>
  );
};

export default Composer;
