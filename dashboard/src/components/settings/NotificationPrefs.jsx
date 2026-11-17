import React, { useState, useEffect, useCallback } from 'react';
import { Bell } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';
import { useRole } from '../../hooks/useRole';
import QuietHours from './QuietHours';

// Per-event, per-channel notification settings. Your own choice wins over the organisation default
// (which owners/admins set here too). The server filters the bell and the email by the same rows.
const NotificationPrefs = () => {
  const { isAdmin } = useRole();
  const [mine, setMine] = useState(null);
  const [org, setOrg] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => api.getNotificationPrefs()
    .then((res) => { setMine(res.data.events); setError(null); })
    .catch((e) => setError(apiError(e) || 'Could not load notification settings.')), []);
  useEffect(() => { load(); }, [load]);

  const toggle = async (scope, event, channel, value) => {
    try {
      const res = scope === 'org'
        ? await api.setOrgNotificationPref({ event, [channel]: value })
        : await api.setNotificationPref({ event, [channel]: value });
      if (scope === 'org') setOrg(res.data.events); else setMine(res.data.events);
      setError(null);
    } catch (e) {
      setError(apiError(e) || 'Could not save the setting.');
    }
  };

  const table = (rows, scope) => (
    <table className="w-full text-xs">
      <thead><tr className="text-left text-muted uppercase text-[10px]"><th className="py-1">Event</th><th>In app</th><th>Email</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.event} className="border-t border-border">
            <td className="py-2 text-bright">{r.label}{scope === 'me' && r.source === 'org' && <span className="ml-2 text-muted">(organisation default)</span>}</td>
            {['in_app', 'email'].map((ch) => (
              <td key={ch}>
                <input type="checkbox" aria-label={`${scope === 'org' ? 'Organisation default: ' : ''}${r.label} ${ch === 'in_app' ? 'in app' : 'email'}`}
                  checked={!!r[ch]} onChange={(e) => toggle(scope, r.event, ch, e.target.checked)} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <section className="panel overflow-hidden">
      <div className="bg-border/20 px-6 py-3 border-b border-border flex items-center text-xs font-bold text-muted uppercase tracking-widest">
        <Bell className="w-4 h-4 mr-2 text-accent" />Notifications
      </div>
      <div className="p-6 space-y-5">
        {error && <div role="alert" className="text-xs text-danger">{error}</div>}
        {mine && table(mine, 'me')}
        <QuietHours />
        {isAdmin && (
          <div className="space-y-2">
            <h4 className="text-[10px] font-bold text-muted uppercase tracking-widest">Organisation default</h4>
            {org ? table(org, 'org') : <button className="text-xs text-accent hover:underline" onClick={() => setOrg(mine)}>Edit organisation default</button>}
          </div>
        )}
      </div>
    </section>
  );
};

export default NotificationPrefs;
