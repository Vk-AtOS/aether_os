import React, { useCallback, useEffect, useState } from 'react';
import { MessageSquare } from 'lucide-react';
import { vc } from '../components/velaris/velarisApi';
import { DownBanner, PageHead, Tabs, Notice } from '../components/velaris/shared';
import { Spinner } from '../components/prime/parts';
import { useRole } from '../hooks/useRole';
import { useChat } from '../components/chat/useChat';
import ChannelList from '../components/chat/ChannelList';
import MessagePane from '../components/chat/MessagePane';
import SidePanel from '../components/chat/SidePanel';
import AssistantBar from '../components/chat/AssistantBar';
import AdminPanel from '../components/chat/AdminPanel';
import EmptyState from '../components/EmptyState';

const Chat = () => {
  const chat = useChat();
  const { isAdmin } = useRole();
  const [tab, setTab] = useState('chat');
  const [picked, setPicked] = useState(null);
  const [side, setSide] = useState(false);
  const [topics, setTopics] = useState({ id: null, list: [] });
  const me = chat.me?.id;
  const activeId = picked ?? chat.channels[0]?.id ?? null;
  const channel = chat.channels.find((c) => c.id === activeId) || null;
  const { setActive } = chat;
  const pick = useCallback((id) => setPicked(id), []);
  useEffect(() => { setActive(activeId); }, [activeId, setActive]);
  useEffect(() => {
    if (activeId == null) return undefined;
    let alive = true;
    vc.get(`/chat/channels/${activeId}/topics`).then((r) => { if (alive) setTopics({ id: activeId, list: r.data.topics }); }).catch(() => {});
    return () => { alive = false; };
  }, [activeId, chat.channels.length]);

  return (
    <div className="space-y-4">
      <PageHead icon={MessageSquare} title="Chat" sub="Team conversations through Velaris"
        right={isAdmin && <Tabs tabs={[['chat', 'Chat'], ['admin', 'Admin']]} value={tab} onChange={setTab} />} />
      {chat.status === 'down' && <DownBanner />}
      {chat.status === 'retry' && <Notice tone="warn">Connection to chat was interrupted: {chat.error}. Retrying.</Notice>}
      {chat.status === 'connecting' && <Spinner />}
      {tab === 'admin' && isAdmin && <AdminPanel channels={chat.channels} />}
      {tab === 'chat' && chat.status === 'live' && (
        <div className="flex gap-3 h-[calc(100vh-13rem)] min-h-[24rem]">
          <ChannelList channels={chat.channels} activeId={activeId} onPick={pick} me={me} />
          <div className="flex-1 flex flex-col min-w-0">
            {channel ? (
              <>
                <AssistantBar chat={chat} channelId={channel.id} me={me} />
                <MessagePane key={channel.id} channel={channel} me={me} chat={chat} topics={topics.id === channel.id ? topics.list : []} onSide={() => setSide(!side)} />
              </>
            ) : <EmptyState icon={MessageSquare} title="Pick a channel" description="Choose a channel on the left, or create one." />}
          </div>
          {side && channel && <SidePanel channel={channel} me={me} onClose={() => setSide(false)} />}
        </div>
      )}
    </div>
  );
};

export default Chat;
