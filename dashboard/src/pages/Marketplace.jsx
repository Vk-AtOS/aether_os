import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { Search, Package, Star, Zap, Shield, Database, Cpu, Globe } from 'lucide-react';

const CATEGORY_ICONS = {
  auth: Shield,
  backend: Database,
  frontend: Globe,
  performance: Zap,
  ai: Cpu,
  default: Package,
};

const Marketplace = () => {
  const [profiles, setProfiles] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    // FIXED: was bare axios.get('/marketplace/profiles') — no /api/ prefix, no auth token.
    // Always 401. Now uses api client which has both the prefix and the bearer token.
    const fetchProfiles = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.getMarketplaceProfiles?.() ?? { data: [] };
        const data = res.data;
        setProfiles(Array.isArray(data) ? data : (data?.profiles ?? []));
      } catch (err) {
        console.error('Failed to load marketplace profiles', err);
        setError('Failed to load marketplace. Please try again.');
      } finally {
        setLoading(false);
      }
    };
    fetchProfiles();
  }, []);

  const filtered = profiles.filter(p =>
    !search || p.name?.toLowerCase().includes(search.toLowerCase()) ||
    p.description?.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center space-x-2 text-muted">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500" />
        <span>Loading marketplace…</span>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Marketplace</h1>
        <span className="text-sm text-gray-400">{filtered.length} skills available</span>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-red-700 text-sm">{error}</div>
      )}

      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          placeholder="Search skills, connectors, plugins…"
          className="border p-2 pl-9 w-full rounded focus:outline-none focus:ring-2 focus:ring-blue-400"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <Package className="w-12 h-12 mx-auto mb-4 opacity-30" />
          <p className="font-medium">No items found{search ? ` for "${search}"` : ''}.</p>
          <p className="text-sm mt-1">Skills and connectors will appear here once added.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(p => {
            const Icon = CATEGORY_ICONS[p.base_domain] ?? CATEGORY_ICONS.default;
            return (
              <div key={p.id} className="border rounded-lg p-5 shadow-sm hover:shadow-md transition-shadow bg-white">
                <div className="flex items-start space-x-3 mb-3">
                  <div className="p-2 bg-blue-50 rounded-lg shrink-0">
                    <Icon className="w-5 h-5 text-blue-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-bold truncate">{p.name}</h3>
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{p.base_domain}</span>
                  </div>
                </div>
                <p className="text-sm text-gray-600 line-clamp-2">{p.description}</p>
                <div className="mt-4 flex items-center justify-between">
                  <span className="font-bold text-sm">
                    {p.price === 0 ? (
                      <span className="text-green-600">Free</span>
                    ) : (
                      <span>${p.price}</span>
                    )}
                  </span>
                  <div className="flex items-center space-x-3 text-xs text-gray-400">
                    {p.rating && (
                      <span className="flex items-center space-x-1">
                        <Star className="w-3 h-3 text-yellow-400 fill-yellow-400" />
                        <span>{p.rating}</span>
                      </span>
                    )}
                    <span>{p.usage_count ?? 0} uses</span>
                  </div>
                </div>
                <button className="mt-3 w-full py-1.5 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-700 transition-colors">
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
