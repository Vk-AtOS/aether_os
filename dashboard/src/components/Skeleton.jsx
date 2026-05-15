import React from 'react';

export const SkeletonLine = ({ width = 'w-full', height = 'h-4', className = '' }) => (
  <div className={`${width} ${height} bg-border/40 rounded animate-pulse ${className}`} />
);

export const SkeletonCard = ({ rows = 3 }) => (
  <div className="panel p-6 space-y-3">
    {Array.from({ length: rows }).map((_, i) => (
      <SkeletonLine key={i} width={i === 0 ? 'w-1/2' : i === rows - 1 ? 'w-3/4' : 'w-full'} />
    ))}
  </div>
);

export const SkeletonRow = ({ cols = 5 }) => (
  <tr className="border-b border-border">
    {Array.from({ length: cols }).map((_, i) => (
      <td key={i} className="px-6 py-4">
        <div className="h-4 bg-border/40 rounded animate-pulse" style={{ width: `${60 + (i % 3) * 20}%` }} />
      </td>
    ))}
  </tr>
);

export const SkeletonTable = ({ rows = 5, cols = 5 }) => (
  <div className="panel overflow-hidden">
    <table className="w-full">
      <tbody>
        {Array.from({ length: rows }).map((_, i) => (
          <SkeletonRow key={i} cols={cols} />
        ))}
      </tbody>
    </table>
  </div>
);

const Skeleton = { Line: SkeletonLine, Card: SkeletonCard, Row: SkeletonRow, Table: SkeletonTable };
export default Skeleton;
