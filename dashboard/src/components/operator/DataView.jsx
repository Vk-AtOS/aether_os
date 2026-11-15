import React from 'react';

const cell = (v) => (v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v));

// Read-only table for operator data of unknown shape: an array of objects becomes rows,
// an object becomes key/value rows (nested objects are shown as JSON).
const DataView = ({ data }) => {
  if (data == null) return null;
  if (Array.isArray(data)) {
    if (data.length === 0) return <p className="text-xs text-muted">Nothing recorded.</p>;
    const cols = [...new Set(data.flatMap((r) => (r && typeof r === 'object' ? Object.keys(r) : [])))];
    return (
      <div className="overflow-x-auto"><table className="w-full text-xs">
        <thead><tr>{cols.map((c) => <th key={c} className="text-left text-[10px] uppercase text-muted pr-4 pb-1">{c}</th>)}</tr></thead>
        <tbody>{data.slice(0, 200).map((r, i) => (
          <tr key={i} className="border-t border-border">{cols.map((c) => <td key={c} className="pr-4 py-1 text-bright align-top">{cell(r?.[c])}</td>)}</tr>
        ))}</tbody>
      </table></div>
    );
  }
  if (typeof data === 'object') {
    return (
      <table className="w-full text-xs"><tbody>
        {Object.entries(data).map(([k, v]) => (
          <tr key={k} className="border-t border-border"><td className="pr-4 py-1 text-muted align-top">{k}</td><td className="py-1 text-bright break-all">{cell(v)}</td></tr>
        ))}
      </tbody></table>
    );
  }
  return <span className="text-xs text-bright">{cell(data)}</span>;
};

export default DataView;
