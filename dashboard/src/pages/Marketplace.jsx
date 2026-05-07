import React, { useState, useEffect } from 'react';
import axios from 'axios';

const Marketplace = () => {
  const [profiles, setProfiles] = useState([]);
  const [search, setSearch] = useState('');

  useEffect(() => {
    axios.get('/marketplace/profiles').then(res => setProfiles(res.data));
  }, []);

  const filtered = profiles.filter(p => p.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Marketplace</h1>
      <input 
        type="text" 
        placeholder="Search..." 
        className="border p-2 w-full rounded"
        value={search}
        onChange={e => setSearch(e.target.value)}
      />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {filtered.map(p => (
          <div key={p.id} className="border p-4 rounded shadow">
            <h3 className="font-bold">{p.name}</h3>
            <span className="text-xs bg-gray-200 px-1 rounded">{p.base_domain}</span>
            <p className="text-sm mt-2">{p.description}</p>
            <div className="mt-4 flex justify-between">
              <span className="font-bold">{p.price === 0 ? 'Free' : `$${p.price}`}</span>
              <span className="text-xs text-gray-500">{p.usage_count} uses</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default Marketplace;
