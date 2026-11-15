// Plain-language names for Prime's autonomy levels and decision outcomes.
export const AUTONOMY = {
  0: { label: 'Observe only',           help: 'Prime watches and records. It does nothing.' },
  1: { label: 'Recommend',              help: 'Prime suggests what to do. A person does it.' },
  2: { label: 'Act after approval',     help: 'Prime prepares the action and waits for a person to approve it.' },
  3: { label: 'Act, then tell me',      help: 'Prime acts and notifies you each time.' },
  4: { label: 'Act without telling me', help: 'Prime acts silently inside the limits. Everything is still in the ledger.' },
};

export const OUTCOME = {
  EXECUTE:            { label: 'Would act',               color: 'text-emerald-400' },
  EXECUTE_AND_NOTIFY: { label: 'Would act and notify you', color: 'text-emerald-400' },
  NEEDS_APPROVAL:     { label: 'Needs approval',          color: 'text-yellow-400' },
  RECOMMEND_ONLY:     { label: 'Recommendation only',     color: 'text-sky-400' },
  ROUTE_TO_DEPUTY:    { label: 'Sent to your deputy',     color: 'text-yellow-400' },
  REFUSE:             { label: 'Refused',                 color: 'text-danger' },
};

// Ledger timestamps are epoch seconds; delegation dates are ISO strings.
export const fmtDate = (value) => {
  const n = Number(value);
  const d = Number.isFinite(n) ? new Date(n * 1000) : new Date(value);
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
};

export const STATE_STYLE = {
  active:    'text-emerald-400 bg-emerald-400/10',
  scheduled: 'text-sky-400 bg-sky-400/10',
  expired:   'text-muted bg-border/20',
  revoked:   'text-danger bg-danger/10',
  pending:   'text-yellow-400 bg-yellow-400/10',
  approved:  'text-emerald-400 bg-emerald-400/10',
  rejected:  'text-danger bg-danger/10',
};

export const URGENCY_STYLE = {
  urgent:  'text-yellow-400 bg-yellow-400/10',
  overdue: 'text-danger bg-danger/10',
};

export const RISK_STYLE = {
  standard: 'text-emerald-400 bg-emerald-400/10',
  high:     'text-yellow-400 bg-yellow-400/10',
  critical: 'text-danger bg-danger/10',
};

export const EXECUTION = {
  running:         { label: 'Being carried out',                  color: 'text-sky-400' },
  succeeded:       { label: 'Carried out',                        color: 'text-emerald-400' },
  failed:          { label: 'Not carried out',                    color: 'text-danger' },
  needs_attention: { label: 'Needs attention: outcome unknown',   color: 'text-yellow-400' },
};

export const money = (amount, currency) =>
  amount ? `${currency || ''} ${Number(amount).toLocaleString('en-IN')}`.trim() : '';
