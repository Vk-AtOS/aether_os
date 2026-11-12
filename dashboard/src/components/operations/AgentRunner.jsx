import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, Play, Clock } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';
import { parseSignature, buildArgs } from './signature';

const input = 'w-full bg-surface border border-border rounded-lg px-3 py-1.5 text-xs text-bright font-mono focus:outline-none focus:border-accent';

// One method: a form made from its signature. Read methods run and show the result; act
// methods are sent to Velaris, which holds them until a person approves them in the Prime inbox.
const MethodForm = ({ agent, method }) => {
  const fields = useMemo(() => parseSignature(method.signature || ''), [method.signature]);
  const [values, setValues] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [out, setOut] = useState(null);

  const run = async (e) => {
    e.preventDefault();
    setBusy(true); setError(''); setOut(null);
    try {
      const res = await api.callVelarisAgent(agent, method.name, buildArgs(fields, values));
      setOut({ status: res.status, data: res.data });
    } catch (err) {
      setError(err instanceof SyntaxError ? 'A list or object field is not valid JSON.' : apiError(err) || 'The call failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={run} className="space-y-2 border-t border-border pt-3">
      <p className="text-xs text-muted">{method.summary}</p>
      {fields.map((f) => (
        <div key={f.name}>
          <label htmlFor={`${agent}-${method.name}-${f.name}`} className="text-[10px] font-bold text-muted uppercase tracking-wider">
            {f.name}{f.required ? ' *' : ''} <span className="normal-case font-normal">{f.type}</span>
          </label>
          {f.kind === 'bool' ? (
            <select id={`${agent}-${method.name}-${f.name}`} className={input} value={values[f.name] || ''}
                    onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
              <option value="">(default)</option><option value="true">true</option><option value="false">false</option>
            </select>
          ) : (
            <input id={`${agent}-${method.name}-${f.name}`} className={input} value={values[f.name] || ''}
                   type={f.kind === 'number' ? 'number' : 'text'} step="any" required={f.required}
                   onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
          )}
        </div>
      ))}
      <button type="submit" disabled={busy}
              className="flex items-center gap-2 px-3 py-1.5 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold rounded-lg">
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
        {method.http === 'act' ? 'Request approval' : 'Run'}
      </button>
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      {out && out.status === 202 && (
        <p className="flex items-center gap-2 text-xs text-yellow-400">
          <Clock className="w-3.5 h-3.5" aria-hidden="true" />
          Waiting for approval. <Link to="/prime/inbox" className="underline">Open the Prime inbox</Link>
        </p>
      )}
      {out && out.status !== 202 && (
        <pre className="bg-surface border border-border rounded-lg p-3 text-xs text-bright font-mono overflow-x-auto whitespace-pre-wrap break-all">
          {JSON.stringify(out.data.result ?? out.data, null, 2)}
        </pre>
      )}
    </form>
  );
};

// Only methods on Velaris's own HTTP allowlist (http = read or act) can be run from here.
const AgentRunner = ({ agent }) => {
  const callable = (agent.methods || []).filter((m) => m.http === 'read' || m.http === 'act');
  const [open, setOpen] = useState(null);
  if (callable.length === 0) return <p className="text-xs text-muted">No methods of this agent can be run from here.</p>;
  return (
    <ul className="space-y-2">
      {callable.map((m) => (
        <li key={m.name} className="bg-surface/50 border border-border rounded-lg px-3 py-2">
          <button type="button" onClick={() => setOpen(open === m.name ? null : m.name)} aria-expanded={open === m.name}
                  className="w-full flex items-center gap-2 text-left">
            <span className="text-xs font-mono text-bright">{m.name}</span>
            <span className={`ml-auto text-[10px] ${m.http === 'act' ? 'text-yellow-400' : 'text-emerald-400'}`}>
              {m.http === 'act' ? 'needs approval' : 'read'}
            </span>
          </button>
          {open === m.name && <MethodForm agent={agent.name} method={m} />}
        </li>
      ))}
    </ul>
  );
};

export default AgentRunner;
