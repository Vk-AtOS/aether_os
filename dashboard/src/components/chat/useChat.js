import { useCallback, useEffect, useRef, useState } from 'react';
import { vc, vError, vCode, isDown } from '../velaris/velarisApi';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// register -> long-poll loop. last_event_id is sent with every poll (it acknowledges what was processed, so a lost
// response loses nothing); a 410 bad_queue means the queue expired: register again for a fresh snapshot.
// Message-level events go to subscribers (the open channel); channel-level state lives here.
export const useChat = () => {
  const [state, setState] = useState({ status: 'connecting', error: '', me: null, channels: [], drafts: [], proposals: [], notices: [] });
  const listeners = useRef(new Set());
  const active = useRef(null);
  const subscribe = useCallback((fn) => { listeners.current.add(fn); return () => listeners.current.delete(fn); }, []);
  const setActive = useCallback((id) => { active.current = id; }, []);

  useEffect(() => {
    let alive = true;
    let qid = null;
    let last = -1;
    const ctl = new AbortController();

    const apply = (ev, me) => {
      listeners.current.forEach((fn) => fn(ev));
      setState((s) => {
        let channels = s.channels;
        const upd = (id, f) => { channels = channels.map((c) => (c.id === id ? f(c) : c)); };
        if (ev.type === 'channel') {
          const old = channels.find((c) => c.id === ev.channel.id);
          channels = old ? channels.map((c) => (c.id === old.id ? { ...old, ...ev.channel } : c))
            : [...channels, { unread: 0, last_read_id: 0, last_message_id: 0, role: 'member', ...ev.channel }];
        } else if (ev.type === 'member') {
          if (ev.op === 'remove' && ev.user_id === me) channels = channels.filter((c) => c.id !== ev.channel_id);
          else if (ev.op === 'remove') upd(ev.channel_id, (c) => ({ ...c, members: (c.members || []).filter((m) => m.id !== ev.user_id) }));
          else if (ev.op === 'add') upd(ev.channel_id, (c) => ((c.members || []).some((m) => m.id === ev.user_id) ? c : { ...c, members: [...(c.members || []), { id: ev.user_id, role: ev.role || 'member' }] }));
          else if (ev.op === 'role') upd(ev.channel_id, (c) => ({ ...c, members: (c.members || []).map((m) => (m.id === ev.user_id ? { ...m, role: ev.role } : m)) }));
        } else if (ev.type === 'message') {
          const own = ev.message.sender === me;
          upd(ev.channel_id, (c) => ({ ...c, last_message_id: ev.message.id,
            unread: own || active.current === ev.channel_id ? c.unread : c.unread + 1 }));
        } else if (ev.type === 'read') {
          upd(ev.channel_id, (c) => ({ ...c, unread: 0, last_read_id: ev.up_to }));
        } else if (ev.type === 'assistant_draft' && ev.op === 'new') {
          return { ...s, channels, drafts: [...s.drafts.filter((d) => d.draft_id !== ev.draft_id), { draft_id: ev.draft_id, channel_id: ev.channel_id, topic: ev.topic, body: ev.body, assistant: ev.assistant }] };
        } else if (ev.type === 'assistant_proposal') {
          const rest = s.proposals.filter((p) => p.run_id !== ev.run_id);
          if (ev.op === 'decided') return { ...s, channels, proposals: rest };
          if (ev.op === 'waiting') return { ...s, channels };
          return { ...s, channels, proposals: [...rest, { run_id: ev.run_id, channel_id: ev.channel_id, tool: ev.tool, args: ev.args, call_hash: ev.call_hash,
            requester: ev.requester, approvers: ev.approvers || [], requester_confirmed: ev.op !== 'confirm' }] };
        } else if (ev.type === 'assistant_notice') {
          return { ...s, channels, notices: [...s.notices.slice(-4), { id: `${ev.message_id}-${ev.code}`, channel_id: ev.channel_id, code: ev.code, assistant: ev.assistant }] };
        }
        return { ...s, channels };
      });
    };

    const loadAssist = async () => {
      const [d, p] = await Promise.allSettled([vc.get('/chat/assistant/drafts'), vc.get('/chat/assistant/proposals')]);
      setState((s) => ({ ...s, drafts: d.status === 'fulfilled' ? d.value.data.drafts || [] : [],
        proposals: p.status === 'fulfilled' ? p.value.data.proposals || [] : [] }));
    };

    const loop = async () => {
      let me = null;
      while (alive) {
        try {
          if (!qid) {
            const r = await vc.post('/chat/register', {}, { signal: ctl.signal });
            qid = r.data.queue_id; last = r.data.last_event_id; me = r.data.snapshot.user.id;
            if (!alive) return;
            setState((s) => ({ ...s, status: 'live', error: '', me: r.data.snapshot.user, channels: r.data.snapshot.channels }));
            loadAssist();
          }
          const r = await vc.get('/chat/events', { params: { queue_id: qid, last_event_id: last, timeout: 20 }, signal: ctl.signal, timeout: 45000 });
          if (!alive) return;
          for (const ev of r.data.events) { apply(ev, me); last = ev.id; }
        } catch (e) {
          if (!alive) return;
          if (e?.response?.status === 410 || vCode(e) === 'bad_queue') { qid = null; continue; }
          // 401/403 will not fix themselves: stop polling instead of retrying every 3 s forever.
          if (e?.response?.status === 401 || e?.response?.status === 403) {
            setState((s) => ({ ...s, status: 'down', error: vError(e) }));
            return;
          }
          setState((s) => ({ ...s, status: isDown(e) ? 'down' : 'retry', error: vError(e) }));
          await sleep(3000);
        }
      }
    };
    loop();
    return () => {
      alive = false;
      ctl.abort();
      if (qid) vc.delete(`/chat/queues/${qid}`).catch(() => {});
    };
  }, []);

  const patch = useCallback((fn) => setState(fn), []);
  return { ...state, subscribe, setActive, patch };
};
