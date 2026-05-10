import React, { useState, useEffect } from 'react';
import { api } from '../api';

const StorageWidget = () => {
  const [data, setData] = useState({ used: 0, limit: 1 });

  useEffect(() => {
    // Use api.client (axios instance) — api.get() does not exist on the api object
    api.client.get('/account/storage')
      .then(res => setData(res.data))
      .catch(() => {}); // Storage widget is non-critical; fail silently
  }, []);

  const pct = Math.min((data.used / Math.max(data.limit, 1)) * 100, 100);
  const color = pct < 70 ? 'bg-green-500' : pct < 90 ? 'bg-amber-500' : 'bg-red-500';

  return (
    <div className="bg-white p-4 border rounded shadow w-full max-w-sm">
      <div className="flex justify-between text-sm mb-1">
        <span>Storage</span>
        <span>{pct.toFixed(0)}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div className={`${color} h-2 rounded-full`} style={{ width: `${pct}%` }}></div>
      </div>
      <div className="text-xs text-gray-500 mt-2">
        {data.used}MB used of {data.limit}MB
      </div>
    </div>
  );
};

export default StorageWidget;
