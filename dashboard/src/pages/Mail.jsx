import React, { useCallback, useState } from 'react';
import { Mail as MailIcon, PenSquare, Inbox, Settings2, Filter, ShieldCheck } from 'lucide-react';
import { vc, useVelaris, btn } from '../components/velaris/velarisApi';
import { LoadView, PageHead } from '../components/velaris/shared';
import MessageList from '../components/mail/MessageList';
import ThreadView from '../components/mail/ThreadView';
import Compose from '../components/mail/Compose';
import Approvals from '../components/mail/Approvals';
import Rules from '../components/mail/Rules';
import MailSettings from '../components/mail/MailSettings';

const Folders = ({ mb, folder, onPick, version }) => {
  const f = useCallback(() => vc.get(`/mail/mailboxes/${mb}/folders`, { params: { v: version } }), [mb, version]);
  const q = useVelaris(f);
  return (
    <LoadView q={q} isEmpty={(d) => d.folders.length === 0}>
      {(d) => d.folders.map((x) => (
        <button key={x.id} onClick={() => onPick(x.name)} aria-current={folder.toLowerCase() === x.name.toLowerCase() ? 'true' : undefined}
          className={`w-full flex justify-between px-2 py-1.5 rounded-lg text-xs ${folder.toLowerCase() === x.name.toLowerCase() ? 'bg-accent/15 text-bright' : 'text-muted hover:text-bright hover:bg-surface'}`}>
          <span className="capitalize">{x.name}</span>{x.unread > 0 && <span className="text-accent font-bold">{x.unread}</span>}
        </button>
      ))}
    </LoadView>
  );
};

const Mailbox = ({ mb }) => {
  const [view, setView] = useState('mail');
  const [folder, setFolder] = useState('inbox');
  const [thread, setThread] = useState(null);
  const [compose, setCompose] = useState(null);
  const [version, setVersion] = useState(0);
  const bump = () => setVersion((v) => v + 1);
  const nav = (id, label, Icon) => (
    <button key={id} onClick={() => { setView(id); setCompose(null); }} aria-current={view === id ? 'true' : undefined}
      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs ${view === id ? 'bg-accent/15 text-bright' : 'text-muted hover:text-bright hover:bg-surface'}`}>
      <Icon className="w-3 h-3" aria-hidden="true" />{label}
    </button>
  );
  return (
    <div className="flex gap-3 min-h-[28rem]">
      <nav className="w-48 shrink-0 space-y-1" aria-label="Mailbox">
        <button className={`${btn()} w-full`} onClick={() => { setView('mail'); setCompose({}); }}><PenSquare className="w-3 h-3 inline mr-1" />Compose</button>
        <div className="pt-2">{nav('mail', 'Mail', Inbox)}</div>
        {view === 'mail' && <div className="pl-2"><Folders mb={mb} folder={folder} onPick={(n) => { setFolder(n); setThread(null); }} version={version} /></div>}
        {nav('approvals', 'Approvals', ShieldCheck)}
        {nav('rules', 'Rules', Filter)}
        {nav('settings', 'Settings and domains', Settings2)}
      </nav>
      <div className="flex-1 min-w-0">
        {view === 'mail' && (compose ? <Compose key={compose.id || 'new'} mb={mb} reply={compose.id ? compose : null} onClose={() => { setCompose(null); bump(); }} /> : (
          <div className="grid grid-cols-1 lg:grid-cols-[22rem_1fr] gap-3">
            <MessageList mb={mb} folder={folder} onOpen={(m) => setThread(m.thread_id)} activeThread={thread} version={version} />
            {thread ? <ThreadView key={thread} mb={mb} threadId={thread} onReply={setCompose} onChanged={bump} /> : <p className="text-sm text-muted p-6">Choose a message to read it.</p>}
          </div>
        ))}
        {view === 'approvals' && <Approvals />}
        {view === 'rules' && <Rules mb={mb} />}
        {view === 'settings' && <MailSettings mb={mb} />}
      </div>
    </div>
  );
};

const Mail = () => {
  const f = useCallback(() => vc.get('/mail/mailboxes'), []);
  const q = useVelaris(f);
  const [picked, setPicked] = useState(null);
  return (
    <div className="space-y-4">
      <PageHead icon={MailIcon} title="Mail" sub="Your mailboxes through Velaris" />
      <LoadView q={q} isEmpty={(d) => d.mailboxes.length === 0} emptyText="You have no mailbox in Velaris yet. A mail administrator can create one for you.">
        {(d) => {
          const mb = picked || d.mailboxes[0].id;
          return (
            <>
              {d.mailboxes.length > 1 && (
                <select aria-label="Mailbox" className="bg-surface border border-border rounded px-2 py-1 text-xs text-bright" value={mb} onChange={(e) => setPicked(e.target.value)}>
                  {d.mailboxes.map((m) => <option key={m.id} value={m.id}>{m.address}</option>)}
                </select>
              )}
              <Mailbox key={mb} mb={mb} />
            </>
          );
        }}
      </LoadView>
    </div>
  );
};

export default Mail;
