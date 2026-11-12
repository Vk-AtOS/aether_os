import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api';
import { Monitor, Smartphone, Tablet, Save, ChevronRight, Layout, Palette, Layers, Grid } from 'lucide-react';
import { apiError } from '../apiError';

const LAYOUTS = [
  { id: 'sidebar-dashboard', label: 'Sidebar Dashboard', desc: 'Left nav + main content area' },
  { id: 'topbar-dashboard', label: 'Top Nav Dashboard', desc: 'Header nav + content panels' },
  { id: 'landing-page', label: 'Landing Page', desc: 'Hero, features, pricing, CTA' },
  { id: 'docs-site', label: 'Documentation Site', desc: 'Sidebar TOC + content' },
  { id: 'admin-panel', label: 'Admin Panel', desc: 'Data-heavy tables and forms' },
];

const COLOR_THEMES = [
  { id: 'dark-indigo', label: 'Dark Indigo', primary: '#6366f1', bg: '#0a0a0f', surface: '#14141f' },
  { id: 'dark-emerald', label: 'Dark Emerald', primary: '#10b981', bg: '#020c07', surface: '#071910' },
  { id: 'dark-rose', label: 'Dark Rose', primary: '#f43f5e', bg: '#0f050a', surface: '#1a0810' },
  { id: 'light-blue', label: 'Light Blue', primary: '#3b82f6', bg: '#f8fafc', surface: '#ffffff' },
  { id: 'light-purple', label: 'Light Purple', primary: '#8b5cf6', bg: '#faf9ff', surface: '#ffffff' },
];

const COMPONENT_LIBRARY = [
  { id: 'shadcn-ui', label: 'shadcn/ui', desc: 'Radix primitives + Tailwind' },
  { id: 'headlessui', label: 'Headless UI', desc: 'Unstyled accessible components' },
  { id: 'mui', label: 'Material UI', desc: 'Google Material Design' },
  { id: 'antd', label: 'Ant Design', desc: 'Enterprise-grade components' },
  { id: 'none', label: 'Tailwind only', desc: 'Pure utility classes' },
];

const DEFAULT_PAGES = [
  { name: 'Dashboard', route: '/', components: ['StatsCard', 'Chart', 'Table'] },
  { name: 'Settings', route: '/settings', components: ['Form', 'Toggle'] },
];

