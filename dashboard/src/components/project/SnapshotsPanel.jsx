import React, { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import { api } from '../../api';
import { apiError } from '../../apiError';

// Saved versions of a run's files. Read-only: there is no restore endpoint, so this lets you read a version
// and copy it, it does not roll anything back.
const SnapshotsPanel = ({ runId }) => {
  const [state, setState] = useState({ loading: true, items: [], error: null });
  const [open, setOpen] = useState(null);
  useEffect(() => {
    let live = true;
    api.listSnapshots(runId)
      .then((res) => live && setState({ loading: false, items: res.data?.snapshots ?? [], error: null }))
      .catch((e) => live && setState({ loading: false, items: [], error: apiError(e) || 'Could not load snapshots.' }));
    return () => { live = false; };
  }, [runId]);

  const show = async (s) => {
    setOpen({ id: s.id, loading: true });
    try { setOpen({ id: s.id, content: (await api.getSnapshot(runId, s.id)).data.content }); }
    catch (e) { setOpen({ id: s.id, error: apiError(e) || 'Could not load this snapshot.' }); }
  };

  if (state.loading) return <div className="p-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-accent" /></div>;
  if (state.error) return <div role="alert" className="m-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-danger text-xs">{state.error}</div>;
  if (state.items.length === 0) return <p className="p-8 text-center text-sm text-muted">No snapshots were saved for this run.</p>;
  return (
    <div className="p-4 space-y-2" style={{ minHeight: '420px' }}>
      {state.items.map((s) => (
        <div key={s.id} className="border border-border rounded-lg">
          <button onClick={() => show(s)} className="w-full flex justify-between px-3 py-2 text-xs text-bright">
            <span className="font-mono">{s.file_path}</span><span className="text-muted">{s.created_at ? new Date(s.created_at * 1000).toLocaleString() : ''}</span>
          </button>
          {open?.id === s.id && (open.loading ? <Loader2 className="m-3 w-4 h-4 animate-spin text-accent" />
            : open.error ? <p role="alert" className="px-3 pb-3 text-xs text-danger">{open.error}</p>
            : <pre className="px-3 pb-3 text-[11px] text-muted overflow-x-auto max-h-80">{open.content}</pre>)}
        </div>
      ))}
    </div>
  );
};

export default SnapshotsPanel;
