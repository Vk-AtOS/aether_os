import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { Download, ChevronDown, ChevronRight, CheckCircle2, XCircle, Clock, Loader2 } from 'lucide-react';

const INDIA_FRAMEWORKS = [
  {
    id: 'dpdp',
    name: 'DPDP Act 2023',
    full: 'Digital Personal Data Protection Act 2023',
    regulator: 'Ministry of Electronics & IT (MeitY)',
    summary: 'Governs collection, processing, and transfer of digital personal data of Indian residents.',
    obligations: [
      'Notice & explicit consent for each purpose of processing',
      'Children\'s data: verifiable parental consent, no tracking/behavioural advertising',
      'Cross-border transfers only to GoI-whitelisted countries',
      'Significant Data Fiduciaries (health, finance, biometric): DPO + annual DPIA + audit',
      'Data Principal rights: access, correction, erasure, grievance redress within 30 days',
      'Breach notification to Data Protection Board within 72 hours',
    ],
    risk: 'HIGH',
    effectiveDate: '2023 (rules pending)',
    penaltyMax: '₹250 crore per violation',
  },
  {
    id: 'it_act',
    name: 'IT Act 2000 / SPDI Rules',
    full: 'Information Technology Act 2000 §43A + SPDI Rules 2011',
    regulator: 'Ministry of Electronics & IT (MeitY)',
    summary: 'Mandates reasonable security practices for handling Sensitive Personal Data or Information (SPDI).',
    obligations: [
      'Publish a privacy policy covering data collected, purpose, retention',
      'Obtain consent before collecting SPDI (passwords, financials, health, biometric)',
      'Implement IS/ISO 27001 or equivalent security standard',
      'Provide data subject rights: review, correct, withdraw consent',
      'Corporate liability for data breaches due to negligence',
    ],
    risk: 'MEDIUM',
    effectiveDate: '2011',
    penaltyMax: 'Civil liability (no fixed cap); criminal provisions under §66',
  },
  {
    id: 'rbi',
    name: 'RBI Data Localisation',
    full: 'RBI Payment System Data Localisation Directive + Master Directions',
    regulator: 'Reserve Bank of India',
    summary: 'Payment system data must be stored exclusively within India; international mirroring allowed only for cross-border transactions.',
    obligations: [
      'Store entire payment transaction data (end-to-end) only in India',
      'International transaction leg may be mirrored abroad; Indian copy mandatory',
      'Maintain immutable audit trail for 5+ years',
      'Fraud risk management system (FRMS) mandatory for payment aggregators',
      'Report fraud incidents to RBI within 6 hours',
      'Annual system audit by CERT-In empanelled auditor',
    ],
    risk: 'CRITICAL',
    effectiveDate: '2018',
    penaltyMax: 'License revocation + ₹10 lakh/day fine',
  },
  {
    id: 'sebi',
    name: 'SEBI CSCRF 2024',
    full: 'SEBI Cybersecurity and Cyber Resilience Framework 2024',
    regulator: 'Securities and Exchange Board of India',
    summary: 'NIST CSF-aligned cybersecurity framework mandatory for Market Infrastructure Institutions and Registered Intermediaries.',
    obligations: [
      'Implement NIST CSF-aligned controls (Identify, Protect, Detect, Respond, Recover)',
      'Establish and operate a Security Operations Centre (SOC)',
      'Annual penetration testing by CERT-In empanelled auditor',
      'Report cyber incidents to SEBI within 6 hours',
      'Store trade data and client records in India',
      'Business Continuity Plan (BCP) with RTO ≤ 4 hours',
      'Third-party/vendor risk management program',
    ],
    risk: 'HIGH',
    effectiveDate: 'January 2025',
    penaltyMax: '₹25 crore + suspension of registration',
  },
  {
    id: 'certIn',
    name: 'CERT-In Directions 2022',
    full: 'CERT-In Cyber Security Directions 2022',
    regulator: 'Indian Computer Emergency Response Team (CERT-In)',
    summary: 'Mandatory incident reporting and log retention obligations for all entities operating ICT infrastructure in India.',
    obligations: [
      'Report all cybersecurity incidents to CERT-In within 6 hours of detection',
      'Maintain ICT system logs for minimum 180 days within India',
      'Clock synchronisation with NTP servers traceable to NTP.GOV.IN',
      'VPN/cloud service providers: retain subscriber data 5 years',
      'Virtual asset exchanges: maintain KYC + transaction records 5 years',
    ],
    risk: 'MEDIUM',
    effectiveDate: 'June 2022',
    penaltyMax: '₹1 lakh/day fine; imprisonment up to 1 year',
  },
];

