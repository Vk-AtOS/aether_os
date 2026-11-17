import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Eye, EyeOff } from 'lucide-react';
import { useHr } from '../velaris/velarisApi';
import { inputClass } from '../prime/parts';

// Fields that identify or pay a person stay masked until someone chooses to look.
const SENSITIVE = /(pan|aadhaar|aadhar|bank|account|ifsc|phone|mobile|email|salary|ctc|dob|birth|passport|identifier|number)/i;

export const Masked = ({ value }) => {
  const [show, setShow] = useState(false);
  const text = typeof value === 'string' || typeof value === 'number' ? String(value) : JSON.stringify(value);
  return (
    <span className="font-mono">
      {show ? text : '•'.repeat(6)}
      <button type="button" className="ml-2 text-muted align-middle" aria-label={show ? 'Hide value' : 'Show value'} onClick={() => setShow(!show)}>
        {show ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
      </button>
    </span>
  );
};

// Any record as label/value rows; sensitive keys masked, nested objects indented, long lists as counts.
export const Detail = ({ data, depth = 0 }) => {
  if (data == null) return <span className="text-muted">none</span>;
  if (typeof data !== 'object') return <span className="font-mono break-all">{String(data)}</span>;
  const entries = Array.isArray(data) ? data.map((v, i) => [String(i + 1), v]) : Object.entries(data);
  if (entries.length === 0) return <span className="text-muted">none</span>;
  return (
    <dl className={`grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1 text-xs ${depth ? 'pl-3 border-l border-border' : ''}`}>
      {entries.map(([k, v]) => (
        <React.Fragment key={k}>
          <dt className="text-muted">{k.replace(/_/g, ' ')}</dt>
          <dd className="text-bright min-w-0">
            {SENSITIVE.test(k) && v != null && typeof v !== 'object' ? <Masked value={v} />
              : depth < 3 ? <Detail data={v} depth={depth + 1} /> : <span className="font-mono break-all">{JSON.stringify(v)}</span>}
          </dd>
        </React.Fragment>
      ))}
    </dl>
  );
};

export const StateBadge = ({ state }) => {
  const good = ['open', 'approved', 'hired', 'signed', 'accepted', 'live', 'completed', 'published'].includes(state);
  const bad = ['rejected', 'closed', 'withdrawn', 'voided', 'declined', 'cancelled', 'canceled', 'taken_down', 'expired'].includes(state);
  return <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${good ? 'bg-success/15 text-success' : bad ? 'bg-danger/15 text-danger' : 'bg-warning/15 text-warning'}`}>{String(state).replace(/_/g, ' ')}</span>;
};

// A requisition dropdown fed by ATS_CORE.list_requisitions.
export const ReqSelect = ({ value, onChange, label = 'Requisition' }) => {
  const q = useHr('ATS_CORE', 'list_requisitions');
  const rows = q.data?.requisitions || [];
  return (
    <select aria-label={label} className={`${inputClass} max-w-xs`} value={value} onChange={(e) => onChange(e.target.value)} disabled={q.loading}>
      <option value="">{q.loading ? 'Loading…' : q.error ? 'Could not load requisitions' : `Choose a ${label.toLowerCase()}`}</option>
      {rows.map((r) => <option key={r.id} value={r.id}>{r.title} ({r.state})</option>)}
    </select>
  );
};

// Points a tab at the admin screen that holds the actions this tab does not (KAN-144, KAN-145): one place per task,
// reachable from where the person already is.
export const ScreenLink = ({ to, children }) => (
  <p className="text-xs text-muted">{children} <Link className="text-accent hover:underline" to={`/work/${to}`}>Open the screen</Link></p>
);
