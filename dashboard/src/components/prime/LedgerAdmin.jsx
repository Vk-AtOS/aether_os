import React, { useCallback, useState } from 'react';
import { Download, ShieldCheck, ShieldAlert, UserX } from 'lucide-react';
import { confirmAction } from '../confirmAction';
import { primeApi, useLoad, errText } from './primeApi';
import { Facts, ErrorBox, inputClass, labelClass } from './parts';
import { fmtDate } from './labels';
import LedgerOps from './LedgerOps';
import { useRole } from '../../hooks/useRole';

const btn = 'px-3 py-1.5 border border-border hover:border-accent text-bright text-xs font-bold rounded-lg disabled:opacity-40';

// This organisation's chain: where it stands, a check you can run, the export you keep,
// and (admins) erasure of one person's audit data.
const LedgerAdmin = ({ isAdmin }) => {
  const { isSuperadmin } = useRole();
  const latest = useLoad(primeApi.anchorLatest, 'Could not load the chain status.');
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [subject, setSubject] = useState('');
  const [erased, setErased] = useState('');

  const verify = useCallback(async () => {
    setBusy(true); setNote('');
    try { setCheck((await primeApi.ledgerVerify()).data); }
    catch (e) { setNote(errText(e, 'The check could not be run.')); }
    finally { setBusy(false); }
  }, []);

  const download = async () => {
    setNote('');
    try {
      const res = await primeApi.anchorExport();
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/json' }));
      const a = document.createElement('a');
      a.href = url; a.download = 'aetheros-ledger-anchor.json'; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setNote(errText(e, 'The export could not be downloaded.')); }
  };

  const erase = async (ev) => {
    ev.preventDefault(); setNote(''); setErased('');
    const ok = await confirmAction(
      `Erase "${subject.trim()}" from this organisation's audit data? Readers will see "[erased]" instead of it from now on. `
      + 'This cannot be undone. Rows written earlier keep the raw value inside their stored payload (the ledger is append-only and cannot be rewritten); '
      + 'AetherOS hides it when reading and exporting, but it is not physically removed from those rows.',
      'Erase a person’s audit data');
    if (!ok) return;
    try {
      const { data } = await primeApi.eraseSubject(subject.trim());
      setErased(data.matched ? 'Erased. Reads now show “[erased]” for this person.'
        : 'Recorded. Nothing was stored under this value, but older rows that hold it raw are hidden from now on.');
      setSubject('');
    } catch (e) { setNote(errText(e, 'The erasure failed. Nothing was changed; try again.')); }
  };

  const cp = latest.data?.checkpoint;
  const fc = latest.data?.file_check;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="bg-panel border border-border rounded-xl px-5 py-4 space-y-3" aria-labelledby="chain-h">
        <h3 id="chain-h" className="text-xs font-bold text-bright">This organisation’s chain</h3>
        {latest.error && <ErrorBox>{latest.error}</ErrorBox>}
        <Facts rows={[
          ['Head entry', check ? `#${check.head_seq}` : null],
          ['Last signed checkpoint', cp ? `entry #${cp.chain_seq}, ${fmtDate(cp.created_at)}` : (latest.data ? 'none yet' : null)],
          ['Anchor file check', fc ? `${fc.ok ? 'ok' : 'PROBLEM'} · ${fmtDate(fc.at)}` : (latest.data ? 'not run yet' : null)],
        ]} />
        {check && (
          <p className={`text-xs font-bold flex items-center gap-2 ${check.ok ? 'text-emerald-400' : 'text-danger'}`}>
            {check.ok ? <ShieldCheck className="w-4 h-4" aria-hidden="true" /> : <ShieldAlert className="w-4 h-4" aria-hidden="true" />}
            {check.ok ? `Intact · ${check.entries_checked} new entries checked` : `Broken at entry ${check.broken_seq}: ${check.reason}`}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button onClick={verify} disabled={busy} className={btn}>{busy ? 'Checking…' : 'Verify chain'}</button>
          {isAdmin && (
            <button onClick={download} className={`${btn} inline-flex items-center gap-2`}>
              <Download className="w-3.5 h-3.5" aria-hidden="true" />Download anchor export
            </button>
          )}
        </div>
        <p className="text-[11px] text-muted">Verify checks only what was added since the last signed checkpoint.
          {isAdmin && ' Keep the export outside AetherOS: it is your own proof the history was not rewritten.'}</p>
      </div>

      {isAdmin && (
        <form onSubmit={erase} className="bg-panel border border-border rounded-xl px-5 py-4 space-y-3" aria-labelledby="erase-h">
          <h3 id="erase-h" className="text-xs font-bold text-bright flex items-center gap-2">
            <UserX className="w-4 h-4" aria-hidden="true" />Erase a person’s audit data
          </h3>
          <div>
            <label htmlFor="erase-subject" className={labelClass}>Email address, IP address or subject id</label>
            <input id="erase-subject" required maxLength={320} className={inputClass}
                   value={subject} onChange={(e) => setSubject(e.target.value)} />
          </div>
          <p className="text-[11px] text-muted">
            What this does: from now on the ledger browser, the audit log and its exports show “[erased]” instead of this value, and the chain stays verifiable.
            What it cannot do: rows written before pseudonymisation keep the raw value inside their stored payload, because the ledger is append-only. They are hidden when read, not physically removed.
          </p>
          <button type="submit" disabled={!subject.trim()} className={btn}>Erase…</button>
          {erased && <p role="status" className="text-xs text-emerald-400">{erased}</p>}
        </form>
      )}
      <LedgerOps isAdmin={isAdmin} isSuperadmin={isSuperadmin} />
      {note && <div className="lg:col-span-2"><ErrorBox>{note}</ErrorBox></div>}
    </div>
  );
};

export default LedgerAdmin;
