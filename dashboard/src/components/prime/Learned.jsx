import React, { useCallback, useState } from 'react';
import { api } from '../../api';
import { confirmAction } from '../confirmAction';
import { useRole } from '../../hooks/useRole';
import { errText, useLoad } from './primeApi';
import { Spinner, ErrorBox, Pill } from './parts';

// KAN-229: what Prime has learned for this organisation (approver corrections, golden builds, build fixes), how often
// each lesson was used and how often it helped. Organisation-level only: no per-person view. Retire / restore is for
// owners and admins; the server checks the role too (hiding the buttons is not the control).
const c = api.client;
const learnedApi = {
  items: () => c.get('/prime/learning/items'),
  metrics: (weeks = 12) => c.get('/prime/learning/metrics', { params: { weeks } }),
  retire: (kind, id) => c.post(`/prime/learning/items/${kind}/${encodeURIComponent(id)}/retire`),
  restore: (kind, id) => c.post(`/prime/learning/items/${kind}/${encodeURIComponent(id)}/restore`),
};

const KINDS = [
  { key: 'correction', title: 'Approver corrections', help: 'Helps when the next request of that agent is approved unchanged.' },
  { key: 'golden', title: 'Golden builds', help: 'Helps when the build that used it as an example passes.' },
  { key: 'fix', title: 'Build fixes', help: 'Helps when the error is gone after the stored fix is replayed.' },
];

const pct = (rate) => (rate === null || rate === undefined ? '—' : `${Math.round(rate * 100)}%`);

// Two weekly rates as lines on one 0-100% scale. Weeks without data leave a gap.
const SERIES = [
  { key: 'first_pass_rate', label: 'Build first-pass rate', color: 'var(--color-accent, #6366f1)' },
  { key: 'correction_rate', label: 'Correction rate', color: '#f59e0b' },
];

const Trend = ({ weeks }) => {
  const W = 560, H = 140, PAD = 24;
  const x = (i) => PAD + (weeks.length > 1 ? (i * (W - 2 * PAD)) / (weeks.length - 1) : 0);
  const y = (v) => H - PAD - v * (H - 2 * PAD);
  const segments = (key) => {
    const out = [];
    let cur = [];
    weeks.forEach((w, i) => {
      if (w[key] === null || w[key] === undefined) { if (cur.length) out.push(cur); cur = []; return; }
      cur.push([x(i), y(w[key])]);
    });
    if (cur.length) out.push(cur);
    return out;
  };
  const latest = (key) => [...weeks].reverse().find((w) => w[key] !== null && w[key] !== undefined)?.[key] ?? null;
  return (
    <figure className="bg-panel border border-border rounded-xl px-5 py-4 space-y-2" aria-label="Weekly trend">
      <figcaption className="flex flex-wrap gap-4 text-xs">
        {SERIES.map((s) => (
          <span key={s.key} className="flex items-center gap-2 text-muted">
            <span className="inline-block w-3 h-0.5" style={{ background: s.color }} aria-hidden="true" />
            {s.label}: <span className="text-bright font-bold" data-testid={`latest-${s.key}`}>{pct(latest(s.key))}</span>
          </span>
        ))}
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-36" role="img"
           aria-label={`Build first-pass rate and correction rate per week, ${weeks.length} weeks`}>
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line x1={PAD} x2={W - PAD} y1={y(v)} y2={y(v)} stroke="currentColor" className="text-border" strokeWidth="1" />
            <text x={2} y={y(v) + 3} fontSize="9" fill="currentColor" className="text-muted">{v * 100}%</text>
          </g>
        ))}
        {SERIES.map((s) => segments(s.key).map((pts, j) => (
          pts.length === 1
            ? <circle key={`${s.key}${j}`} cx={pts[0][0]} cy={pts[0][1]} r="3" fill={s.color} />
            : <polyline key={`${s.key}${j}`} points={pts.map((p) => p.join(',')).join(' ')} fill="none"
                        stroke={s.color} strokeWidth="2" strokeLinejoin="round" />
        )))}
        {weeks.length > 0 && (
          <>
            <text x={PAD} y={H - 6} fontSize="9" fill="currentColor" className="text-muted">{weeks[0].week}</text>
            <text x={W - PAD} y={H - 6} fontSize="9" fill="currentColor" className="text-muted" textAnchor="end">
              {weeks[weeks.length - 1].week}
            </text>
          </>
        )}
      </svg>
    </figure>
  );
};

