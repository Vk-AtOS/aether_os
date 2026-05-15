import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api';
import { Database, Plus, Trash2, Save, Shield, CheckCircle2, AlertCircle, Server } from 'lucide-react';

const FRAMEWORKS = ['fastapi', 'express', 'django', 'rails', 'spring-boot', 'nestjs'];
const DATABASES = ['postgresql', 'mysql', 'mongodb', 'sqlite', 'mssql'];
const ORMS = { postgresql: ['sqlalchemy', 'tortoise-orm', 'prisma'], mysql: ['sqlalchemy', 'prisma', 'typeorm'], mongodb: ['mongoengine', 'beanie', 'motor'], sqlite: ['sqlalchemy', 'prisma'], mssql: ['sqlalchemy', 'prisma'] };
const AUTH_METHODS = ['jwt', 'sessions', 'oauth2', 'api_key', 'saml'];
const FIELD_TYPES = ['string', 'integer', 'float', 'boolean', 'datetime', 'uuid', 'text', 'json'];

const defaultSpec = () => ({
  framework: 'fastapi',
  database: 'postgresql',
  orm: 'sqlalchemy',
  authentication: 'jwt',
  entities: [
    {
      name: 'User',
      fields: [
        { name: 'id', type: 'uuid', primary_key: true },
        { name: 'email', type: 'string', unique: true, max_length: 255 },
        { name: 'created_at', type: 'datetime', auto: true },
      ],
    },
  ],
  endpoints: [
    { method: 'GET', path: '/users', auth: true, pagination: true },
    { method: 'POST', path: '/users', auth: true, validate: true },
  ],
  cors_origins: [],
  rate_limiting: true,
  async: true,
});

