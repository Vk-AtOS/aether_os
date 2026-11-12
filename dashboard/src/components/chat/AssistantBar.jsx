import React, { useState } from 'react';
import { Bot, ShieldCheck } from 'lucide-react';
import { vc, vError, btn } from '../velaris/velarisApi';
import { Notice } from '../velaris/shared';
import { confirmAction } from '../confirmAction';
import { Json, inputClass } from '../prime/parts';

const NOTICE = {
  not_configured: 'The assistant is not set up on this Velaris (no model is configured), so it did not answer.',
  disabled: 'The assistant is switched off here (for this channel or for the organisation).',
  rate_limited: 'The assistant is rate limited right now; try again shortly.',
  denied: 'The assistant was not allowed to do that for you.',
};

// A private draft only the requester sees: nothing is posted until they confirm; confirming posts under their own name.
const DraftCard = ({ d, onDone, setErr }) => {
  const [body, setBody] = useState(d.body);
  const run = async (fn) => { try { await fn(); onDone(d.draft_id); } catch (e) { setErr(vError(e)); } };
  return (
    <div className="border border-accent/40 rounded-lg p-3 space-y-2 bg-surface">
      <p className="text-[11px] text-muted"><Bot className="w-3 h-3 inline mr-1" aria-hidden="true" />Private draft from {d.assistant}. Only you can see it. It posts under your name when you confirm.</p>
      <textarea className={inputClass} rows={3} value={body} onChange={(e) => setBody(e.target.value)} aria-label="Assistant draft" />
      <div className="flex gap-2">
        <button className={btn()} onClick={() => run(() => vc.post(`/chat/assistant/drafts/${d.draft_id}/confirm`, body !== d.body ? { body } : {}))}>Confirm and post</button>
        <button className={btn('ghost')} onClick={() => run(() => vc.post(`/chat/assistant/drafts/${d.draft_id}/discard`, {}))}>Discard</button>
      </div>
    </div>
  );
};

// Two keys: the requester confirms the exact call, then a different person approves it. Both see the arguments and hash.
const ProposalCard = ({ p, me, onChange, setErr }) => {
  const [note, setNote] = useState('');
  const mine = p.requester === me;
  const detail = `${p.tool}\ncall hash ${p.call_hash}\n${JSON.stringify(p.args)}`;
  const confirm = async () => {
    if (!(await confirmAction(`Confirm that the assistant may ask for this exact call?\n${detail}`, 'Confirm proposal'))) return;
    try { await vc.post(`/chat/assistant/proposals/${p.run_id}/confirm`, { call_hash: p.call_hash }); onChange(p.run_id, { requester_confirmed: true }); } catch (e) { setErr(vError(e)); }
  };
  const decide = async (approve) => {
    if (!(await confirmAction(`${approve ? 'Approve' : 'Reject'} this call? It is recorded under your name.\n${detail}`, approve ? 'Approve call' : 'Reject call'))) return;
    try { await vc.post(`/chat/assistant/proposals/${p.run_id}/decide`, { call_hash: p.call_hash, approve, note }); onChange(p.run_id, null); } catch (e) { setErr(vError(e)); }
  };
  return (
    <div className="border border-warning/40 rounded-lg p-3 space-y-2 bg-surface">
      <p className="text-xs font-bold text-bright"><ShieldCheck className="w-3.5 h-3.5 inline mr-1 text-warning" aria-hidden="true" />The assistant proposes: {p.tool}</p>
      <Json value={p.args} />
      <p className="text-[10px] font-mono text-muted break-all">call hash {p.call_hash}</p>
      {mine && !p.requester_confirmed && <button className={btn()} onClick={confirm}>Confirm</button>}
      {mine && p.requester_confirmed && <p className="text-xs text-muted">Confirmed. Waiting for a second person to approve; you cannot approve your own request.</p>}
      {!mine && p.requester_confirmed && (
        <div className="space-y-2">
          <input className={inputClass} placeholder="Note (optional)" aria-label="Decision note" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="flex gap-2"><button className={btn()} onClick={() => decide(true)}>Approve</button><button className={btn('danger')} onClick={() => decide(false)}>Reject</button></div>
        </div>
      )}
    </div>
  );
};

const AssistantBar = ({ chat, channelId, me }) => {
  const [err, setErr] = useState('');
  const drafts = chat.drafts.filter((d) => d.channel_id === channelId);
  const props = chat.proposals.filter((p) => p.channel_id === channelId);
  const notices = chat.notices.filter((n) => n.channel_id === channelId);
  if (!drafts.length && !props.length && !notices.length && !err) return null;
  return (
    <div className="space-y-2 mb-2" aria-label="Assistant">
      {notices.map((n) => <Notice key={n.id} tone="warn">{NOTICE[n.code] || `The assistant could not help (${String(n.code).replace(/_/g, ' ')}).`}</Notice>)}
      {err && <p role="alert" className="text-xs text-danger">{err}</p>}
      {drafts.map((d) => <DraftCard key={d.draft_id} d={d} setErr={setErr} onDone={(id) => chat.patch((s) => ({ ...s, drafts: s.drafts.filter((x) => x.draft_id !== id) }))} />)}
      {props.map((p) => <ProposalCard key={p.run_id} p={p} me={me} setErr={setErr}
        onChange={(id, change) => chat.patch((s) => ({ ...s, proposals: change ? s.proposals.map((x) => (x.run_id === id ? { ...x, ...change } : x)) : s.proposals.filter((x) => x.run_id !== id) }))} />)}
    </div>
  );
};

export default AssistantBar;
