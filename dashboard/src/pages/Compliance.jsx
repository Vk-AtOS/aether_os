import React, { useState, useEffect } from 'react';
import { api } from '../api';

const Compliance = () => {
  const [runs, setRuns] = useState([]);
  const [orgReport, setOrgReport] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [runsRes, reportRes, logsRes] = await Promise.all([
          api.listRuns(),
          api.get('/compliance/org-report'),
          api.get('/audit/logs')
        ]);
        setRuns(runsRes.data);
        setOrgReport(reportRes.data);
        setAuditLogs(logsRes.data);
      } catch (e) {
        console.error("Failed to load compliance data", e);
      }
    };
    fetchData();
  }, []);

  const downloadArtifacts = (runId) => {
    window.location.href = `/compliance/artifacts/${runId}`;
  };

  return (
    <div className="p-6 space-y-8">
      <h1 className="text-2xl font-bold">Compliance</h1>
      
      <div className="bg-white p-4 border rounded shadow">
        <h2 className="text-xl font-bold mb-2">EU AI Act Classification</h2>
        <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded">Medium Risk</span>
      </div>

      <div className="bg-white p-4 border rounded shadow">
        <h2 className="text-xl font-bold mb-4">Org Compliance Report</h2>
        {orgReport && <pre className="bg-gray-100 p-2 text-sm">{JSON.stringify(orgReport, null, 2)}</pre>}
      </div>

      <div className="bg-white p-4 border rounded shadow">
        <h2 className="text-xl font-bold mb-4">Recent Runs Compliance</h2>
        {runs.map(run => (
          <div key={run.id} className="flex justify-between items-center py-2 border-b">
            <span>{run.id}</span>
            <button onClick={() => downloadArtifacts(run.id)} className="text-blue-500 hover:underline">Download ZIP</button>
          </div>
        ))}
      </div>

      <div className="bg-white p-4 border rounded shadow">
        <h2 className="text-xl font-bold mb-4">Audit Logs</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b">
              <th className="text-left">Time</th>
              <th className="text-left">Action</th>
              <th className="text-left">Resource</th>
              <th className="text-left">User</th>
            </tr>
          </thead>
          <tbody>
            {auditLogs.map((log, i) => (
              <tr key={i} className="border-b">
                <td>{log.timestamp}</td>
                <td>{log.action}</td>
                <td>{log.resource_type}</td>
                <td>{log.user}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default Compliance;
