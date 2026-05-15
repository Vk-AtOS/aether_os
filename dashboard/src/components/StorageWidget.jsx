import React, { useState, useEffect } from 'react';
import { api } from '../api';

const StorageWidget = () => {
  const [data, setData] = useState({ used_mb: 0, limit_mb: 1, percent_used: 0 });

  useEffect(() => {
    api.client.get('/account/storage')
      .then(res => setData(res.data))
      .catch(() => {});
  }, []);

  const pct = Math.min(data.percent_used ?? (data.used_mb / Math.max(data.limit_mb, 1)) * 100, 100);
  const color = pct < 70 ? 'bg-green-500' : pct < 90 ? 'bg-amber-500' : 'bg-red-500';

  return (
    <div className="panel p-4 w-full">
      <div className="flex justify-between text-sm mb-1">
        <span className="text-muted font-medium">Storage</span>
        <span className="text-bright font-bold">{pct.toFixed(0)}%</span>
      </div>
      <div className="w-full bg-border/40 rounded-full h-2">
        <div className={`${color} h-2 rounded-full transition-all`} style={{ width: `${pct}%` }}></div>
      </div>
      <div className="text-xs text-muted mt-2">
        {data.used_mb?.toFixed(1) ?? 0}MB used of {data.limit_mb ?? '—'}MB
      </div>
    </div>
  );
};

export default StorageWidget;
