import React, { useState, useEffect } from 'react';
import { api } from '../../api';
import { apiError } from '../../apiError';
import { inputClass } from '../prime/parts';

// E-mail is held back between start and end (local time of the chosen zone). Approval emails ignore it: a request
// can expire while nobody is told. In-app notices always stay. Equal times clear the window.
const QuietHours = () => {
  const [f, setF] = useState({ start: '22:00', end: '07:00', tz: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' });
  const [saved, setSaved] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    api.getQuietHours().then((r) => { const q = r.data.quiet_hours; if (live && q) setF({ start: q.start, end: q.end, tz: q.tz }); })
      .catch((e) => live && setError(apiError(e) || 'Could not load quiet hours.'));
    return () => { live = false; };
  }, []);

  const save = async (next) => {
    try { await api.setQuietHours(next); setSaved(next.start === next.end ? 'Quiet hours are off.' : 'Saved.'); setError(''); }
    catch (e) { setError(apiError(e) || 'Could not save quiet hours.'); setSaved(''); }
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  return (
    <div className="space-y-2">
      <h4 className="text-[10px] font-bold text-muted uppercase tracking-widest">Quiet hours (email)</h4>
      <div className="flex flex-wrap items-end gap-3 text-xs">
        <label>From <input type="time" aria-label="Quiet hours start" className={inputClass} value={f.start} onChange={set('start')} /></label>
        <label>To <input type="time" aria-label="Quiet hours end" className={inputClass} value={f.end} onChange={set('end')} /></label>
        <label>Time zone <input aria-label="Quiet hours time zone" className={inputClass} value={f.tz} onChange={set('tz')} /></label>
        <button className="px-3 py-1.5 border border-border rounded-lg font-bold" onClick={() => save(f)}>Save</button>
        <button className="px-3 py-1.5 border border-border rounded-lg text-muted" onClick={() => { const off = { ...f, end: f.start }; setF(off); save(off); }}>Turn off</button>
      </div>
      {saved && <p role="status" className="text-xs text-success">{saved}</p>}
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      <p className="text-[10px] text-muted">Approval emails are always sent. Held emails are not sent later; the in-app notice stays.</p>
    </div>
  );
};

export default QuietHours;