const BackendBuilder = () => {
  const { id: runId } = useParams();
  const [spec, setSpec] = useState(defaultSpec());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [validation, setValidation] = useState(null);
  const [activeEntity, setActiveEntity] = useState(0);
  const [newEndpoint, setNewEndpoint] = useState({ method: 'GET', path: '', auth: true, pagination: false, validate: false });

  useEffect(() => {
    if (!runId) { setLoading(false); return; }
    api.client.get(`/factory/runs/${runId}/backend-spec`)
      .then(r => { if (r.data?.spec && Object.keys(r.data.spec).length) setSpec(r.data.spec); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [runId]);

  const handleSave = async () => {
    setSaving(true);
    try {
      if (runId) {
        await api.client.post(`/factory/runs/${runId}/backend-spec`, { spec });
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      alert('Save failed: ' + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async () => {
    if (!runId) return;
    try {
      const r = await api.client.post(`/factory/runs/${runId}/validate-spec`, { spec });
      setValidation(r.data);
    } catch (e) {
      alert('Validation failed');
    }
  };

  const addEntity = () => {
    const name = prompt('Entity name (PascalCase):');
    if (!name) return;
    setSpec(s => ({
      ...s,
      entities: [...s.entities, { name, fields: [{ name: 'id', type: 'uuid', primary_key: true }] }],
    }));
    setActiveEntity(spec.entities.length);
  };

  const removeEntity = (i) => {
    setSpec(s => ({ ...s, entities: s.entities.filter((_, idx) => idx !== i) }));
    setActiveEntity(0);
  };

  const addField = (entityIdx) => {
    setSpec(s => {
      const entities = [...s.entities];
      entities[entityIdx] = {
        ...entities[entityIdx],
        fields: [...entities[entityIdx].fields, { name: '', type: 'string' }],
      };
      return { ...s, entities };
    });
  };

  const updateField = (entityIdx, fieldIdx, key, value) => {
    setSpec(s => {
      const entities = s.entities.map((e, ei) => ei !== entityIdx ? e : {
        ...e,
        fields: e.fields.map((f, fi) => fi !== fieldIdx ? f : { ...f, [key]: value }),
      });
      return { ...s, entities };
    });
  };

  const removeField = (entityIdx, fieldIdx) => {
    setSpec(s => {
      const entities = s.entities.map((e, ei) => ei !== entityIdx ? e : {
        ...e,
        fields: e.fields.filter((_, fi) => fi !== fieldIdx),
      });
      return { ...s, entities };
    });
  };

  const addEndpoint = () => {
    if (!newEndpoint.path) return;
    setSpec(s => ({ ...s, endpoints: [...s.endpoints, { ...newEndpoint }] }));
    setNewEndpoint({ method: 'GET', path: '', auth: true, pagination: false, validate: false });
  };

  const removeEndpoint = (i) => setSpec(s => ({ ...s, endpoints: s.endpoints.filter((_, idx) => idx !== i) }));

  if (loading) return (
    <div className="p-6 flex items-center justify-center text-muted">
      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-accent mr-3" />
      Loading spec…
    </div>
  );

  const entity = spec.entities[activeEntity];

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Database className="w-6 h-6 text-accent" /> Backend Builder
          </h1>
          {runId && <p className="text-muted text-sm mt-1">Schema for run <span className="font-mono">{runId}</span></p>}
        </div>
        <div className="flex gap-2">
          {runId && (
            <button
              onClick={handleValidate}
              className="flex items-center gap-2 border border-border hover:border-accent/50 text-muted hover:text-bright font-bold px-4 py-2 rounded-lg text-sm transition-colors"
            >
              <CheckCircle2 className="w-4 h-4" /> Validate
            </button>
          )}
          <button
            onClick={handleSave}
            disabled={saving || !runId}
            className="flex items-center gap-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white font-bold px-4 py-2 rounded-lg text-sm transition-colors"
          >
            <Save className="w-4 h-4" />
            {saving ? 'Saving…' : saved ? 'Saved!' : 'Save Spec'}
          </button>
        </div>
      </div>

      {validation && (
        <div className={`flex items-start gap-3 p-3 rounded border text-sm ${validation.valid ? 'bg-green-900/20 border-green-700/40 text-green-400' : 'bg-red-900/20 border-red-700/40 text-red-400'}`}>
          {validation.valid ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /> : <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />}
          <div>
            {validation.valid ? 'Spec is valid.' : (
              <ul className="list-disc list-inside space-y-0.5">
                {validation.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* Stack config */}
      <section className="bg-panel border border-border rounded-lg p-5">
        <h2 className="font-bold mb-4 flex items-center gap-2 text-sm uppercase tracking-wider text-muted">
          <Server className="w-4 h-4" /> Stack
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { key: 'framework', label: 'Framework', options: FRAMEWORKS },
            { key: 'database', label: 'Database', options: DATABASES },
            { key: 'orm', label: 'ORM', options: ORMS[spec.database] || ['sqlalchemy'] },
            { key: 'authentication', label: 'Auth Method', options: AUTH_METHODS },
          ].map(({ key, label, options }) => (
            <div key={key}>
              <label className="text-xs text-muted uppercase tracking-wider block mb-1">{label}</label>
              <select
                value={spec[key]}
                onChange={e => setSpec(s => ({ ...s, [key]: e.target.value }))}
                className="w-full bg-surface border border-border rounded px-2 py-1.5 text-sm text-bright focus:outline-none focus:border-accent"
              >
                {options.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          ))}
        </div>
        <div className="flex gap-6 mt-4">
          {[
            { key: 'rate_limiting', label: 'Rate Limiting' },
            { key: 'async', label: 'Async' },
          ].map(({ key, label }) => (
            <label key={key} className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={!!spec[key]}
                onChange={e => setSpec(s => ({ ...s, [key]: e.target.checked }))}
                className="accent-accent"
              />
              {label}
            </label>
          ))}
        </div>
      </section>

      {/* Entity / Field editor */}
      <div className="grid grid-cols-3 gap-4">
        <section className="bg-panel border border-border rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-bold text-sm uppercase tracking-wider text-muted">Entities</h2>
            <button onClick={addEntity} className="text-accent hover:text-accent/80 text-xs font-bold">+ Add</button>
          </div>
          <div className="space-y-1">
            {spec.entities.map((e, i) => (
              <div
                key={i}
                className={`flex items-center justify-between p-2 rounded cursor-pointer transition-colors ${activeEntity === i ? 'bg-accent/20 border border-accent/40' : 'hover:bg-surface border border-transparent'}`}
                onClick={() => setActiveEntity(i)}
              >
                <span className="font-mono text-sm">{e.name}</span>
                <button onClick={ev => { ev.stopPropagation(); removeEntity(i); }} className="text-muted hover:text-danger text-xs">×</button>
              </div>
            ))}
          </div>
        </section>

        {entity && (
          <section className="col-span-2 bg-panel border border-border rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-bold text-sm uppercase tracking-wider text-muted">
                {entity.name} — Fields
              </h2>
              <button onClick={() => addField(activeEntity)} className="text-accent hover:text-accent/80 text-xs font-bold flex items-center gap-1">
                <Plus className="w-3 h-3" /> Add Field
              </button>
            </div>
            <div className="space-y-2">
              {entity.fields.map((f, fi) => (
                <div key={fi} className="flex items-center gap-2">
                  <input
                    value={f.name}
                    onChange={e => updateField(activeEntity, fi, 'name', e.target.value)}
                    placeholder="field_name"
                    className="bg-surface border border-border rounded px-2 py-1 text-sm font-mono text-bright focus:outline-none focus:border-accent flex-1"
                  />
                  <select
                    value={f.type}
                    onChange={e => updateField(activeEntity, fi, 'type', e.target.value)}
                    className="bg-surface border border-border rounded px-2 py-1 text-sm text-bright focus:outline-none focus:border-accent"
                  >
                    {FIELD_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                  <label className="flex items-center gap-1 text-xs text-muted cursor-pointer whitespace-nowrap">
                    <input type="checkbox" checked={!!f.primary_key} onChange={e => updateField(activeEntity, fi, 'primary_key', e.target.checked)} className="accent-accent" />
                    PK
                  </label>
                  <label className="flex items-center gap-1 text-xs text-muted cursor-pointer whitespace-nowrap">
                    <input type="checkbox" checked={!!f.unique} onChange={e => updateField(activeEntity, fi, 'unique', e.target.checked)} className="accent-accent" />
                    Unique
                  </label>
                  <button onClick={() => removeField(activeEntity, fi)} className="text-muted hover:text-danger transition-colors">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>

      {/* Endpoints */}
      <section className="bg-panel border border-border rounded-lg p-5">
        <h2 className="font-bold mb-4 flex items-center gap-2 text-sm uppercase tracking-wider text-muted">
          <Shield className="w-4 h-4" /> API Endpoints
        </h2>
        <div className="space-y-2 mb-4">
          {spec.endpoints.map((ep, i) => (
            <div key={i} className="flex items-center gap-3 p-2 bg-surface border border-border rounded text-sm">
              <span className={`font-bold font-mono text-xs w-12 text-center rounded px-1 py-0.5 ${
                ep.method === 'GET' ? 'bg-green-900/40 text-green-400' :
                ep.method === 'POST' ? 'bg-blue-900/40 text-blue-400' :
                ep.method === 'PUT' ? 'bg-yellow-900/40 text-yellow-400' :
                'bg-red-900/40 text-red-400'
              }`}>{ep.method}</span>
              <span className="font-mono flex-1">{ep.path}</span>
              {ep.auth && <span className="text-xs bg-accent/20 text-accent px-1.5 py-0.5 rounded">auth</span>}
              {ep.pagination && <span className="text-xs bg-surface border border-border px-1.5 py-0.5 rounded text-muted">paginated</span>}
              <button onClick={() => removeEndpoint(i)} className="text-muted hover:text-danger ml-auto">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <select
            value={newEndpoint.method}
            onChange={e => setNewEndpoint(p => ({ ...p, method: e.target.value }))}
            className="bg-surface border border-border rounded px-2 py-1.5 text-sm text-bright focus:outline-none focus:border-accent"
          >
            {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map(m => <option key={m}>{m}</option>)}
          </select>
          <input
            value={newEndpoint.path}
            onChange={e => setNewEndpoint(p => ({ ...p, path: e.target.value }))}
            placeholder="/resource"
            className="bg-surface border border-border rounded px-3 py-1.5 text-sm font-mono text-bright focus:outline-none focus:border-accent flex-1"
          />
          <label className="flex items-center gap-1 text-xs text-muted cursor-pointer">
            <input type="checkbox" checked={newEndpoint.auth} onChange={e => setNewEndpoint(p => ({ ...p, auth: e.target.checked }))} className="accent-accent" />
            Auth
          </label>
          <button
            onClick={addEndpoint}
            disabled={!newEndpoint.path}
            className="bg-accent hover:bg-accent/90 disabled:opacity-40 text-white text-sm font-bold px-3 py-1.5 rounded transition-colors"
          >
            Add
          </button>
        </div>
      </section>

      {/* Spec JSON */}
      <section className="bg-panel border border-border rounded-lg p-5">
        <h2 className="font-bold mb-3 text-sm uppercase tracking-wider text-muted">Generated Spec</h2>
        <pre className="bg-surface border border-border rounded p-3 text-xs text-bright overflow-auto max-h-64 font-mono">
          {JSON.stringify(spec, null, 2)}
        </pre>
      </section>
    </div>
  );
};

export default BackendBuilder;
