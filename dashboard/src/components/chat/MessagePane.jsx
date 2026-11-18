import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Users } from 'lucide-react';
import { vc, vError, btn } from '../velaris/velarisApi';
import { confirmAction } from '../confirmAction';
import { useRole } from '../../hooks/useRole';
import { Spinner, ErrorBox } from '../prime/parts';
import MessageItem from './MessageItem';
import Composer from './Composer';

const PAGE = 50;
const byId = (a, b) => (typeof a.id === 'number' && typeof b.id === 'number' ? a.id - b.id : 0);

// Messages of one channel (or one thread). Only the newest PAGE are in the page at first; "Load earlier" adds
// older ones, so a long channel never puts thousands of nodes on screen at once.
const MessagePane = ({ channel, me, chat, onSide, topics }) => {
  const { isAdmin } = useRole();                // organisation owner/admin: the compliance erase button (the gateway checks too)
  const [msgs, setMsgs] = useState({ key: null, list: [], more: false, error: '' });
  const [topic, setTopic] = useState('');
  const [filter, setFilter] = useState('');
  const [thread, setThread] = useState(null);
  const [pins, setPins] = useState([]);
  const [notice, setNotice] = useState('');
  const endRef = useRef(null);
  const cid = channel.id;
  const key = `${cid}|${filter}|${thread?.id || ''}`;
  const ready = msgs.key === key;
  const params = useCallback((extra = {}) => ({ limit: PAGE, ...(filter ? { topic: filter } : {}), ...(thread ? { thread: thread.id } : {}), ...extra }), [filter, thread]);

  useEffect(() => {
    let alive = true;
    vc.get(`/chat/channels/${cid}/messages`, { params: params() })
      .then((r) => { if (alive) setMsgs({ key, list: r.data.messages, more: r.data.has_more, error: '' }); })
      .catch((e) => { if (alive) setMsgs({ key, list: [], more: false, error: vError(e, 'Messages could not be loaded.') }); });
    vc.get(`/chat/channels/${cid}/pins`).then((r) => { if (alive) setPins(r.data.messages.map((m) => m.id)); }).catch(() => {});
    return () => { alive = false; };
  }, [cid, key, params]);

  const lastId = msgs.list.filter((m) => typeof m.id === 'number').at(-1)?.id;
  useEffect(() => {
    if (!ready) return;
    endRef.current?.scrollIntoView?.({ block: 'end' });
    if (lastId) vc.post(`/chat/channels/${cid}/read`, { up_to: lastId }).catch(() => {});
  }, [lastId, cid, ready]);

  useEffect(() => chat.subscribe((ev) => {
    if (ev.channel_id !== cid) return;
    setMsgs((s) => {
      if (s.key !== key) return s;
      const l = s.list;
      if (ev.type === 'message') {
        const m = ev.message;
        if (filter && m.topic !== filter) return s;
        if (thread && m.thread_root !== thread.id && m.id !== thread.id) return s;
        if (l.some((x) => x.id === m.id)) return s;
        const i = l.findIndex((x) => x.pending && x.local_id && x.local_id === m.local_id);   // the echo of our own send
        return { ...s, list: i >= 0 ? l.map((x, j) => (j === i ? m : x)) : [...l, m].sort(byId) };
      }
      if (ev.type === 'message_edit') return { ...s, list: l.map((x) => (x.id === ev.message.id ? ev.message : x)) };
      if (ev.type === 'message_delete') return { ...s, list: l.map((x) => (x.id === ev.message_id ? { ...x, deleted: true, body: null, attachments: [] } : x)) };
      if (ev.type === 'reaction') {
        return { ...s, list: l.map((x) => {
          if (x.id !== ev.message_id) return x;
          const cur = new Set(x.reactions?.[ev.emoji] || []);
          if (ev.op === 'add') cur.add(ev.user_id); else cur.delete(ev.user_id);
          return { ...x, reactions: { ...x.reactions, [ev.emoji]: [...cur] } };
        }) };
      }
      return s;
    });
    if (ev.type === 'pin') setPins((p) => (ev.op === 'add' ? [...new Set([...p, ev.message_id])] : p.filter((x) => x !== ev.message_id)));
  }), [chat, cid, key, filter, thread]);

  const loadEarlier = async () => {
    const first = msgs.list.find((m) => typeof m.id === 'number');
    try {
      const r = await vc.get(`/chat/channels/${cid}/messages`, { params: params({ before: first.id }) });
      setMsgs((s) => ({ ...s, list: [...r.data.messages, ...s.list], more: r.data.has_more }));
    } catch (e) { setNotice(vError(e)); }
  };

  const post = async (payload, localId) => {
    const lid = localId || (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`);
    const body = { body: payload.body, local_id: lid, ...(topic ? { topic } : {}), ...(thread ? { reply_to: thread.id } : {}),
      ...(payload.attachments.length ? { attachments: payload.attachments } : {}) };
    const temp = { id: `local-${lid}`, local_id: lid, sender: me, body: payload.body, created_at: Date.now() / 1000, pending: true,
      reactions: {}, attachments: payload.attachments, topic: topic || null, _payload: payload };
    setMsgs((s) => ({ ...s, list: [...s.list.filter((x) => x.local_id !== lid), temp] }));
    try {
      const r = await vc.post(`/chat/channels/${cid}/messages`, body);
      setMsgs((s) => ({ ...s, list: s.list.some((x) => x.id === r.data.message.id)
        ? s.list.filter((x) => x.local_id !== lid || x.id === r.data.message.id)
        : s.list.map((x) => (x.local_id === lid && x.pending ? r.data.message : x)) }));
      return true;
    } catch (e) {
      setMsgs((s) => ({ ...s, list: s.list.map((x) => (x.local_id === lid ? { ...x, pending: false, failed: true } : x)) }));
      setNotice(vError(e, 'The message was not sent.'));
      return true;     // it stays in the list marked "not sent" with a retry; do not lose the text
    }
  };

  const act = async (fn) => { try { await fn(); setNotice(''); return true; } catch (e) { setNotice(vError(e)); return false; } };
  const onReact = (m, e, had) => act(() => (had ? vc.delete(`/chat/messages/${m.id}/reactions/${encodeURIComponent(e)}`) : vc.put(`/chat/messages/${m.id}/reactions/${encodeURIComponent(e)}`, {})));
  const onEdit = (m, body) => act(async () => { const r = await vc.patch(`/chat/messages/${m.id}`, { body }); setMsgs((s) => ({ ...s, list: s.list.map((x) => (x.id === m.id ? r.data.message : x)) })); });
  // Compliance erase (KAN-129): removes the content for good (a channel on legal hold keeps it; Velaris says so). Org
  // admins only; the typed word travels as `confirm` and the gateway refuses the call without it and ledgers it.
  // An author who is not an admin deletes their own message instead (Velaris allows erase for admins only).
  const onErase = (m, word) => act(() => vc.post(`/chat/admin/messages/${m.id}/erase`, { confirm: word }));
  const onDelete = async (m) => { if (await confirmAction('Delete this message for everyone in the channel?', 'Delete message')) act(() => vc.delete(`/chat/messages/${m.id}`)); };
  const onPin = (m, pinned) => act(() => (pinned ? vc.delete(`/chat/messages/${m.id}/pin`) : vc.put(`/chat/messages/${m.id}/pin`, {})));
  const onDownload = (h) => act(async () => {
    const r = await vc.get(`/chat/files/${h}`, { responseType: 'blob' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(r.data);
    a.download = `${h.slice(0, 10)}`;
    a.click();
    URL.revokeObjectURL(a.href);
  });

  const canAdmin = ['owner', 'admin'].includes(channel.role);
  return (
    <section className="flex-1 flex flex-col min-w-0 bg-panel border border-border rounded-xl overflow-hidden" aria-label={`Channel ${channel.name || channel.id}`}>
      <header className="flex items-center gap-2 px-4 py-2 border-b border-border">
        {thread && <button className={btn('ghost')} onClick={() => setThread(null)} aria-label="Back to channel"><ArrowLeft className="w-3 h-3" /></button>}
        <h2 className="text-sm font-bold text-bright truncate">{channel.name || `${channel.kind} chat`}{thread ? ' · thread' : ''}</h2>
        <select aria-label="Topic filter" className="bg-surface border border-border rounded text-xs text-bright px-1 py-1 ml-auto" value={filter} onChange={(e) => { setFilter(e.target.value); setThread(null); }}>
          <option value="">All topics</option>
          {topics.map((t) => <option key={t.topic ?? ''} value={t.topic ?? ''}>{t.topic || '(none)'} · {t.messages}</option>)}
        </select>
        <button className={btn('ghost')} onClick={onSide} aria-label="Members, pins and search"><Users className="w-3 h-3" /></button>
      </header>
      {notice && <div role="alert" className="px-4 py-1 text-xs text-danger border-b border-border">{notice}</div>}
      <div className="flex-1 overflow-y-auto py-2 min-h-[16rem]" aria-live="polite">
        {!ready ? <Spinner /> : msgs.error ? <div className="p-4"><ErrorBox>{msgs.error}</ErrorBox></div> : (
          <>
            {msgs.more && <div className="text-center py-1"><button className={btn('ghost')} onClick={loadEarlier}>Load earlier messages</button></div>}
            {msgs.list.length === 0 && <p className="text-sm text-muted text-center py-10">No messages yet. Say something.</p>}
            {msgs.list.map((m) => (
              <div key={m.id}>
                <MessageItem m={m} me={me} pinned={pins.includes(m.id)} canAdmin={canAdmin} canErase={isAdmin} onReact={onReact} onEdit={onEdit} onDelete={onDelete} onErase={onErase}
                  onPin={onPin} onThread={setThread} onDownload={onDownload} onTopic={setFilter} />
                {m.failed && <button className={`${btn('ghost')} ml-3`} onClick={() => post(m._payload, m.local_id)}>Retry send</button>}
              </div>
            ))}
            <div ref={endRef} />
          </>
        )}
      </div>
      <Composer members={channel.members || []} topic={topic} setTopic={setTopic} replyTo={thread} onCancelReply={() => setThread(null)} onSend={(p) => post(p)} disabled={channel.archived} />
    </section>
  );
};

export default MessagePane;
