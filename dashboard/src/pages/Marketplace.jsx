import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { Search, Package, Star, Zap, Shield, Database, Cpu, Globe, PlusCircle, X, Loader2, CheckCircle2 } from 'lucide-react';

const CATEGORY_ICONS = {
  auth: Shield,
  backend: Database,
  frontend: Globe,
  performance: Zap,
  ai: Cpu,
  default: Package,
};

const DOMAINS = ['general', 'auth', 'backend', 'frontend', 'performance', 'ai'];

const BLANK_FORM = { name: '', base_domain: 'general', description: '', price_usd: '0' };

const Marketplace = () => {
  const [profiles, setProfiles] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showPublish, setShowPublish] = useState(false);
  const [form, setForm] = useState(BLANK_FORM);
  const [publishing, setPublishing] = useState(false);
  const [publishSuccess, setPublishSuccess] = useState(null);

  const fetchProfiles = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getMarketplaceProfiles?.() ?? { data: [] };
      const data = res.data;
      setProfiles(Array.isArray(data) ? data : (data?.items ?? data?.profiles ?? []));
    } catch (err) {
      console.error('Failed to load marketplace profiles', err);
      setError('Failed to load marketplace. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchProfiles(); }, [fetchProfiles]);

  const handlePublish = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setPublishing(true);
    setPublishSuccess(null);
    try {
      const res = await api.client.post('/marketplace/publish', {
        name: form.name.trim(),
        base_domain: form.base_domain,
        description: form.description.trim(),
        price_usd: parseFloat(form.price_usd) || 0,
      });
      setPublishSuccess(res.data.name);
      setForm(BLANK_FORM);
      setShowPublish(false);
      fetchProfiles();
    } catch (err) {
      setError('Publish failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setPublishing(false);
    }
  };

  const filtered = profiles.filter(p =>
    !search || p.name?.toLowerCase().includes(search.toLowerCase()) ||
    p.description?.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center space-x-2 text-muted">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-accent" />
        <span>Loading marketplace…</span>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright">Marketplace</h1>
          <p className="text-sm text-muted mt-0.5">{filtered.length} skills available</p>
        </div>
        <button
          onClick={() => { setShowPublish(v => !v); setPublishSuccess(null); }}
          className="flex items-center gap-2 bg-accent hover:bg-accent/90 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors"
        >
          <PlusCircle className="w-3.5 h-3.5" /> Publish Skill
        </button>
      </div>

      {publishSuccess && (
        <div className="flex items-center gap-3 p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400 text-sm">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
          <span><strong>{publishSuccess}</strong> published to marketplace.</span>
          <button onClick={() => setPublishSuccess(null)} className="ml-auto text-muted hover:text-bright">✕</button>
        </div>
      )}

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-danger text-sm flex items-center gap-2">
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="text-muted hover:text-bright">✕</button>
        </div>
      )}

      {/* Publish form */}
      {showPublish && (
        <section className="panel p-6 border-accent/20 bg-accent/5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Publish a New Skill</h3>
            <button onClick={() => setShowPublish(false)} className="text-muted hover:text-bright">
              <X className="w-4 h-4" />
            </button>
          </div>
          <form onSubmit={handlePublish} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Name *</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  placeholder="My Awesome Skill"
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                  required
                  autoFocus
                />
              </div>
              <div>
                <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Category</label>
                <select
                  value={form.base_domain}
                  onChange={e => setForm(f => ({ ...f, base_domain: e.target.value }))}
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                >
                  {DOMAINS.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Description</label>
              <textarea
                value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                placeholder="Briefly describe what this skill does…"
                rows={3}
                className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent resize-none"
              />
            </div>
            <div className="flex items-end gap-4">
              <div className="w-40">
                <label className="text-[10px] font-bold text-muted uppercase tracking-wider mb-1 block">Price (USD)</label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.price_usd}
                  onChange={e => setForm(f => ({ ...f, price_usd: e.target.value }))}
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                />
              </div>
              <button
                type="submit"
                disabled={publishing || !form.name.trim()}
                className="flex items-center gap-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold px-5 py-2 rounded-lg transition-colors uppercase tracking-wider"
              >
                {publishing ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Publishing…</> : 'Publish'}
              </button>
              <button type="button" onClick={() => setShowPublish(false)} className="text-xs text-muted hover:text-bright transition-colors">
                Cancel
              </button>
            </div>
          </form>
        </section>
      )}

      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
        <input
          type="text"
          placeholder="Search skills, connectors, plugins…"
          className="bg-panel border border-border p-2 pl-9 w-full rounded-lg focus:outline-none focus:ring-1 focus:ring-accent text-bright placeholder-muted text-sm"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-16 text-muted">
          <Package className="w-12 h-12 mx-auto mb-4 opacity-30" />
          <p className="font-medium">No items found{search ? ` for "${search}"` : ''}.</p>
          <p className="text-sm mt-1">Publish a skill above — it will appear here once added.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(p => {
            const Icon = CATEGORY_ICONS[p.base_domain] ?? CATEGORY_ICONS.default;
            return (
              <div key={p.id} className="panel p-5 hover:border-accent/30 transition-all">
                <div className="flex items-start space-x-3 mb-3">
                  <div className="p-2 bg-accent/10 rounded-lg shrink-0">
                    <Icon className="w-5 h-5 text-accent" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-bold truncate text-bright">{p.name}</h3>
                    <span className="text-xs bg-border/50 text-muted px-2 py-0.5 rounded-full">{p.base_domain}</span>
                  </div>
                </div>
                <p className="text-sm text-muted line-clamp-2">{p.description}</p>
                <div className="mt-4 flex items-center justify-between">
                  <span className="font-bold text-sm">
                    {(p.price_usd ?? p.price) === 0 ? (
                      <span className="text-emerald-400">Free</span>
                    ) : (
                      <span className="text-bright">${p.price_usd ?? p.price}</span>
                    )}
                  </span>
                  <div className="flex items-center space-x-3 text-xs text-muted">
                    {p.rating && (
                      <span className="flex items-center space-x-1">
                        <Star className="w-3 h-3 text-yellow-400 fill-yellow-400" />
                        <span>{p.rating}</span>
                      </span>
                    )}
                    <span>{p.usage_count ?? 0} uses</span>
                  </div>
                </div>
                <button
                  className="mt-3 w-full py-1.5 bg-accent hover:bg-accent/90 text-white text-sm font-medium rounded-lg transition-colors"
                  onClick={async () => {
                    try {
                      await api.client.post(`/marketplace/install/${p.id}`);
                      alert(`${p.name} installed successfully`);
                    } catch (err) {
                      alert('Install failed: ' + (err.response?.data?.detail || err.message));
                    }
                  }}
                >
                  Install
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default Marketplace;
