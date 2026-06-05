import React from 'react';

export const CardSkeleton = ({ count = 4 }) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    {Array.from({length: count}).map((_, i) => (
      <div key={i} className="bg-surface border border-border rounded-xl p-5 animate-pulse space-y-3">
        <div className="h-4 w-24 bg-border/40 rounded" />
        <div className="h-8 w-16 bg-border/30 rounded" />
        <div className="h-3 w-32 bg-border/20 rounded" />
      </div>
    ))}
  </div>
);

export const TableSkeleton = ({ rows = 5 }) => (
  <div className="space-y-2 animate-pulse">
    <div className="h-10 bg-border/30 rounded-lg" />
    {Array.from({length: rows}).map((_, i) => (
      <div key={i} className="h-14 bg-border/20 rounded-lg" style={{opacity: 1 - i * 0.12}} />
    ))}
  </div>
);

export const PageLoader = () => (
  <div className="space-y-6 animate-pulse">
    <div className="flex justify-between">
      <div className="h-7 w-56 bg-border/40 rounded-lg" />
      <div className="h-8 w-28 bg-border/30 rounded-lg" />
    </div>
    <CardSkeleton count={4} />
    <TableSkeleton rows={6} />
  </div>
);
