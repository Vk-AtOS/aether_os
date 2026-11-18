import React, { useState } from 'react';
import { confirmAction } from '../confirmAction';
import { primeApi, errText } from './primeApi';
import { ErrorBox } from './parts';

const btn = 'px-3 py-1.5 border border-border hover:border-accent text-bright text-xs font-bold rounded-lg disabled:opacity-40';

// Ledger actions beyond the read-only check. Organisation admins: sign a checkpoint now, verify the whole chain
// against the signed checkpoints, check an anchor export you kept. Platform operators: check the local anchor file,
// back-fill old audit rows, retry unfinished erasures. The server enforces who may; each result is shown as returned.
// Purging the audit log is not offered: the ledger is append-only and the API refuses it (410).
const LedgerOps = ({ isAdmin, isSuperadmin }) => {
  const [busy, setBusy] = useState('');
  const [out, setOut] = useState(null);
  const [err, setErr] = useState('');

  const run = async (label, call, confirmText) => {
    if (confirmText && !(await confirmAction(confirmText, label))) return;
    setBusy(label); setErr(''); setOut(null);
    try { setOut({ label, data: (await call()).data }); }
    catch (e) { setErr(`${label}: ${errText(e, 'it failed')}`); }
    finally { setBusy(''); }
  };

  const checkKept = async (ev) => {
    const file = ev.target.files?.[0];
    ev.target.value = '';
    if (!file) return;
    let kept;
    try {
      const doc = JSON.parse(await file.text());
      kept = [...(doc.checkpoints || [])].sort((a, b) => a.chain_seq - b.chain_seq).pop();
      if (!kept) throw new Error('no checkpoints');
    } catch {
      setErr('That file is not an anchor export (no checkpoints found).'); setOut(null); return;
    }
    run('Check kept anchor file', () => primeApi.anchorVerify({ full: true, checkpoint: kept }));
  };

  if (!isAdmin && !isSuperadmin) return null;
  return (
    <div className="bg-panel border border-border rounded-xl px-5 py-4 space-y-3 lg:col-span-2">
      <h3 className="text-xs font-bold text-bright">Ledger actions</h3>
      <div className="flex flex-wrap gap-2 items-center">
        {isAdmin && (
          <>
            <button className={btn} disabled={!!busy} onClick={() => run('Anchor now', primeApi.anchorNow,
              'Verify this organisation’s chain and sign its current head now?')}>Anchor now</button>
            <button className={btn} disabled={!!busy} onClick={() => run('Verify against anchors', () => primeApi.anchorVerify({ full: true }))}>
              Verify against anchors</button>
            <label className={`${btn} cursor-pointer`}>Check kept anchor file…
              <input type="file" accept="application/json,.json" className="sr-only" onChange={checkKept} aria-label="Anchor export file" /></label>
          </>
        )}
        {isSuperadmin && (
          <>
            <button className={btn} disabled={!!busy} onClick={() => run('Check anchor file', primeApi.anchorCheckFile)}>Check local anchor file</button>
            <button className={btn} disabled={!!busy} onClick={() => run('Back-fill (dry run)', () => primeApi.backfill(true))}>Back-fill: dry run</button>
            <button className={btn} disabled={!!busy} onClick={() => run('Back-fill', () => primeApi.backfill(false),
              'Import audit rows that never reached a chain? Run the dry run first. This writes to the ledger.')}>Back-fill: run</button>
            <button className={btn} disabled={!!busy} onClick={() => run('Retry erasures', primeApi.retryErasures,
              'Retry the personal-data erasure of deleted organisations whose erasure did not finish?')}>Retry erasures</button>
          </>
        )}
      </div>
      {busy && <p className="text-xs text-muted">{busy}…</p>}
      {err && <ErrorBox>{err}</ErrorBox>}
      {out && (
        <div role="status" className="text-xs">
          <p className="font-bold text-bright mb-1">{out.label}: result</p>
          <pre className="bg-surface border border-border rounded-lg p-3 overflow-x-auto text-[11px] text-muted">{JSON.stringify(out.data, null, 2)}</pre>
        </div>
      )}
    </div>
  );
};

export default LedgerOps;
