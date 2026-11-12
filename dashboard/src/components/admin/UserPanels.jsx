import React from 'react';

import { ROLES } from './roles';

export const InvitePanel = ({ inviteEmail, setInviteEmail, inviteRole, setInviteRole, inviteStatus, onSubmit, onClose }) => (
  <section className="panel p-6 border-accent/20 bg-accent/5">
    <h3 className="text-xs font-bold text-muted uppercase tracking-widest mb-4">Invite New Member</h3>
    <form onSubmit={onSubmit} className="flex items-end gap-3">
      <div className="flex-1">
        <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Email Address</label>
        <input
          type="email"
          value={inviteEmail}
          onChange={e => setInviteEmail(e.target.value)}
          placeholder="colleague@company.com"
          className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
          required
          autoFocus
        />
      </div>
      <div>
        <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Role</label>
        <select
          value={inviteRole}
          onChange={e => setInviteRole(e.target.value)}
          className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
        >
          {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
      </div>
      <button
        type="submit"
        disabled={inviteStatus === 'sending'}
        className="bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors uppercase tracking-wider"
      >
        {inviteStatus === 'sending' ? '…' : inviteStatus === 'sent' ? '✓ Sent' : inviteStatus === 'link_copied' ? '✓ Link Copied' : inviteStatus === 'error' ? '✗ Error' : 'Send Invite'}
      </button>
      <button type="button" onClick={onClose} className="text-muted hover:text-bright text-xs transition-colors">
        Cancel
      </button>
    </form>
  </section>
);

export const BulkImportPanel = ({ bulkCsv, setBulkCsv, bulkRole, setBulkRole, bulkStatus, onSubmit, onClose }) => (
  <section className="panel p-6 border-border/60 bg-border/5">
    <h3 className="text-xs font-bold text-muted uppercase tracking-widest mb-4">Bulk User Import (CSV / SCIM)</h3>
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Email Addresses (one per line or comma-separated)</label>
          <textarea
            value={bulkCsv}
            onChange={e => setBulkCsv(e.target.value)}
            placeholder={'alice@company.com\nbob@company.com, carol@company.com'}
            rows={4}
            className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright font-mono focus:outline-none focus:border-accent resize-none"
            autoFocus
          />
        </div>
        <div className="shrink-0">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Default Role</label>
          <select
            value={bulkRole}
            onChange={e => setBulkRole(e.target.value)}
            className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
          >
            {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={bulkStatus === 'importing'}
          className="bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors uppercase tracking-wider"
        >
          {bulkStatus === 'importing' ? 'Importing…' : 'Import Users'}
        </button>
        <button type="button" onClick={onClose} className="text-muted hover:text-bright text-xs transition-colors">
          Cancel
        </button>
      </div>
      {bulkStatus && bulkStatus !== 'importing' && (
        <div className="space-y-1">
          <p className="text-xs text-success font-medium">✓ {bulkStatus.ok} user(s) imported successfully.</p>
          {bulkStatus.errors.map((e, i) => <p key={i} className="text-xs text-danger font-mono">{e}</p>)}
        </div>
      )}
    </form>
  </section>
);