const ItemRow = ({ item, isAdmin, onToggle }) => (
  <li className="bg-panel border border-border rounded-xl px-5 py-3 flex flex-wrap items-center gap-3">
    <div className="flex-1 min-w-[14rem]">
      <p className="text-sm text-bright break-all">{item.text}</p>
      <p className="text-xs text-muted mt-0.5 font-mono">{item.scope}</p>
    </div>
    <div className="text-xs text-muted text-right" aria-label={`Used ${item.used} times, helped ${pct(item.help_rate)}`}>
      <span className="text-bright font-bold">{item.used}</span> uses · helped <span className="text-bright font-bold">{pct(item.help_rate)}</span>
    </div>
    {item.retired && (
      <Pill className="bg-danger/10 text-danger">{item.retired_by === 'prime' ? 'Retired by Prime' : 'Retired'}</Pill>
    )}
    {isAdmin && (
      <button onClick={() => onToggle(item)}
              aria-label={`${item.retired ? 'Restore' : 'Retire'} ${item.text}`}
              className={`px-3 py-1.5 text-xs font-bold rounded-lg border ${item.retired
                ? 'text-bright border-border hover:bg-surface' : 'text-danger border-danger/40 hover:bg-danger/10'}`}>
        {item.retired ? 'Restore' : 'Retire'}
      </button>
    )}
  </li>
);

const Learned = () => {
  const { isAdmin } = useRole();
  const loadItems = useCallback(() => learnedApi.items(), []);
  const loadMetrics = useCallback(() => learnedApi.metrics(12), []);
  const items = useLoad(loadItems, 'Could not load what Prime has learned.');
  const metrics = useLoad(loadMetrics, 'Could not load the trend.');
  const [problem, setProblem] = useState('');

  const toggle = async (item) => {
    if (!item.retired && !(await confirmAction(
      'Retire this lesson? Prime stops putting it into prompts until an admin restores it.', 'Retire lesson'))) return;
    setProblem('');
    try {
      await (item.retired ? learnedApi.restore : learnedApi.retire)(item.kind, item.id);
      items.reload();
    } catch (e) { setProblem(errText(e, 'Could not change it.')); }
  };

  if (items.loading && !items.data) return <Spinner />;
  const kinds = items.data?.kinds || {};
  const totals = metrics.data?.totals || {};
  return (
    <section className="space-y-6" aria-label="What Prime has learned">
      <div>
        <h2 className="text-lg font-bold text-bright">What Prime has learned</h2>
        <p className="text-xs text-muted mt-1">
          Lessons from approvals and builds in this organisation, how often each was used and how often it helped.
          A lesson that does not help {items.data?.retire_after ?? 3} times in a row is retired automatically.
        </p>
      </div>
      {(items.error || problem) && <ErrorBox>{items.error || problem}</ErrorBox>}
      {metrics.error && <ErrorBox>{metrics.error}</ErrorBox>}
      {metrics.data && <Trend weeks={metrics.data.weeks || []} />}
      {KINDS.map((k) => {
        const list = kinds[k.key] || [];
        return (
          <section key={k.key} aria-label={k.title} className="space-y-2">
            <header className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-bold text-bright">{k.title} <span className="text-muted font-normal">({list.length})</span></h3>
              <span className="text-xs text-muted">Help rate, 12 weeks: <span className="text-bright font-bold">{pct(totals[k.key]?.help_rate)}</span></span>
            </header>
            <p className="text-xs text-muted">{k.help}</p>
            {list.length === 0 ? (
              <p className="text-xs text-muted bg-panel border border-border rounded-xl px-5 py-3">Nothing learned yet.</p>
            ) : (
              <ul className="space-y-2">
                {list.map((item) => <ItemRow key={item.id} item={item} isAdmin={isAdmin} onToggle={toggle} />)}
              </ul>
            )}
          </section>
        );
      })}
    </section>
  );
};

export default Learned;
