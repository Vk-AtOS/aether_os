import React, { useState } from 'react';
import { api } from '../api';
import { apiError } from '../apiError';

const input = 'w-full bg-surface border border-border rounded-lg px-3 py-2 text-xs text-bright';
const FIELDS = {
  salesforce: [['instance_url', 'Instance URL', 'text'], ['access_token', 'Access token', 'password']],
  ldap: [['server', 'Server', 'text'], ['bind_dn', 'Bind DN', 'text'], ['bind_password', 'Bind password', 'password'], ['base_dn', 'Base DN', 'text']],
};

// Validate credentials and browse what a Salesforce or LDAP connector can see. The stored config is masked, so the
// credentials are typed here, used for this one request and never saved or shown again. Direct user login against
// LDAP and SOQL queries stay API-only on purpose: a password prompt and a free query box are not a browse feature.
const ConnectorExplore = ({ pluginId }) => {
  const [v, setV] = useState({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const fields = FIELDS[pluginId];
  if (!fields) return null;

  const call = async (label, fn) => {
    setBusy(true); setError(null); setResult(null);
    try { setResult({ label, data: (await fn()).data }); }
    catch (e) { setError(apiError(e) || `${label} failed`); }
    finally { setBusy(false); }
  };
  const sf = { instance_url: v.instance_url || '', access_token: v.access_token || '' };
  const ldap = { server: v.server || '', bind_dn: v.bind_dn || '', bind_password: v.bind_password || '' };

  return (
    <div className="mt-3 pt-3 border-t border-border space-y-2" data-testid="explore">
      <h4 className="text-[10px] font-bold uppercase tracking-widest text-muted">Validate and explore</h4>
      {fields.map(([k, label, type]) => (
        <input key={k} aria-label={label} type={type} autoComplete="off" placeholder={label} className={input}
          value={v[k] || ''} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
      ))}
      <div className="flex gap-2">
        {pluginId === 'salesforce' ? (
          <>
            <button disabled={busy} className="text-xs px-3 py-1.5 bg-blue-950/40 text-blue-400 rounded-lg" onClick={() => call('Validate', () => api.salesforceValidate(sf))}>Validate</button>
            <button disabled={busy} className="text-xs px-3 py-1.5 bg-blue-950/40 text-blue-400 rounded-lg" onClick={() => call('Objects', () => api.salesforceObjects(sf))}>List objects</button>
          </>
        ) : (
          <>
            <button disabled={busy} className="text-xs px-3 py-1.5 bg-blue-950/40 text-blue-400 rounded-lg" onClick={() => call('Validate', () => api.ldapValidate(ldap))}>Validate</button>
            <button disabled={busy} className="text-xs px-3 py-1.5 bg-blue-950/40 text-blue-400 rounded-lg" onClick={() => call('Users', () => api.ldapUsers({ ...ldap, base_dn: v.base_dn || '', max_results: 50 }))}>List users</button>
          </>
        )}
      </div>
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      {result && (
        <div role="status" className="text-xs">
          {result.data?.ok === false ? <p className="text-danger">{result.data.message}</p>
            : <pre className="bg-surface border border-border rounded-lg p-2 overflow-auto max-h-60 text-[11px] text-muted">{JSON.stringify(result.data, null, 2)}</pre>}
        </div>
      )}
    </div>
  );
};

export default ConnectorExplore;
