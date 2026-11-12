import React, { useCallback, useState } from 'react';
import { Hash, Lock, User, Users, Plus } from 'lucide-react';
import { vc, vError, useVelaris, btn } from '../velaris/velarisApi';
import { inputClass } from '../prime/parts';

const ICON = { public: Hash, private: Lock, direct: User, group: Users };

const Create = ({ onDone }) => {
  const [kind, setKind] = useState('public');
  const [name, setName] = useState('');
  const [members, setMembers] = useState('');
  const [err, setErr] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    try {
      const r = await vc.post('/chat/channels', { kind, ...(name ? { name } : {}), members: members.split(/[\s,]+/).filter(Boolean) });
      onDone(r.data.id ?? r.data.channel?.id);
    } catch (x) { setErr(vError(x)); }
  };
  return (
    <form onSubmit={submit} className="space-y-2 p-2 border border-border rounded-lg">
      <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">
        {Object.keys(ICON).map((k) => <option key={k}>{k}</option>)}
      </select>
      {(kind === 'public' || kind === 'private' || kind === 'group') && <input className={inputClass} placeholder="Name" aria-label="Channel name" value={name} onChange={(e) => setName(e.target.value)} />}
      <input className={inputClass} placeholder="Member user ids" aria-label="Member user ids" value={members} onChange={(e) => setMembers(e.target.value)} />
      {err && <p role="alert" className="text-xs text-danger">{err}</p>}
      <button className={btn()}>Create</button>
    </form>
  );
};

const Directory = ({ joined, onJoin }) => {
  const f = useCallback(() => vc.get('/chat/channels/public'), []);
  const q = useVelaris(f);
  const rows = (q.data?.channels || []).filter((c) => !joined.some((j) => j.id === c.id));
  if (q.loading || q.error || rows.length === 0) return null;
  return (
    <div className="pt-2">
      <p className="px-2 text-[10px] font-bold text-muted uppercase tracking-wider">Public channels</p>
      {rows.map((c) => <button key={c.id} className="w-full text-left px-2 py-1 text-xs text-muted hover:text-bright" onClick={() => onJoin(c.id)}># {c.name} · join</button>)}
    </div>
  );
};

const ChannelList = ({ channels, activeId, onPick, me }) => {
  const [creating, setCreating] = useState(false);
  const label = (c) => c.name || (c.members || []).filter((m) => m.id !== me).map((m) => m.id).join(', ') || `${c.kind} ${c.id}`;
  const join = async (id) => { try { await vc.post(`/chat/channels/${id}/join`, {}); onPick(id); } catch { /* the channel event or a refresh shows the result */ } };
  return (
    <nav className="w-56 shrink-0 bg-panel border border-border rounded-xl p-2 space-y-1 overflow-y-auto" aria-label="Channels">
      <div className="flex items-center justify-between px-2 py-1">
        <span className="text-[10px] font-bold text-muted uppercase tracking-wider">Channels</span>
        <button aria-label="New channel" onClick={() => setCreating(!creating)}><Plus className="w-3.5 h-3.5 text-muted" /></button>
      </div>
      {creating && <Create onDone={(id) => { setCreating(false); if (id) onPick(id); }} />}
      {channels.length === 0 && <p className="text-xs text-muted px-2 py-3">No channels yet. Create one or join a public channel.</p>}
      {channels.filter((c) => !c.archived).map((c) => {
        const I = ICON[c.kind] || Hash;
        return (
          <button key={c.id} onClick={() => onPick(c.id)} aria-current={c.id === activeId ? 'true' : undefined}
            className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs ${c.id === activeId ? 'bg-accent/15 text-bright' : 'text-muted hover:text-bright hover:bg-surface'}`}>
            <I className="w-3 h-3 shrink-0" aria-hidden="true" />
            <span className="truncate flex-1 text-left">{label(c)}</span>
            {c.legal_hold && <Lock className="w-3 h-3 text-warning" aria-label="Legal hold" />}
            {c.unread > 0 && <span className="bg-accent text-white rounded-full px-1.5 text-[10px] font-bold" aria-label={`${c.unread} unread`}>{c.unread}</span>}
          </button>
        );
      })}
      <Directory joined={channels} onJoin={join} />
    </nav>
  );
};

export default ChannelList;
