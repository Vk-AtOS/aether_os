import React, { useState, useEffect } from 'react';
import { api } from '../api';

const Compliance = () => {
  const [runs, setRuns] = useState([]);
  const [orgReport, setOrgReport] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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
        setRuns(Array.isArray(runsData) ? runsData : (runsData?.runs ?? []));
        setOrgReport(reportRes.data ?? null);
        const logsData = logsRes.data;
        setAuditLogs(Array.isArray(logsData) ? logsData : (logsData?.logs ?? []));
      } catch (e) {
        console.error('Failed to load compliance data', e);
        setError('Failed to load compliance data. Please try again.');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const downloadArtifacts = (runId) => {
    // Must go through /api/ prefix so nginx proxies to uvicorn
    const token = api.getToken();
    window.location.href = `/api/compliance/artifacts/${runId}?token=${encodeURIComponent(token ?? '')}`;
  };

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
        <span className="ml-3 text-gray-500">Loading compliance data…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded p-4 text-red-700">{error}</div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-8">
      <h1 className="text-2xl font-bold">Compliance</h1>

      <div className="bg-white p-4 border rounded shadow">
        <h2 className="text-xl font-bold mb-2">EU AI Act Classification</h2>
        <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded">Medium Risk</span>
      </div>

      <div className="bg-white p-4 border rounded shadow">
        <h2 className="text-xl font-bold mb-4">Org Compliance Report</h2>
        {orgReport ? (
          <pre className="bg-gray-100 p-2 text-sm overflow-auto max-h-64">
            {JSON.stringify(orgReport, null, 2)}
          </pre>
        ) : (
          <p className="text-gray-400 text-sm">No report data available.</p>
        )}
      </div>

      <div className="bg-white p-4 border rounded shadow">
        <h2 className="text-xl font-bold mb-4">Recent Runs Compliance</h2>
        {runs.length === 0 ? (
          <p className="text-gray-400 text-sm">No runs found.</p>
        ) : (
          runs.map(run => (
            <div key={run.id} className="flex justify-between items-center py-2 border-b">
              <span className="font-mono text-sm">{run.id}</span>
              <button
                onClick={() => downloadArtifacts(run.id)}
                className="text-blue-500 hover:underline text-sm"
              >
                Download ZIP
              </button>
            </div>
          ))
        )}
      </div>

      <div className="bg-white p-4 border rounded shadow">
        <h2 className="text-xl font-bold mb-4">Audit Logs</h2>
        {auditLogs.length === 0 ? (
          <p className="text-gray-400 text-sm">No audit logs found.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-gray-50">
                <th className="text-left py-2 px-1">Time</th>
                <th className="text-left py-2 px-1">Action</th>
                <th className="text-left py-2 px-1">Resource</th>
                <th className="text-left py-2 px-1">User</th>
              </tr>
            </thead>
            <tbody>
              {auditLogs.map((log, i) => (
                <tr key={i} className="border-b hover:bg-gray-50">
                  <td className="py-1 px-1 font-mono text-xs">{log.timestamp}</td>
                  <td className="py-1 px-1">{log.action}</td>
                  <td className="py-1 px-1">{log.resource_type}</td>
                  <td className="py-1 px-1">{log.user}</td>
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