const RISK_STYLES = {
  CRITICAL: 'bg-red-900/30 text-red-300 border-red-700/50',
  HIGH:     'bg-orange-900/30 text-orange-300 border-orange-700/50',
  MEDIUM:   'bg-yellow-900/30 text-yellow-300 border-yellow-700/50',
  LOW:      'bg-green-900/30 text-green-300 border-green-700/50',
};

function IndiaCompliancePanel() {
  const [expanded, setExpanded] = useState(null);
  return (
    <div className="bg-panel p-4 border border-border rounded shadow space-y-4">
      <div className="flex items-center gap-3">
        <span className="text-2xl">🇮🇳</span>
        <div>
          <h2 className="text-xl font-bold">India Compliance</h2>
          <p className="text-xs text-muted">DPDP Act 2023 · IT Act 2000 · RBI · SEBI CSCRF 2024 · CERT-In 2022</p>
        </div>
      </div>
      <div className="space-y-2">
        {INDIA_FRAMEWORKS.map(fw => (
          <div key={fw.id} className={`border rounded overflow-hidden ${RISK_STYLES[fw.risk]?.split(' ').slice(2).join(' ') || 'border-border'}`}>
            <button
              className="w-full flex justify-between items-center px-4 py-3 text-left hover:bg-white/5 transition-colors"
              onClick={() => setExpanded(expanded === fw.id ? null : fw.id)}
            >
              <div className="flex items-center gap-3">
                <span className={`text-xs font-bold px-2 py-0.5 rounded border ${RISK_STYLES[fw.risk] || ''}`}>{fw.risk}</span>
                <div>
                  <div className="font-semibold text-sm">{fw.name}</div>
                  <div className="text-xs text-muted">{fw.regulator}</div>
                </div>
              </div>
              <span className="text-muted text-xs">{expanded === fw.id ? '▲' : '▼'}</span>
            </button>
            {expanded === fw.id && (
              <div className="px-4 pb-4 space-y-3 border-t border-border/40 pt-3">
                <p className="text-sm text-muted">{fw.summary}</p>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div><span className="text-muted">Effective:</span> <span className="text-bright">{fw.effectiveDate}</span></div>
                  <div><span className="text-muted">Max Penalty:</span> <span className="text-bright">{fw.penaltyMax}</span></div>
                </div>
                <div>
                  <div className="text-xs text-muted uppercase font-bold mb-1">Key Obligations</div>
                  <ul className="space-y-1">
                    {fw.obligations.map((o, i) => (
                      <li key={i} className="text-xs flex gap-2">
                        <span className="text-accent mt-0.5 shrink-0">•</span>
                        <span className="text-bright/80">{o}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="text-xs text-muted italic">{fw.full}</div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const STATUS_META = {
  completed: { icon: CheckCircle2, color: 'text-emerald-400' },
  failed:    { icon: XCircle,      color: 'text-red-400' },
  running:   { icon: Loader2,      color: 'text-accent animate-spin' },
  pending:   { icon: Clock,        color: 'text-yellow-400' },
};

const RunArtifactRow = ({ run, onDownload }) => {
  const [open, setOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const runId = run.run_id || run.id;
  const status = run.status || 'unknown';
  const meta = STATUS_META[status] || { icon: Clock, color: 'text-muted' };
  const StatusIcon = meta.icon;

  const handleDownload = async () => {
    setDownloading(true);
    try { await onDownload(runId); } finally { setDownloading(false); }
  };

  return (
    <div className="border border-border rounded-lg overflow-hidden mb-2">
      <button
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface/50 transition-colors text-left"
        onClick={() => setOpen(v => !v)}
      >
        {open ? <ChevronDown className="w-3.5 h-3.5 text-muted shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-muted shrink-0" />}
        <StatusIcon className={`w-3.5 h-3.5 shrink-0 ${meta.color}`} />
        <span className="font-mono text-sm text-bright flex-1 truncate">{runId}</span>
        {run.domain && <span className="text-[10px] font-bold bg-accent/10 text-accent px-2 py-0.5 rounded-full">{run.domain}</span>}
        <span className={`text-[10px] font-bold uppercase tracking-wider ${meta.color}`}>{status}</span>
        <button
          onClick={e => { e.stopPropagation(); handleDownload(); }}
          disabled={downloading}
          className="flex items-center gap-1.5 text-xs text-accent hover:text-bright border border-accent/30 hover:border-accent px-3 py-1 rounded transition-colors disabled:opacity-50 ml-2 shrink-0"
        >
          {downloading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
          {downloading ? 'Downloading…' : 'Artifacts ZIP'}
        </button>
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1 border-t border-border/40 grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: 'Run ID',    value: runId },
            { label: 'Status',    value: status },
            { label: 'Domain',    value: run.domain || '—' },
            { label: 'Model',     value: run.model || run.llm_model || '—' },
            { label: 'Started',   value: run.started_at ? new Date(run.started_at * 1000).toLocaleString() : (run.created_at ? new Date(run.created_at).toLocaleString() : '—') },
            { label: 'Finished',  value: run.finished_at ? new Date(run.finished_at * 1000).toLocaleString() : '—' },
            { label: 'Phases',    value: run.phases_completed ?? run.phase ?? '—' },
            { label: 'Artifacts', value: run.artifact_count ?? '—' },
          ].map(({ label, value }) => (
            <div key={label} className="space-y-0.5">
              <div className="text-[10px] font-bold text-muted uppercase tracking-wider">{label}</div>
              <div className="text-xs text-bright font-mono truncate">{String(value)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const Compliance = () => {
  const [runs, setRuns] = useState([]);
  const [orgReport, setOrgReport] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [downloadError, setDownloadError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const [runsRes, reportRes, logsRes] = await Promise.all([
          api.listRuns(),
          api.getComplianceReport(),
          api.getAuditLogs(),
        ]);
        // Normalize — backend may return array directly or {runs:[...]}
        const runsData = runsRes.data;
        // Handle paginated {items:[...]} or legacy array or {runs:[...]}
        setRuns(Array.isArray(runsData) ? runsData : (runsData?.items ?? runsData?.runs ?? []));
        setOrgReport(reportRes.data ?? null);
        const logsData = logsRes.data;
        setAuditLogs(Array.isArray(logsData) ? logsData : (logsData?.logs ?? []));
      } catch (e) {
        if (import.meta.env.DEV) console.error('Failed to load compliance data', e);
        setError('Failed to load compliance data. Please try again.');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const downloadArtifacts = async (runId) => {
    setDownloadError(null);
    try {
      const res = await api.client.get(`/compliance/artifacts/${runId}`, { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = `artifacts-${runId}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setDownloadError('Artifact download failed. The run may still be in progress.');
    }
  };

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
        <span className="ml-3 text-muted">Loading compliance data…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-900/20 border border-red-700/50 rounded p-4 text-red-400">{error}</div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-8">
      <h1 className="text-2xl font-bold">Compliance</h1>
      {downloadError && (
        <div className="flex items-center gap-3 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <span className="flex-1">{downloadError}</span>
          <button onClick={() => setDownloadError(null)} className="text-muted hover:text-bright">✕</button>
        </div>
      )}

      <IndiaCompliancePanel />

      <div className="bg-panel p-4 border border-border rounded shadow">
        <h2 className="text-xl font-bold mb-2">EU AI Act Classification</h2>
        {(() => {
          const risk = orgReport?.eu_ai_act_risk || 'UNKNOWN';
          const styles = {
            HIGH: 'bg-red-900/30 text-red-400',
            LIMITED: 'bg-yellow-900/30 text-yellow-400',
            MINIMAL: 'bg-green-900/30 text-green-400',
            UNKNOWN: 'bg-gray-900/30 text-gray-400',
          };
          return (
            <span className={`px-2 py-1 rounded text-sm font-medium ${styles[risk] || styles.UNKNOWN}`}>
              {risk}
            </span>
          );
        })()}
      </div>

      <div className="bg-panel p-4 border border-border rounded shadow">
        <h2 className="text-xl font-bold mb-4">Org Compliance Report</h2>
        {orgReport ? (
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-xs text-muted uppercase font-bold mb-1">Total Runs</div>
              <div className="text-2xl font-bold text-bright">{orgReport.total_runs ?? 0}</div>
            </div>
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-xs text-muted uppercase font-bold mb-1">Decision Approval Rate</div>
              <div className="text-2xl font-bold text-bright">{((orgReport.decision_approval_rate ?? 0) * 100).toFixed(0)}%</div>
            </div>
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-xs text-muted uppercase font-bold mb-1">Security Scans</div>
              <div className="text-bright">{orgReport.security_scan_summary?.scans_run ?? 0} scans · {orgReport.security_scan_summary?.issues_found ?? 0} issues</div>
            </div>
            <div className="bg-surface border border-border rounded p-3">
              <div className="text-xs text-muted uppercase font-bold mb-1">Data Regions</div>
              <div className="text-bright">{(orgReport.data_processing_locations ?? []).join(', ') || '—'}</div>
            </div>
            {orgReport.models_used?.length > 0 && (
              <div className="bg-surface border border-border rounded p-3 col-span-2">
                <div className="text-xs text-muted uppercase font-bold mb-2">Models Used</div>
                <div className="flex flex-wrap gap-2">
                  {orgReport.models_used.map(m => (
                    <span key={m} className="px-2 py-0.5 bg-accent/10 text-accent rounded text-xs font-mono">{m}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="text-muted text-sm">No report data available.</p>
        )}
      </div>

      <div className="bg-panel p-4 border border-border rounded shadow">
        <h2 className="text-xl font-bold mb-4">Recent Runs — Compliance Artifacts</h2>
        {runs.length === 0 ? (
          <p className="text-muted text-sm">No runs found. Start a pipeline to generate compliance artifacts.</p>
        ) : (
          <div className="space-y-1">
            {runs.map(run => (
              <RunArtifactRow key={run.run_id || run.id} run={run} onDownload={downloadArtifacts} />
            ))}
          </div>
        )}
      </div>

      <div className="bg-panel p-4 border border-border rounded shadow">
        <h2 className="text-xl font-bold mb-4">Audit Logs</h2>
        {auditLogs.length === 0 ? (
          <p className="text-muted text-sm">No audit logs found.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-surface">
                <th className="text-left py-2 px-1 text-muted font-medium">Time</th>
                <th className="text-left py-2 px-1 text-muted font-medium">Action</th>
                <th className="text-left py-2 px-1 text-muted font-medium">Resource</th>
                <th className="text-left py-2 px-1 text-muted font-medium">User</th>
              </tr>
            </thead>
            <tbody>
              {auditLogs.map((log, i) => (
                <tr key={i} className="border-b border-border hover:bg-surface">
                  <td className="py-1 px-1 font-mono text-xs text-muted">{log.created_at ? new Date(log.created_at * 1000).toLocaleString() : '—'}</td>
                  <td className="py-1 px-1">{log.action}</td>
                  <td className="py-1 px-1">{log.resource_type}</td>
                  <td className="py-1 px-1">{log.user_id || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

export default Compliance;
