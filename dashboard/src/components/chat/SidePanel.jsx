import React, { useCallback, useState } from 'react';
import { Pin, Search, UserPlus, X } from 'lucide-react';
import { vc, vError, useVelaris, when, btn } from '../velaris/velarisApi';
import { LoadView, Tabs } from '../velaris/shared';
import { confirmAction } from '../confirmAction';
import { inputClass } from '../prime/parts';

const Members = ({ channel, me }) => {
  const [id, setId] = useState('');
  const [msg, setMsg] = useState('');
  const act = async (fn) => { try { await fn(); setMsg(''); } catch (e) { setMsg(vError(e)); } };
  const mine = (channel.members || []).find((m) => m.id === me)?.role;
  const admin = ['owner', 'admin'].includes(mine);
  return (
    <div className="space-y-3">
      <ul className="space-y-1">
        {(channel.members || []).map((m) => (
          <li key={m.id} className="flex items-center gap-2 text-xs">
            <span className="text-bright truncate flex-1" title={m.id}>{m.id === me ? `${m.id} (you)` : m.id}</span>
            <span className="text-muted">{m.role}</span>
            {admin && m.id !== me && (
              <button aria-label={`Remove ${m.id}`} onClick={async () => { if (await confirmAction(`Remove ${m.id} from this channel?`, 'Remove member')) act(() => vc.delete(`/chat/channels/${channel.id}/members/${encodeURIComponent(m.id)}`)); }}><X className="w-3 h-3 text-danger" /></button>
            )}
          </li>
        ))}
      </ul>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (id.trim()) act(async () => { await vc.post(`/chat/channels/${channel.id}/members`, { user_id: id.trim() }); setId(''); }); }}>
        <input className={inputClass} placeholder="User id to invite" aria-label="User id to invite" value={id} onChange={(e) => setId(e.target.value)} />
        <button className={btn()} aria-label="Invite"><UserPlus className="w-3 h-3" /></button>
      </form>
      <button className={btn('ghost')} onClick={() => act(() => vc.post(`/chat/channels/${channel.id}/members`, { user_id: 'assistant:velaris' }))}>Add the assistant</button>
      <label className="flex items-center gap-2 text-xs text-bright">
        <input type="checkbox" checked={channel.ai_enabled} disabled={!admin}
          onChange={(e) => act(() => vc.patch(`/chat/channels/${channel.id}`, { ai_enabled: e.target.checked }))} />
        Assistant allowed in this channel
      </label>
      {msg && <p role="alert" className="text-xs text-danger">{msg}</p>}
    </div>
  );
};

const Pins = ({ channel }) => {
  const f = useCallback(() => vc.get(`/chat/channels/${channel.id}/pins`), [channel.id]);
  const q = useVelaris(f);
  return (
    <LoadView q={q} isEmpty={(d) => d.messages.length === 0} emptyText="Nothing is pinned.">
      {(d) => <ul className="space-y-2">{d.messages.map((m) => (
        <li key={m.id} className="text-xs"><Pin className="w-3 h-3 inline text-warning mr-1" aria-hidden="true" /><b>{m.sender}</b> {when(m.created_at)}<p className="text-bright">{m.body}</p></li>
      ))}</ul>}
    </LoadView>
  );
};

const SearchTab = ({ channel }) => {
  const [text, setText] = useState('');
  const [scope, setScope] = useState(true);
  const [state, setState] = useState({ rows: null, error: '', busy: false });
  const go = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    setState({ rows: null, error: '', busy: true });
    try {
      const r = await vc.get('/chat/search', { params: { q: text.trim(), ...(scope ? { channel_id: channel.id } : {}) } });
      setState({ rows: r.data.messages, error: '', busy: false });
    } catch (err) { setState({ rows: null, error: vError(err), busy: false }); }
  };
  return (
    <div className="space-y-3">
      <form onSubmit={go} className="flex gap-2">
        <input className={inputClass} placeholder="Search messages" aria-label="Search messages" value={text} onChange={(e) => setText(e.target.value)} />
        <button className={btn()} aria-label="Search" disabled={state.busy}><Search className="w-3 h-3" /></button>
      </form>
      <label className="flex gap-2 text-xs text-muted"><input type="checkbox" checked={scope} onChange={(e) => setScope(e.target.checked)} />This channel only</label>
      {state.error && <p role="alert" className="text-xs text-danger">{state.error}</p>}
      {state.rows && state.rows.length === 0 && <p className="text-xs text-muted">No messages matched.</p>}
      {state.rows && <ul className="space-y-2">{state.rows.map((m) => <li key={m.id} className="text-xs"><b>{m.sender}</b> {when(m.created_at)}<p className="text-bright">{m.body}</p></li>)}</ul>}
    </div>
  );
};

const SidePanel = ({ channel, me, onClose }) => {
  const [tab, setTab] = useState('members');
  return (
    <aside className="w-72 shrink-0 bg-panel border border-border rounded-xl p-3 space-y-3 overflow-y-auto" aria-label="Channel details">
      <div className="flex justify-between items-center">
        <Tabs tabs={[['members', 'Members'], ['pins', 'Pins'], ['search', 'Search']]} value={tab} onChange={setTab} />
        <button onClick={onClose} aria-label="Close panel"><X className="w-3.5 h-3.5 text-muted" /></button>
      </div>
      {tab === 'members' && <Members channel={channel} me={me} />}
      {tab === 'pins' && <Pins channel={channel} />}
      {tab === 'search' && <SearchTab channel={channel} />}
    </aside>
  );
};

export default SidePanel;
