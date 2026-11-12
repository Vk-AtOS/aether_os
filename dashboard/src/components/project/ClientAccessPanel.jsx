import React, { useCallback, useEffect, useState } from 'react';
import { KeyRound, Copy, Check, Loader2, Trash2, AlertTriangle, MessageSquare } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';
import { confirmAction } from '../confirmAction';

const fmtWhen = (ts) => {
  if (!ts) return '—';
  const d = new Date(ts > 1e12 ? ts : ts * 1000);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
};

const STATUS_CLS = {
  active: 'bg-success/15 text-success border-success/30',
  expired: 'bg-border/40 text-muted border-border',
  revoked: 'bg-danger/10 text-danger border-danger/30',
};

const portalLink = (runId, token) => `${window.location.origin}/dashboard/portal/${runId}#t=${encodeURIComponent(token)}`;

// "Client access" (owner/admin): portal links for this run, and the decisions clients recorded.
// Server: gateway/routers/portal_admin_router.py. The token is returned once, at issue.
const ClientAccessPanel = ({ runId }) => {
  const [tokens, setTokens] = useState({ loading: true, items: [], error: '' });
  const [approvals, setApprovals] = useState({ loading: true, items: [], error: '' });
  const [label, setLabel] = useState('');
  const [days, setDays] = useState(30);
  const [issuing, setIssuing] = useState(false);
  const [issueError, setIssueError] = useState('');
  const [issued, setIssued] = useState(null); // {link, label}
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState(null);

  const reload = useCallback(() => {
    api.listPortalTokens(runId)
      .then((r) => setTokens({ loading: false, items: r.data?.tokens || [], error: '' }))
      .catch((e) => setTokens({ loading: false, items: [], error: apiError(e) || 'Could not load access links.' }));
    api.listPortalApprovals(runId)
      .then((r) => setApprovals({ loading: false, items: r.data?.approvals || [], error: '' }))
      .catch((e) => setApprovals({ loading: false, items: [], error: apiError(e) || 'Could not load client decisions.' }));
  }, [runId]);

  useEffect(() => { reload(); }, [reload]);

  const issue = async (e) => {
    e.preventDefault();
    setIssuing(true); setIssueError(''); setIssued(null); setCopied(false);
    try {
      const res = await api.issuePortalToken(runId, label.trim(), Number(days));
      setIssued({ link: portalLink(runId, res.data.token), label: res.data.label });
      setLabel('');
      reload();
    } catch (err) {
      setIssueError(apiError(err) || 'Could not create the link.');
    } finally {
      setIssuing(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(issued.link);
      setCopied(true);
    } catch (err) {
      console.warn('Clipboard write failed', err);
      setIssueError('Copy failed: select the link and copy it by hand.');
    }
  };

  const revoke = async (t) => {
    if (!(await confirmAction(`Revoke the link${t.label ? ` for ${t.label}` : ''}? Anyone using it loses access at once.`, 'Revoke access link'))) return;
    setRevoking(t.id);
    try {
      await api.revokePortalToken(runId, t.id);
      reload();
    } catch (err) {
      setTokens((s) => ({ ...s, error: apiError(err) || 'Could not revoke the link.' }));
    } finally {
      setRevoking(null);
    }
  };

  const inputCls = 'bg-surface border border-border rounded-lg px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent';

  return (
    <section className="space-y-4" aria-labelledby="client-access-h">
      <h2 id="client-access-h" className="text-xs font-bold text-muted uppercase tracking-widest flex items-center gap-1.5">
        <KeyRound className="w-3.5 h-3.5" /> Client access
      </h2>
      <div className="bg-panel border border-border rounded-xl p-5 space-y-4">
        <form onSubmit={issue} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-[10px] font-bold text-muted uppercase">
            For (optional)
            <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} placeholder="Client name" className={`${inputCls} w-48 normal-case font-normal`} />
          </label>
          <label className="flex flex-col gap-1 text-[10px] font-bold text-muted uppercase">
            Expires after (days)
            <input type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} className={`${inputCls} w-24`} />
          </label>
          <button type="submit" disabled={issuing || !(days >= 1 && days <= 90)}
            className="flex items-center gap-1.5 px-3 py-2 bg-accent/20 text-accent border border-accent/30 rounded-lg text-xs font-bold hover:bg-accent/30 disabled:opacity-50">
            {issuing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <KeyRound className="w-3.5 h-3.5" />} Create access link
          </button>
        </form>
        {issueError && <p role="alert" className="text-xs text-danger">{issueError}</p>}
        {issued && (
          <div role="status" className="rounded-lg border border-warning/40 bg-warning/5 p-4 space-y-2">
            <p className="text-xs font-bold text-warning flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" /> Copy this link now. It will not be shown again.
            </p>
            <div className="flex items-center gap-2">
              <input readOnly value={issued.link} onFocus={(e) => e.target.select()} aria-label="Portal link"
                className={`${inputCls} flex-1 font-mono`} />
              <button type="button" onClick={copy} className="flex items-center gap-1 px-3 py-1.5 border border-border rounded-lg text-xs text-bright hover:border-accent">
                {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />} {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <p className="text-[11px] text-muted">Anyone with this link can view this build and record an approval until it expires or you revoke it.</p>
          </div>
        )}

        {tokens.loading ? (
          <p className="text-xs text-muted flex items-center gap-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading links…</p>
        ) : tokens.error ? (
          <p role="alert" className="text-xs text-danger">{tokens.error}</p>
        ) : tokens.items.length === 0 ? (
          <p className="text-xs text-muted">No access links yet. Clients without a link cannot open the portal.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-[10px] text-muted uppercase tracking-wider border-b border-border">
                  <th className="py-2 pr-3">For</th><th className="py-2 pr-3">Status</th><th className="py-2 pr-3">Created</th>
                  <th className="py-2 pr-3">Expires</th><th className="py-2 pr-3">Last used</th><th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {tokens.items.map((t) => (
                  <tr key={t.id} className="border-b border-border/50 last:border-0">
                    <td className="py-2 pr-3 text-bright">{t.label || <span className="text-muted font-mono">{t.id.slice(0, 8)}</span>}</td>
                    <td className="py-2 pr-3"><span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase ${STATUS_CLS[t.status] || STATUS_CLS.expired}`}>{t.status}</span></td>
                    <td className="py-2 pr-3 text-muted">{fmtWhen(t.created_at)}</td>
                    <td className="py-2 pr-3 text-muted">{t.status === 'revoked' ? `revoked ${fmtWhen(t.revoked_at)}` : fmtWhen(t.expires_at)}</td>
                    <td className="py-2 pr-3 text-muted">{t.last_used_at ? fmtWhen(t.last_used_at) : 'never'}</td>
                    <td className="py-2 text-right">
                      {t.status === 'active' && (
                        <button onClick={() => revoke(t)} disabled={revoking === t.id} title="Revoke this link"
                          className="inline-flex items-center gap-1 px-2 py-1 text-[11px] text-danger border border-danger/30 rounded hover:bg-danger/10 disabled:opacity-50">
                          {revoking === t.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />} Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <h3 className="text-xs font-bold text-muted uppercase tracking-widest flex items-center gap-1.5">
        <MessageSquare className="w-3.5 h-3.5" /> Client approvals
      </h3>
      <div className="bg-panel border border-border rounded-xl p-5">
        {approvals.loading ? (
          <p className="text-xs text-muted flex items-center gap-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…</p>
        ) : approvals.error ? (
          <p role="alert" className="text-xs text-danger">{approvals.error}</p>
        ) : approvals.items.length === 0 ? (
          <p className="text-xs text-muted">No client has recorded a decision on this build yet.</p>
        ) : (
          <ul className="divide-y divide-border/50">
            {approvals.items.map((a) => (
              <li key={a.id} className="py-2.5 text-xs space-y-0.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`font-bold ${a.approved ? 'text-success' : 'text-warning'}`}>{a.approved ? 'Approved' : 'Changes requested'}</span>
                  <span className="text-muted">by {a.actor_label || a.actor_kind}</span>
                  <span className="text-muted">· {fmtWhen(a.created_at)}</span>
                  {a.applied_to === 'spec_review' && <span className="text-accent">· released spec review</span>}
                </div>
                {a.comment && <p className="text-bright/80 whitespace-pre-wrap">{a.comment}</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
};

export default ClientAccessPanel;
