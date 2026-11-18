import React, { useState } from 'react';
import { Paperclip, Pin, MessageSquare, Pencil, Trash2, Smile, Bot, ShieldX } from 'lucide-react';
import { when, btn } from '../velaris/velarisApi';
import { inputClass } from '../prime/parts';

const EMOJI = ['👍', '❤️', '😄', '🎉', '👀'];

const Reactions = ({ message, me, onReact }) => (
  <div className="flex flex-wrap gap-1 mt-1">
    {Object.entries(message.reactions || {}).filter(([, u]) => u.length).map(([e, users]) => (
      <button key={e} onClick={() => onReact(message, e, users.includes(me))} aria-label={`${e} ${users.length}`}
        className={`px-1.5 py-0.5 rounded-full text-[11px] border ${users.includes(me) ? 'border-accent bg-accent/10 text-bright' : 'border-border text-muted'}`}>
        {e} {users.length}
      </button>
    ))}
  </div>
);

const MessageItem = ({ m, me, pinned, canAdmin, canErase, onReact, onEdit, onDelete, onErase, onPin, onThread, onDownload, onTopic }) => {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.body || '');
  const [picker, setPicker] = useState(false);
  const [erasing, setErasing] = useState(false);
  const [word, setWord] = useState('');
  if (m.deleted) {
    return <div className="text-xs text-muted italic px-3 py-1">Message {m.erased ? 'erased' : 'deleted'}</div>;
  }
  const mine = m.sender === me;
  const save = async () => { if (text.trim() && await onEdit(m, text.trim())) setEditing(false); };
  return (
    <div className={`group px-3 py-2 rounded-lg hover:bg-surface/60 ${m.pending ? 'opacity-60' : ''}`} data-testid="chat-message">
      <div className="flex items-baseline gap-2 text-[11px] text-muted">
        <span className="font-bold text-bright truncate max-w-[12rem]" title={m.sender}>{mine ? 'You' : m.sender}</span>
        <span>{m.pending ? 'sending…' : when(m.created_at)}</span>
        {m.edited_at && <span>(edited)</span>}
        {m.ai_assisted && <span className="inline-flex items-center gap-0.5"><Bot className="w-3 h-3" aria-hidden="true" />assistant</span>}
        {m.topic && <button className="underline" onClick={() => onTopic(m.topic)}>#{m.topic}</button>}
        {pinned && <Pin className="w-3 h-3 text-warning" aria-label="Pinned" />}
        {m.failed && <span className="text-danger">not sent</span>}
      </div>
      {editing ? (
        <div className="flex gap-2 mt-1">
          <input className="flex-1 bg-surface border border-border rounded px-2 py-1 text-sm text-bright" value={text} onChange={(e) => setText(e.target.value)} aria-label="Edit message" />
          <button className={btn()} onClick={save}>Save</button>
          <button className={btn('ghost')} onClick={() => setEditing(false)}>Cancel</button>
        </div>
      ) : <p className="text-sm text-bright whitespace-pre-wrap break-words">{m.body}</p>}
      {(m.attachments || []).length > 0 && (
        <div className="flex flex-wrap gap-2 mt-1">
          {m.attachments.map((h) => (
            <button key={h} onClick={() => onDownload(h)} className="inline-flex items-center gap-1 text-xs text-accent underline">
              <Paperclip className="w-3 h-3" aria-hidden="true" />{h.slice(0, 10)}
            </button>
          ))}
        </div>
      )}
      <Reactions message={m} me={me} onReact={onReact} />
      {!m.pending && (
        <div className="hidden group-hover:flex group-focus-within:flex gap-2 mt-1 text-muted">
          <button aria-label="Add reaction" onClick={() => setPicker(!picker)}><Smile className="w-3.5 h-3.5" /></button>
          <button aria-label="Reply in thread" onClick={() => onThread(m)}><MessageSquare className="w-3.5 h-3.5" /></button>
          <button aria-label={pinned ? 'Unpin' : 'Pin'} onClick={() => onPin(m, pinned)}><Pin className="w-3.5 h-3.5" /></button>
          {mine && <button aria-label="Edit message" onClick={() => setEditing(true)}><Pencil className="w-3.5 h-3.5" /></button>}
          {(mine || canAdmin) && <button aria-label="Delete message" onClick={() => onDelete(m)}><Trash2 className="w-3.5 h-3.5" /></button>}
          {canErase && <button aria-label="Erase message (compliance)" onClick={() => setErasing(true)}><ShieldX className="w-3.5 h-3.5 text-danger" /></button>}
        </div>
      )}
      {erasing && (
        <form className="mt-2 flex flex-wrap items-center gap-2 border border-danger/40 rounded p-2" aria-label="Erase this message"
          onSubmit={async (e) => { e.preventDefault(); if (await onErase(m, word)) { setErasing(false); setWord(''); } }}>
          <span className="text-xs text-muted">Erasing removes the text for good (a channel on legal hold keeps it). It is recorded in the audit log. Type <b className="text-bright">ERASE</b> to continue.</span>
          <input aria-label="Type ERASE" className={`${inputClass} max-w-[8rem]`} value={word} onChange={(e) => setWord(e.target.value)} autoFocus />
          <button type="submit" className={btn('danger')} disabled={word !== 'ERASE'}>Erase permanently</button>
          <button type="button" className={btn('ghost')} onClick={() => { setErasing(false); setWord(''); }}>Cancel</button>
        </form>
      )}
      {picker && (
        <div className="flex gap-1 mt-1">
          {EMOJI.map((e) => <button key={e} onClick={() => { onReact(m, e, false); setPicker(false); }} className="text-base">{e}</button>)}
        </div>
      )}
    </div>
  );
};

export default MessageItem;
