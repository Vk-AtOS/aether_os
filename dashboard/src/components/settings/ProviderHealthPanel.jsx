import React, { useCallback, useEffect, useState } from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import { api } from '../../api';
import { healthText, keyStatusText, providerError } from './providerHelpers';

const TONE = { healthy: 'text-emerald-400', degraded: 'text-yellow-400', down: 'text-danger', unknown: 'text-muted' };

// Key presence and router health (AHM score, circuit breaker) per provider. Adding, rotating and testing a key
// are on the API key panel above; this panel never receives or shows a key.
const ProviderHealthPanel = ({ isAdmin }) => {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const load = useCallback(() => api.getProviderStatus()
    .then((r) => { setError(''); setRows(r.data.providers); })
    .catch((e) => setError(providerError(e, 'Could not load provider health.'))), []);
  useEffect(() => {
    if (!isAdmin) return undefined;
    let alive = true;
    api.getProviderStatus().then((r) => { if (alive) setRows(r.data.providers); })
      .catch((e) => { if (alive) setError(providerError(e, 'Could not load provider health.')); });
    return () => { alive = false; };
  }, [isAdmin]);
  if (!isAdmin) return null;

  return (
    <section className="panel overflow-hidden" aria-labelledby="prov-health-h">
      <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
        <Activity className="w-4 h-4 mr-2 text-accent" />
        <h3 id="prov-health-h" className="text-xs font-bold text-muted uppercase tracking-widest">Provider health</h3>
        <button type="button" onClick={load} className="ml-auto text-xs text-muted flex items-center gap-1" aria-label="Refresh provider health">
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
      </div>
      <div className="p-6 space-y-3">
        {error && <p role="alert" className="text-xs text-danger">{error}</p>}
        <ul className="space-y-3">
          {(rows || []).map((p) => (
            <li key={p.id} className="border border-border rounded-lg p-3 flex flex-wrap items-center gap-x-4 gap-y-1" data-provider={p.id}>
              <span className="text-sm text-bright font-bold">{p.label}</span>
              <span className={`text-xs font-bold ${TONE[p.health.state]}`}>{healthText(p.health)}</span>
              {p.health.score != null && <span className="text-[10px] text-muted font-mono">score {p.health.score}</span>}
              <span className="text-xs text-muted basis-full">{keyStatusText(p)}{p.endpoint_host ? ` · endpoint ${p.endpoint_host}` : ''}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
};

export default ProviderHealthPanel;
