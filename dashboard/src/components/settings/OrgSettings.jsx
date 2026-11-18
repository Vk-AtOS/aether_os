import React from 'react';
import { confirmAction } from '../confirmAction';
import { Settings as SettingsIcon, Server, FileText, Download } from 'lucide-react';

// ── Audit Log Export Panel ─────────────────────────────────────────────────────
export const AuditExportPanel = ({
  auditFromDate, setAuditFromDate,
  auditToDate, setAuditToDate,
  auditActionFilter, setAuditActionFilter,
  auditExportStatus,
  onExport,
}) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
      <FileText className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Audit Log Export</h3>
    </div>
    <div className="p-6 space-y-5">
      <p className="text-xs text-muted">Download a CSV of all organisation audit events. Filter by date range and action type.</p>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">From Date</label>
          <input
            type="date"
            value={auditFromDate}
            onChange={e => setAuditFromDate(e.target.value)}
            className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent transition-colors"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">To Date</label>
          <input
            type="date"
            value={auditToDate}
            onChange={e => setAuditToDate(e.target.value)}
            className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent transition-colors"
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">Action Filter <span className="normal-case font-normal text-muted">(optional, partial match)</span></label>
        <select
          value={auditActionFilter}
          onChange={e => setAuditActionFilter(e.target.value)}
          className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent transition-colors"
        >
          <option value="">All actions</option>
          <option value="login">login</option>
          <option value="logout">logout</option>
          <option value="create">create</option>
          <option value="update">update</option>
          <option value="delete">delete</option>
          <option value="invite">invite</option>
          <option value="role">role</option>
          <option value="export">export</option>
        </select>
      </div>
      <div className="flex items-center gap-4">
        <button
          onClick={onExport}
          disabled={auditExportStatus === 'exporting'}
          className="flex items-center gap-2 text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-4 py-2 rounded-lg uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
        >
          <Download className="w-3.5 h-3.5" />
          {auditExportStatus === 'exporting' ? 'Exporting…' : auditExportStatus === 'done' ? '✓ Downloaded' : auditExportStatus === 'error' ? '✗ Export Failed' : 'Export CSV'}
        </button>
        {!auditFromDate && !auditToDate && (
          <span className="text-[10px] text-muted">No date range set — exports all records</span>
        )}
      </div>
    </div>
  </section>
);

