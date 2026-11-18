import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { Plus, Trash2, FolderOpen, Users, Globe, Loader2, Pencil } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import { apiError } from '../apiError';

const Workspaces = () => {
  const [workspaces, setWorkspaces] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  // Create modal state
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({ name: '', description: '', is_shared: false });
  const [createStatus, setCreateStatus] = useState(null); // null|'saving'|'error'

  // Confirm delete
  const [confirmDelete, setConfirmDelete] = useState(null); // workspace object
  const [deleteStatus, setDeleteStatus] = useState({}); // { [id]: 'deleting' }

  // Edit modal state
  const [editingWs, setEditingWs] = useState(null); // workspace object being edited
  const [editForm, setEditForm] = useState({ name: '', description: '', is_shared: false });
  const [editStatus, setEditStatus] = useState(null); // null|'saving'|'error'

  // Promise chain with no state set before the request: this runs from an effect.
  const loadWorkspaces = useCallback(() => api.getWorkspaces()
    .then((res) => { setWorkspaces(res.data || []); setError(null); })
    .catch((err) => setError(apiError(err) || 'Failed to load workspaces'))
    .finally(() => setLoading(false)), []);

  useEffect(() => { loadWorkspaces(); }, [loadWorkspaces]);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!createForm.name.trim()) return;
    setCreateStatus('saving');
    try {
      await api.createWorkspace(createForm);
      setCreateForm({ name: '', description: '', is_shared: false });
      setShowCreate(false);
      setCreateStatus(null);
      await loadWorkspaces();
    } catch {
      setCreateStatus('error');
      setTimeout(() => setCreateStatus(null), 3000);
    }
  };

  const handleDelete = async (workspace) => {
    setDeleteStatus(s => ({ ...s, [workspace.id]: 'deleting' }));
    try {
      await api.deleteWorkspace(workspace.id);
      setWorkspaces(ws => ws.filter(w => w.id !== workspace.id));
    } catch (err) {
      setError(apiError(err) || 'Failed to delete workspace');
    } finally {
      setDeleteStatus(s => { const n = { ...s }; delete n[workspace.id]; return n; });
      setConfirmDelete(null);
    }
  };

  const handleEdit = async (e) => {
    e.preventDefault();
    if (!editForm.name.trim()) return;
    setEditStatus('saving');
    try {
      await api.updateWorkspace(editingWs.id, editForm);
      setEditingWs(null);
      setEditStatus(null);
      await loadWorkspaces();
    } catch {
      setEditStatus('error');
      setTimeout(() => setEditStatus(null), 3000);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-bright">Workspaces</h1>
          <p className="text-muted text-sm mt-1">Organise your projects and collaborate with your team.</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 bg-accent hover:bg-accent/90 transition-colors text-white text-xs font-bold px-4 py-2 rounded-lg"
        >
          <Plus className="w-3.5 h-3.5" />
          New Workspace
        </button>
      </header>

      {/* Error banner */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 flex items-center justify-between">
          <p className="text-red-400 text-sm">{error}</p>
          <button onClick={() => setError(null)} className="text-muted hover:text-bright text-lg leading-none">×</button>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map(i => (
            <div key={i} className="panel p-5 space-y-3 animate-pulse">
              <div className="h-4 bg-border/40 rounded w-3/4" />
              <div className="h-3 bg-border/30 rounded w-full" />
              <div className="h-3 bg-border/30 rounded w-1/2" />
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && workspaces.length === 0 && !error && (
        <div className="panel flex flex-col items-center justify-center py-20 space-y-4">
          <FolderOpen className="w-12 h-12 text-muted/30" />
          <div className="text-center">
            <h3 className="text-base font-bold text-bright">No workspaces yet</h3>
            <p className="text-muted text-sm mt-1">Create a workspace to organise your projects and share with teammates.</p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 bg-accent hover:bg-accent/90 transition-colors text-white text-xs font-bold px-5 py-2 rounded-lg"
          >
            <Plus className="w-3.5 h-3.5" />
            Create First Workspace
          </button>
        </div>
      )}

      {/* Workspace cards */}
      {!loading && workspaces.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {workspaces.map(ws => (
            <div key={ws.id} className="panel p-5 space-y-3 group hover:border-accent/30 transition-colors">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center shrink-0">
                    <FolderOpen className="w-4 h-4 text-accent" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-bright text-sm leading-tight">{ws.name}</h3>
                    <div className="flex items-center gap-2 mt-0.5">
                      {ws.is_shared ? (
                        <span className="flex items-center gap-1 text-[10px] text-accent">
                          <Globe className="w-2.5 h-2.5" /> Shared
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-[10px] text-muted">
                          <Users className="w-2.5 h-2.5" /> Private
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center">
                  <button
                    onClick={() => { setEditingWs(ws); setEditForm({ name: ws.name, description: ws.description || '', is_shared: ws.is_shared || false }); }}
                    className="opacity-0 group-hover:opacity-100 p-1.5 text-muted hover:text-accent hover:bg-accent/10 rounded transition-all mr-1"
                    title="Edit workspace"
                    aria-label={`Edit workspace ${ws.name}`}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setConfirmDelete(ws)}
                    disabled={deleteStatus[ws.id] === 'deleting'}
                    className="opacity-0 group-hover:opacity-100 p-1.5 text-muted hover:text-danger hover:bg-danger/10 rounded transition-all disabled:opacity-50"
                    title="Delete workspace"
                    aria-label={`Delete workspace ${ws.name}`}
                  >
                    {deleteStatus[ws.id] === 'deleting'
                      ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      : <Trash2 className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>

              {ws.description && (
                <p className="text-xs text-muted leading-relaxed line-clamp-2">{ws.description}</p>
              )}

              <div className="flex items-center justify-between pt-1 border-t border-border/50">
                <span className="text-[10px] text-muted font-mono">
                  {ws.created_at ? new Date(ws.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—'}
                </span>
                <span className="text-[10px] font-mono text-muted/60 truncate max-w-[80px]" title={ws.id}>{ws.id.slice(0, 8)}</span>
              </div>
              <button
                onClick={() => navigate(`/projects?workspace=${ws.id}`)}
                className="text-[10px] text-accent hover:underline"
              >
                View Projects →
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Create workspace modal */}
      {showCreate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setShowCreate(false)}
          role="presentation"
        >
          <div
            className="bg-panel border border-border rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-ws-title"
            onClick={e => e.stopPropagation()}
          >
            <h3 id="create-ws-title" className="text-base font-bold text-bright mb-4">Create Workspace</h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Name *</label>
                <input
                  autoFocus
                  type="text"
                  value={createForm.name}
                  onChange={e => setCreateForm(f => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. Engineering, Marketing"
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent placeholder:text-muted/50"
                  required
                />
              </div>
              <div>
                <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Description</label>
                <textarea
                  rows={2}
                  value={createForm.description}
                  onChange={e => setCreateForm(f => ({ ...f, description: e.target.value }))}
                  placeholder="Optional workspace description"
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent resize-none placeholder:text-muted/50"
                />
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setCreateForm(f => ({ ...f, is_shared: !f.is_shared }))}
                  role="switch"
                  aria-checked={createForm.is_shared}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${createForm.is_shared ? 'bg-accent' : 'bg-border'}`}
                >
                  <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${createForm.is_shared ? 'translate-x-[18px]' : 'translate-x-1'}`} />
                </button>
                <label className="text-sm text-bright">Shared workspace (visible to all org members)</label>
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="flex-1 px-4 py-2 text-sm text-muted border border-border rounded-lg hover:text-bright transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!createForm.name.trim() || createStatus === 'saving'}
                  className="flex-1 px-4 py-2 text-sm font-bold bg-accent hover:bg-accent/90 text-white rounded-lg transition-colors disabled:opacity-50"
                >
                  {createStatus === 'saving' ? 'Creating…' : createStatus === 'error' ? '✗ Error' : 'Create Workspace'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit workspace modal */}
      {editingWs && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setEditingWs(null)}
          role="presentation"
        >
          <div
            className="bg-panel border border-border rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl"
            role="dialog"
            aria-modal="true"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="text-base font-bold text-bright mb-4">Edit Workspace</h3>
            <form onSubmit={handleEdit} className="space-y-4">
              <div>
                <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Name *</label>
                <input
                  autoFocus
                  type="text"
                  value={editForm.name}
                  onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                  required
                />
              </div>
              <div>
                <label className="block text-[10px] font-bold text-muted uppercase tracking-wider mb-1">Description</label>
                <textarea
                  rows={2}
                  value={editForm.description}
                  onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))}
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-bright focus:outline-none focus:border-accent resize-none"
                />
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setEditForm(f => ({ ...f, is_shared: !f.is_shared }))}
                  role="switch"
                  aria-checked={editForm.is_shared}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${editForm.is_shared ? 'bg-accent' : 'bg-border'}`}
                >
                  <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${editForm.is_shared ? 'translate-x-[18px]' : 'translate-x-1'}`} />
                </button>
                <span className="text-sm text-bright">Shared workspace</span>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setEditingWs(null)} className="flex-1 px-4 py-2 text-sm text-muted border border-border rounded-lg hover:text-bright transition-colors">
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!editForm.name.trim() || editStatus === 'saving'}
                  className="flex-1 px-4 py-2 text-sm font-bold bg-accent hover:bg-accent/90 text-white rounded-lg transition-colors disabled:opacity-50"
                >
                  {editStatus === 'saving' ? 'Saving…' : editStatus === 'error' ? '✗ Error' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Confirm delete dialog */}
      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete Workspace"
        message={confirmDelete ? `Are you sure you want to delete "${confirmDelete.name}"? This action cannot be undone.` : ''}
        onConfirm={() => confirmDelete && handleDelete(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
        danger
      />
    </div>
  );
};

export default Workspaces;
