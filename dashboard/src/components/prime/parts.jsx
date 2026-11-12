import React from 'react';
import { Loader2 } from 'lucide-react';

export const inputClass =
  'w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent';
export const labelClass = 'text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block';

export const Spinner = () => (
  <div className="flex justify-center py-16" role="status" aria-label="Loading">
    <Loader2 className="w-6 h-6 animate-spin text-muted" />
  </div>
);

export const ErrorBox = ({ children }) => (
  <div role="alert" className="bg-panel border border-danger/40 rounded-xl px-5 py-4 text-sm text-danger">{children}</div>
);

export const Pill = ({ className, children }) => (
  <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded shrink-0 ${className}`}>{children}</span>
);

// Label / value rows for detail views. Values are shown exactly as stored.
export const Facts = ({ rows }) => (
  <dl className="grid grid-cols-[9rem_1fr] gap-x-4 gap-y-2 text-xs">
    {rows.filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v]) => (
      <React.Fragment key={k}>
        <dt className="text-muted">{k}</dt>
        <dd className="text-bright font-mono break-all">{v}</dd>
      </React.Fragment>
    ))}
  </dl>
);

export const Json = ({ value }) => (
  <pre className="bg-surface border border-border rounded-lg p-3 text-xs text-bright font-mono overflow-x-auto whitespace-pre-wrap break-all">
    {JSON.stringify(value, null, 2)}
  </pre>
);