// ── Organisation Settings Panel ────────────────────────────────────────────────
export const OrgConfigPanel = ({
  orgConfig, setOrgConfig,
  orgSaveStatus,
  onSave,
  deleteOrgStatus, setDeleteOrgStatus,
  deleteOrgInput, setDeleteOrgInput,
  orgName,
  onDeleteOrg,
}) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
      <SettingsIcon className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Organisation Settings</h3>
    </div>
    <div className="p-6 space-y-6">
      <div className="space-y-2">
        <label className="text-[10px] font-bold text-muted uppercase tracking-wider block">Autonomous Mode</label>
        <p className="text-xs text-muted">When enabled, AetherOS runs pipelines without requesting human approval gates.</p>
        <div className="flex items-center gap-3 mt-1">
          <button
            onClick={async () => {
              // Turning it on skips the spec review gate for every run in the organisation.
              if (!orgConfig.autonomous_mode && !(await confirmAction('Autonomous mode skips the spec review step for every run in this organisation. Turn it on?', 'Enable autonomous mode'))) return;
              setOrgConfig(c => ({ ...c, autonomous_mode: !c.autonomous_mode }));
            }}
            role="switch"
            aria-checked={orgConfig.autonomous_mode}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${orgConfig.autonomous_mode ? 'bg-accent' : 'bg-border'}`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${orgConfig.autonomous_mode ? 'translate-x-[18px]' : 'translate-x-1'}`}
            />
          </button>
          <span className="text-xs text-bright">{orgConfig.autonomous_mode ? 'Enabled' : 'Disabled'}</span>
        </div>
      </div>

      <button
        onClick={onSave}
        disabled={orgSaveStatus === 'saving'}
        className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-4 py-1.5 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
      >
        {orgSaveStatus === 'saving' ? '…' : orgSaveStatus === 'saved' ? '✓ Saved' : orgSaveStatus === 'error' ? '✗ Error' : 'Save Organisation Settings'}
      </button>

      {/* Danger Zone */}
      <div className="border border-danger/30 rounded-xl p-5 space-y-4 mt-4">
        <h4 className="text-xs font-bold text-danger uppercase tracking-widest">Danger Zone</h4>
        <p className="text-xs text-muted">Delete this organisation. This cannot be undone and there is no grace period: all users are signed out and anonymised, passwords are destroyed, and personal data in the audit ledger is erased. Only an owner can do this.</p>
        {deleteOrgStatus !== 'confirming' ? (
          <button
            onClick={() => setDeleteOrgStatus('confirming')}
            className="text-[10px] font-bold bg-danger/10 text-danger border border-danger/20 px-4 py-1.5 rounded uppercase tracking-wider hover:bg-danger/20 transition-colors"
          >
            Delete Organisation
          </button>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-danger font-bold">Type <span className="underline italic">{orgName}</span> to confirm:</p>
            <input
              type="text"
              value={deleteOrgInput}
              onChange={e => setDeleteOrgInput(e.target.value)}
              placeholder={orgName}
              className="w-full bg-surface border border-danger/30 rounded px-3 py-2 text-xs text-bright focus:outline-none focus:border-danger"
            />
            <div className="flex gap-3">
              <button
                disabled={!orgName || deleteOrgInput !== orgName || deleteOrgStatus === 'deleting'}
                onClick={onDeleteOrg}
                className="text-[10px] font-bold bg-danger text-white px-4 py-1.5 rounded uppercase tracking-wider hover:bg-danger/90 transition-colors disabled:opacity-40"
              >
                {deleteOrgStatus === 'deleting' ? 'Deleting…' : deleteOrgStatus === 'done' ? 'Deleted' : deleteOrgStatus === 'error' ? '✗ Error' : 'Confirm Delete'}
              </button>
              <button
                onClick={() => { setDeleteOrgStatus(null); setDeleteOrgInput(''); }}
                className="text-[10px] font-bold text-muted border border-border px-4 py-1.5 rounded uppercase tracking-wider hover:text-bright transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  </section>
);

// ── Data Region Panel ──────────────────────────────────────────────────────────
export const DataRegionPanel = ({ dataRegion, setDataRegion, regionSaveStatus, onSave }) => (
  <section className="panel p-6">
    <div className="flex items-center mb-4">
      <Server className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Data Region</h3>
    </div>
    <p className="text-xs text-muted mb-4">Select where your organisation&apos;s data is processed and stored. Changing this affects compliance reporting.</p>
    <div className="space-y-3">
      <select
        value={dataRegion}
        onChange={e => setDataRegion(e.target.value)}
        className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent transition-colors"
      >
        <option value="global">Global (No Restriction)</option>
        <option value="eu">EU / EEA (GDPR)</option>
        <option value="us">United States</option>
        <option value="apac">Asia-Pacific</option>
        <option value="uk">United Kingdom</option>
      </select>
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted">
          {dataRegion === 'eu' && 'Data stays within EU/EEA boundaries (GDPR compliant)'}
          {dataRegion === 'us' && 'Data processed in US data centres'}
          {dataRegion === 'apac' && 'Data processed in Asia-Pacific region'}
          {dataRegion === 'uk' && 'Data processed in UK (post-Brexit GDPR)'}
          {dataRegion === 'global' && 'No geographic restriction — lowest latency routing'}
        </span>
        <button
          onClick={onSave}
          disabled={regionSaveStatus === 'saving'}
          className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-3 py-1 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors disabled:opacity-50"
        >
          {regionSaveStatus === 'saving' ? '...' : regionSaveStatus === 'saved' ? '✓ Saved' : regionSaveStatus === 'error' ? '✗ Error' : 'Save Region'}
        </button>
      </div>
    </div>
  </section>
);
