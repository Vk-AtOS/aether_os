import React, { useState } from 'react';
import { Download, Trash2 } from 'lucide-react';
import { confirmAction } from '../confirmAction';
import { primeApi, errText, useLoad } from './primeApi';
import { Spinner, ErrorBox } from './parts';

// KAN-228: what Prime may learn about the signed-in person, from which source, and what it has learned. Only that
// person sees this screen's data (the API refuses everyone else, admins included). Everything starts off.
const SOURCE_LABELS = {
  all: 'Let Prime learn from my work',
  git: 'Git',
  jira: 'Jira',
  calendar: 'Calendar',
  attendance: 'Attendance (Velaris)',
};

const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '');

const Toggle = ({ on, label, disabled, onChange }) => (
  <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={onChange}
          className={`relative w-10 h-6 rounded-full shrink-0 transition-colors disabled:opacity-40 ${on ? 'bg-accent' : 'bg-border'}`}>
    <span className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${on ? 'left-5' : 'left-1'}`} />
  </button>
);

const download = (data) => {
  // Best effort in the browser; the export itself already happened and was recorded.
  if (typeof URL.createObjectURL !== 'function') return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `prime-my-data-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

const YourData = () => {
  const { data, error, loading, reload } = useLoad(primeApi.myData, 'Could not load your data.');
  const [busy, setBusy] = useState('');
  const [problem, setProblem] = useState('');
  const [note, setNote] = useState('');

  const act = async (key, fn, done) => {
    setBusy(key); setProblem(''); setNote('');
    try { const res = await fn(); setNote(done(res?.data || {})); reload(); }
    catch (e) { setProblem(errText(e, 'That did not work. Nothing was changed.')); }
    finally { setBusy(''); }
  };

  const toggle = async (s) => {
    const name = SOURCE_LABELS[s.source];
    if (s.enabled && !(await confirmAction(
      s.source === 'all'
        ? 'Prime stops learning from every source and deletes everything it learned about you.'
        : `Prime stops learning from ${name} and deletes what it learned from it.`,
      'Turn off and delete?'))) return;
    return act(s.source, () => primeApi.setConsent({ source: s.source, enabled: !s.enabled, notice_version: data.notice_version }),
      (r) => (s.enabled ? `${name} is off. ${r.erased || 0} learned items deleted.` : `${name} is on.`));
  };

  const erase = async (source) => {
    const what = source ? `what Prime learned from ${SOURCE_LABELS[source]}` : 'everything Prime learned about you';
    if (!(await confirmAction(`Delete ${what}? Your switches stay as they are.`, 'Erase learned data?'))) return;
    return act(`erase-${source || 'all'}`, () => primeApi.eraseMyData(source), (r) => `${r.erased || 0} learned items deleted.`);
  };

  const exportAll = () => act('export', primeApi.exportMyData, (r) => {
    download(r);
    return `Exported ${(r.learned || []).length} learned items.`;
  });

  if (loading && !data) return <Spinner />;
  if (!data?.switches) return <ErrorBox>{error || 'Could not load your data.'}</ErrorBox>;
  const [overall, ...sources] = data.switches;
  const total = Object.values(data.counts).reduce((a, b) => a + b, 0);

  return (
    <section className="space-y-5" aria-labelledby="your-data-h">
      <div className="bg-panel border border-border rounded-xl px-5 py-4 space-y-2">
        <h2 id="your-data-h" className="text-sm font-bold text-bright">Prime and your data</h2>
        <p className="text-xs text-muted leading-relaxed" data-testid="notice">{data.notice}</p>
        <p className="text-[11px] text-muted">
          Notice version {data.notice_version} · learned data is kept for {data.retention_days} days.
        </p>
      </div>

      {(problem || error) && <ErrorBox>{problem || error}</ErrorBox>}
      {note && <p role="status" className="text-xs text-emerald-400">{note}</p>}

      <ul className="bg-panel border border-border rounded-xl divide-y divide-border" aria-label="Sources">
        {[overall, ...sources].map((s) => {
          const isSource = s.source !== 'all';
          return (
            <li key={s.source} className={`px-5 py-4 flex items-start gap-4 ${isSource ? 'pl-9' : ''}`}>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold text-bright">{SOURCE_LABELS[s.source]}</p>
                <p className="text-xs text-muted mt-0.5">{s.purpose}</p>
                <p className="text-[11px] text-muted mt-1">
                  {s.enabled ? `On since ${day(s.enabled_at)}` : 'Off'}
                  {isSource && ` · ${data.counts[s.source]} learned`}
                </p>
              </div>
              <Toggle on={s.enabled} label={SOURCE_LABELS[s.source]} onChange={() => toggle(s)}
                      disabled={!!busy || (isSource && !overall.enabled && !s.enabled)} />
            </li>
          );
        })}
      </ul>
      {!overall.enabled && <p className="text-xs text-muted">Turn on the first switch, then the sources you want.</p>}

      <div className="bg-panel border border-border rounded-xl px-5 py-4 space-y-3" aria-label="What Prime has learned">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold text-bright flex-1">What Prime has learned ({total})</h3>
          <button type="button" onClick={exportAll} disabled={!!busy}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-bright border border-border hover:bg-border/30 rounded-lg disabled:opacity-50">
            <Download className="w-3.5 h-3.5" aria-hidden="true" /> Export as JSON
          </button>
          <button type="button" onClick={() => erase(null)} disabled={!!busy || total === 0}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-danger border border-danger/40 hover:bg-danger/10 rounded-lg disabled:opacity-50">
            <Trash2 className="w-3.5 h-3.5" aria-hidden="true" /> Erase everything
          </button>
        </div>
        <ul className="flex flex-wrap gap-2" aria-label="Counts per source">
          {sources.map((s) => (
            <li key={s.source} className="flex items-center gap-2 text-xs bg-surface border border-border rounded-lg px-3 py-1.5">
              <span className="text-bright">{SOURCE_LABELS[s.source]}: {data.counts[s.source]}</span>
              {data.counts[s.source] > 0 && (
                <button type="button" onClick={() => erase(s.source)} disabled={!!busy}
                        aria-label={`Erase ${SOURCE_LABELS[s.source]} data`} className="text-danger hover:underline">
                  Erase
                </button>
              )}
            </li>
          ))}
        </ul>
        {data.newest.length === 0 ? (
          <p className="text-xs text-muted">Nothing learned yet.</p>
        ) : (
          <ul className="space-y-1.5" aria-label="Newest learned items">
            {data.newest.map((i) => (
              <li key={i.id} className="text-xs text-bright flex gap-3">
                <span className="text-muted shrink-0 w-24">{day(i.learned_at)}</span>
                <span className="text-muted shrink-0 w-20">{SOURCE_LABELS[i.source]}</span>
                <span className="break-all">{i.summary}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
};

export default YourData;
