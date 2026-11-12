import React, { useCallback, useState } from 'react';
import { Paperclip, Flag } from 'lucide-react';
import { vc, useVelaris, when, btn } from '../velaris/velarisApi';
import { LoadView } from '../velaris/shared';
import { inputClass } from '../prime/parts';

const PAGE = 30;

const MessageList = ({ mb, folder, onOpen, activeThread, version }) => {
  const [q, setQ] = useState('');
  const [applied, setApplied] = useState('');
  const [unread, setUnread] = useState(false);
  const [flagged, setFlagged] = useState(false);
  const [offset, setOffset] = useState(0);
  const f = useCallback(() => vc.get(`/mail/mailboxes/${mb}/messages`, { params: { folder, q: applied || undefined,
    unread: unread || undefined, flagged: flagged || undefined, limit: PAGE, offset, v: version } }), [mb, folder, applied, unread, flagged, offset, version]);
  const res = useVelaris(f);
  const reset = (fn) => { fn(); setOffset(0); };
  return (
    <div className="space-y-2">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); reset(() => setApplied(q.trim())); }}>
        <input type="search" className={inputClass} placeholder="Search mail" aria-label="Search mail" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className={btn()}>Search</button>
      </form>
      <div className="flex gap-3 text-xs text-muted">
        <label><input type="checkbox" checked={unread} onChange={(e) => reset(() => setUnread(e.target.checked))} /> Unread</label>
        <label><input type="checkbox" checked={flagged} onChange={(e) => reset(() => setFlagged(e.target.checked))} /> Flagged</label>
      </div>
      <LoadView q={res} isEmpty={(d) => d.messages.length === 0} emptyText="No messages here.">
        {(d) => (
          <>
            <ul className="divide-y divide-border border border-border rounded-xl overflow-hidden bg-panel">
              {d.messages.map((m) => (
                <li key={m.id}>
                  <button onClick={() => onOpen(m)} aria-current={activeThread === m.thread_id ? 'true' : undefined}
                    className={`w-full text-left px-3 py-2 hover:bg-surface/60 ${activeThread === m.thread_id ? 'bg-accent/10' : ''}`}>
                    <div className="flex items-center gap-2 text-xs">
                      <span className={`truncate flex-1 ${m.seen ? 'text-muted' : 'text-bright font-bold'}`}>{m.from_name || m.from}</span>
                      {m.flagged && <Flag className="w-3 h-3 text-warning" aria-label="Flagged" />}
                      {m.attachments > 0 && <Paperclip className="w-3 h-3 text-muted" aria-label="Has attachments" />}
                      <span className="text-muted shrink-0">{when(m.date || m.received)}</span>
                    </div>
                    <p className={`text-xs truncate ${m.seen ? 'text-muted' : 'text-bright'}`}>{m.subject || '(no subject)'}</p>
                    <p className="text-[11px] text-muted truncate">{m.snippet}</p>
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex justify-between items-center text-xs text-muted">
              <span>{d.offset + 1}-{d.offset + d.messages.length} of {d.total}</span>
              <span className="flex gap-2">
                <button className={btn('ghost')} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Newer</button>
                <button className={btn('ghost')} disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)}>Older</button>
              </span>
            </div>
          </>
        )}
      </LoadView>
    </div>
  );
};

export default MessageList;