const FrontendBuilder = () => {
  const { id: runId } = useParams();

  const [spec, setSpec] = useState({
    framework: 'react',
    styling: 'tailwindcss',
    layout: 'sidebar-dashboard',
    color_theme: COLOR_THEMES[0],
    pages: DEFAULT_PAGES,
    authentication: true,
    responsive: true,
    dark_mode: true,
    component_library: 'shadcn-ui',
  });
  const [preview, setPreview] = useState('desktop');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [loading, setLoading] = useState(Boolean(runId));
  const [newPage, setNewPage] = useState({ name: '', route: '' });

  useEffect(() => {
    if (!runId) return;
    api.client.get(`/factory/runs/${runId}/frontend-spec`)
      .then(r => { if (r.data?.spec && Object.keys(r.data.spec).length) setSpec(r.data.spec); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [runId]);

  const handleSave = async () => {
    setSaving(true);
    setSaveError('');
    try {
      if (runId) {
        await api.client.post(`/factory/runs/${runId}/frontend-spec`, { spec });
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setSaveError('Save failed: ' + (apiError(e) || e.message));
    } finally {
      setSaving(false);
    }
  };

  const addPage = () => {
    if (!newPage.name || !newPage.route) return;
    setSpec(s => ({ ...s, pages: [...s.pages, { ...newPage, components: [] }] }));
    setNewPage({ name: '', route: '' });
  };

  const removePage = (i) => setSpec(s => ({ ...s, pages: s.pages.filter((_, idx) => idx !== i) }));

  if (loading) return (
    <div className="p-6 flex items-center justify-center text-muted">
      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-accent mr-3" />
      Loading spec…
    </div>
  );

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Layout className="w-6 h-6 text-accent" /> Frontend Builder
          </h1>
          {runId && <p className="text-muted text-sm mt-1">Spec for run <span className="font-mono">{runId}</span></p>}
        </div>
        <button
          onClick={handleSave}
          disabled={saving || !runId}
          title={!runId ? 'Save is disabled until you open this page from a project run' : undefined}
          className="flex items-center gap-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white font-bold px-4 py-2 rounded-lg text-sm transition-colors"
        >
          <Save className="w-4 h-4" />
          {saving ? 'Saving…' : saved ? 'Saved!' : 'Save Spec'}
        </button>
      </div>

      {saveError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded p-3 text-danger text-sm flex items-center gap-2">
          <span className="flex-1">{saveError}</span>
          <button onClick={() => setSaveError('')} className="text-muted hover:text-bright">✕</button>
        </div>
      )}

      {!runId && (
        <div className="bg-yellow-900/20 border border-yellow-700/40 rounded p-3 text-yellow-400 text-sm">
          Open this page from a project run to save the spec. Browsing in preview-only mode.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Layout */}
        <section className="bg-panel border border-border rounded-lg p-5">
          <h2 className="font-bold mb-4 flex items-center gap-2 text-sm uppercase tracking-wider text-muted">
            <Grid className="w-4 h-4" /> Layout
          </h2>
          <div className="space-y-2">
            {LAYOUTS.map(l => (
              <label key={l.id} className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                spec.layout === l.id ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/40'
              }`}>
                <input
                  type="radio"
                  name="layout"
                  value={l.id}
                  checked={spec.layout === l.id}
                  onChange={() => setSpec(s => ({ ...s, layout: l.id }))}
                  className="accent-accent"
                />
                <div>
                  <div className="font-medium text-sm">{l.label}</div>
                  <div className="text-xs text-muted">{l.desc}</div>
                </div>
              </label>
            ))}
          </div>
        </section>

        {/* Color Theme */}
        <section className="bg-panel border border-border rounded-lg p-5">
          <h2 className="font-bold mb-4 flex items-center gap-2 text-sm uppercase tracking-wider text-muted">
            <Palette className="w-4 h-4" /> Color Theme
          </h2>
          <div className="space-y-2">
            {COLOR_THEMES.map(t => (
              <label key={t.id} className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                spec.color_theme?.id === t.id ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/40'
              }`}>
                <input
                  type="radio"
                  name="theme"
                  value={t.id}
                  checked={spec.color_theme?.id === t.id}
                  onChange={() => setSpec(s => ({ ...s, color_theme: t }))}
                  className="accent-accent"
                />
                <div
                  className="w-6 h-6 rounded-full border-2 border-white/20 shrink-0"
                  style={{ backgroundColor: t.primary }}
                />
                <div className="font-medium text-sm">{t.label}</div>
              </label>
            ))}
          </div>
        </section>

        {/* Component Library */}
        <section className="bg-panel border border-border rounded-lg p-5">
          <h2 className="font-bold mb-4 flex items-center gap-2 text-sm uppercase tracking-wider text-muted">
            <Layers className="w-4 h-4" /> Component Library
          </h2>
          <div className="space-y-2">
            {COMPONENT_LIBRARY.map(c => (
              <label key={c.id} className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                spec.component_library === c.id ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/40'
              }`}>
                <input
                  type="radio"
                  name="complib"
                  value={c.id}
                  checked={spec.component_library === c.id}
                  onChange={() => setSpec(s => ({ ...s, component_library: c.id }))}
                  className="accent-accent"
                />
                <div>
                  <div className="font-medium text-sm">{c.label}</div>
                  <div className="text-xs text-muted">{c.desc}</div>
                </div>
              </label>
            ))}
          </div>
        </section>

        {/* Options */}
        <section className="bg-panel border border-border rounded-lg p-5 space-y-4">
          <h2 className="font-bold mb-4 flex items-center gap-2 text-sm uppercase tracking-wider text-muted">
            <Monitor className="w-4 h-4" /> Options
          </h2>
          {[
            { key: 'authentication', label: 'Authentication', desc: 'Login / signup flow' },
            { key: 'responsive', label: 'Responsive', desc: 'Mobile + tablet breakpoints' },
            { key: 'dark_mode', label: 'Dark Mode', desc: 'Dark theme by default' },
          ].map(o => (
            <label key={o.key} className="flex items-center justify-between cursor-pointer">
              <div>
                <div className="text-sm font-medium">{o.label}</div>
                <div className="text-xs text-muted">{o.desc}</div>
              </div>
              <div
                onClick={() => setSpec(s => ({ ...s, [o.key]: !s[o.key] }))}
                className={`w-10 h-5 rounded-full transition-colors relative cursor-pointer ${spec[o.key] ? 'bg-accent' : 'bg-border'}`}
              >
                <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-all ${spec[o.key] ? 'left-5' : 'left-0.5'}`} />
              </div>
            </label>
          ))}

          <div className="pt-4 border-t border-border">
            <div className="text-xs text-muted uppercase tracking-wider mb-2">Preview</div>
            <div className="flex gap-2">
              {[
                { id: 'desktop', Icon: Monitor },
                { id: 'tablet', Icon: Tablet },
                { id: 'mobile', Icon: Smartphone },
              ].map(({ id, Icon }) => (
                <button
                  key={id}
                  onClick={() => setPreview(id)}
                  className={`p-2 rounded border transition-colors ${preview === id ? 'border-accent text-accent bg-accent/10' : 'border-border text-muted hover:border-accent/40'}`}
                >
                  <Icon className="w-4 h-4" />
                </button>
              ))}
            </div>
          </div>
        </section>
      </div>

      {/* Pages */}
      <section className="bg-panel border border-border rounded-lg p-5">
        <h2 className="font-bold mb-4 text-sm uppercase tracking-wider text-muted">Pages</h2>
        <div className="space-y-2 mb-4">
          {spec.pages.map((page, i) => (
            <div key={i} className="flex items-center justify-between p-3 bg-surface border border-border rounded-lg">
              <div className="flex items-center gap-3">
                <ChevronRight className="w-4 h-4 text-accent" />
                <div>
                  <span className="font-medium text-sm">{page.name}</span>
                  <span className="font-mono text-xs text-muted ml-3">{page.route}</span>
                </div>
              </div>
              <button onClick={() => removePage(i)} className="text-xs text-muted hover:text-danger transition-colors">Remove</button>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={newPage.name}
            onChange={e => setNewPage(p => ({ ...p, name: e.target.value }))}
            placeholder="Page name"
            className="bg-surface border border-border rounded px-3 py-1.5 text-sm text-bright focus:outline-none focus:border-accent flex-1"
          />
          <input
            value={newPage.route}
            onChange={e => setNewPage(p => ({ ...p, route: e.target.value }))}
            placeholder="/route"
            className="bg-surface border border-border rounded px-3 py-1.5 text-sm text-bright focus:outline-none focus:border-accent w-32 font-mono"
          />
          <button
            onClick={addPage}
            disabled={!newPage.name || !newPage.route}
            className="bg-accent hover:bg-accent/90 disabled:opacity-40 text-white text-sm font-bold px-3 py-1.5 rounded transition-colors"
          >
            Add
          </button>
        </div>
      </section>

      {/* Spec preview */}
      <section className="bg-panel border border-border rounded-lg p-5">
        <h2 className="font-bold mb-3 text-sm uppercase tracking-wider text-muted">Generated Spec</h2>
        <pre className="bg-surface border border-border rounded p-3 text-xs text-bright overflow-auto max-h-64 font-mono">
          {JSON.stringify(spec, null, 2)}
        </pre>
      </section>
    </div>
  );
};

export default FrontendBuilder;
