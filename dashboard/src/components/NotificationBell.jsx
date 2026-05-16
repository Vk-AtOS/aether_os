import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Bell, CheckCheck, ExternalLink } from 'lucide-react';
import { api } from '../api';
import { useNavigate } from 'react-router-dom';

const TYPE_ICON = {
  run_completed: '✅',
  run_failed: '❌',
  decision_required: '⚠️',
  default: '🔔',
};

const NotificationBell = () => {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [marking, setMarking] = useState(false);
  const ref = useRef(null);
  const navigate = useNavigate();

  const fetchNotifications = useCallback(async () => {
    try {
      const res = await api.client.get('/notifications', { params: { limit: 30 } });
      setItems(res.data.items ?? []);
      setUnread(res.data.unread_count ?? 0);
    } catch {
      // silently ignore if endpoint not yet available
    }
  }, []);

  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 30000);
    return () => clearInterval(interval);
  }, [fetchNotifications]);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleMarkAllRead = async () => {
    setMarking(true);
    try {
      await api.client.post('/notifications/read-all');
      setItems(prev => prev.map(n => ({ ...n, is_read: true })));
      setUnread(0);
    } catch {}
    setMarking(false);
  };

  const handleClick = async (notif) => {
    if (!notif.is_read) {
      try {
        await api.client.post(`/notifications/${notif.id}/read`);
        setItems(prev => prev.map(n => n.id === notif.id ? { ...n, is_read: true } : n));
        setUnread(prev => Math.max(0, prev - 1));
      } catch {}
    }
    if (notif.link) {
      setOpen(false);
      navigate(notif.link);
    }
  };

  const relativeTime = (ts) => {
    const diff = Date.now() / 1000 - ts;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  };

  const bellLabel = unread > 0
    ? `Notifications — ${unread} unread`
    : 'Notifications — no unread';

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(v => !v)}
        aria-label={bellLabel}
        aria-haspopup="true"
        aria-expanded={open}
        className="relative p-1.5 text-muted hover:text-bright transition-colors"
      >
        <Bell className="w-4 h-4" aria-hidden="true" />
        {unread > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 flex items-center justify-center bg-danger text-white text-[9px] font-bold rounded-full px-1"
            aria-hidden="true"
          >
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-2 w-80 bg-panel border border-border rounded-xl shadow-2xl z-50 overflow-hidden"
          role="region"
          aria-label="Notifications panel"
        >
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <span className="text-xs font-bold text-muted uppercase tracking-widest" id="notif-heading">Notifications</span>
            {unread > 0 && (
              <button
                onClick={handleMarkAllRead}
                disabled={marking}
                aria-label="Mark all notifications as read"
                className="flex items-center gap-1 text-[10px] font-bold text-accent hover:text-accent/80 transition-colors disabled:opacity-50"
              >
                <CheckCheck className="w-3 h-3" aria-hidden="true" />
                Mark all read
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto divide-y divide-border/50" role="list" aria-labelledby="notif-heading">
            {items.length === 0 ? (
              <div className="px-4 py-8 text-center text-muted text-xs" role="listitem">No notifications yet.</div>
            ) : items.map(n => (
              <button
                key={n.id}
                onClick={() => handleClick(n)}
                role="listitem"
                aria-label={`${n.is_read ? '' : 'Unread: '}${n.title}${n.message ? ` — ${n.message}` : ''}`}
                className={`w-full text-left px-4 py-3 hover:bg-border/10 transition-colors flex items-start gap-3 ${!n.is_read ? 'bg-accent/5' : ''}`}
              >
                <span className="text-sm mt-0.5 shrink-0" aria-hidden="true">{TYPE_ICON[n.type] || TYPE_ICON.default}</span>
                <div className="flex-1 min-w-0">
                  <div className={`text-xs font-semibold truncate ${!n.is_read ? 'text-bright' : 'text-muted'}`}>{n.title}</div>
                  {n.message && <div className="text-[11px] text-muted mt-0.5 truncate">{n.message}</div>}
                  <div className="text-[10px] text-muted/60 mt-1">{relativeTime(n.created_at)}</div>
                </div>
                {!n.is_read && <span className="w-1.5 h-1.5 rounded-full bg-accent mt-1.5 shrink-0" aria-hidden="true" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default NotificationBell;
