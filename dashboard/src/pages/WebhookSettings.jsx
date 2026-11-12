import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { Webhook, Plus, Trash2, CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import ConfirmDialog from '../components/ConfirmDialog';
import { apiError } from '../apiError';

const EVENT_OPTIONS = [
  'run.started', 'run.completed', 'run.failed', 'run.cancelled',
  'phase.completed', 'decision.requested', 'deploy.completed',
];

const WebhookSettings = () => {
  const [webhooks, setWebhooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ url: '', events: ['run.completed', 'run.failed'] });
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState({});
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [addError, setAddError] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({ url: '', events: [] });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState(null);
  const [testing, setTesting] = useState({});
  const [testResults, setTestResults] = useState({});

  const fetchWebhooks = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await api.getWebhooks();
      setWebhooks(res.data ?? []);
    } catch (err) {
      setLoadError(apiError(err) || 'Failed to load webhooks.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchWebhooks(); }, []);

  const handleAdd = async (e) => {
    e.preventDefault();
    if (!form.url.trim()) return;
    setAddError(null);
    setSaving(true);
    try {
      await api.createWebhook({ url: form.url, events: form.events });
      setForm({ url: '', events: ['run.completed', 'run.failed'] });
      setAdding(false);
      await fetchWebhooks();
    } catch (e) {
      setAddError('Failed to add webhook: ' + (apiError(e) || e.message));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    setConfirmDelete(null);
    setDeleteError(null);
    setDeleting(prev => ({ ...prev, [id]: true }));
    try {
      await api.deleteWebhook(id);
      setWebhooks(prev => prev.filter(w => w.id !== id));
    } catch (err) {
      setDeleteError(apiError(err) || 'Failed to delete webhook.');
    } finally {
      setDeleting(prev => ({ ...prev, [id]: false }));
    }
  };

  const toggleEvent = (evt) => {
    setForm(prev => ({
      ...prev,
      events: prev.events.includes(evt)
        ? prev.events.filter(e => e !== evt)
        : [...prev.events, evt],
    }));
  };

  const handleEdit = async (e) => {
    e.preventDefault();
    if (!editForm.url.trim()) return;
    setEditSaving(true);
    setEditError(null);
    try {
      await api.client.put(`/webhooks/${editingId}`, editForm);
      setEditingId(null);
      await fetchWebhooks();
    } catch (e) {
      setEditError(apiError(e) || 'Failed to update webhook');
    } finally {
      setEditSaving(false);
    }
  };

  const handleTest = async (id) => {
    setTesting(p => ({ ...p, [id]: true }));
    setTestResults(p => ({ ...p, [id]: null }));
    try {
      const res = await api.client.post(`/webhooks/${id}/test`);
      setTestResults(p => ({ ...p, [id]: res.data }));
    } catch (e) {
      setTestResults(p => ({ ...p, [id]: { ok: false, message: apiError(e) || e.message } }));
    } finally {
      setTesting(p => ({ ...p, [id]: false }));
    }
  };

  const toggleEditEvent = (evt) => {
    setEditForm(prev => ({
      ...prev,
      events: prev.events.includes(evt) ? prev.events.filter(e => e !== evt) : [...prev.events, evt],
    }));
  };

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      {loadError && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-danger text-xs flex items-center gap-2">
          <span className="flex-1">{loadError}</span>
          <button onClick={() => setLoadError(null)} className="text-muted hover:text-bright">✕</button>
        </div>
      )}
      {deleteError && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-danger text-xs flex items-center gap-2">
          <span className="flex-1">{deleteError}</span>
          <button onClick={() => setDeleteError(null)} className="text-muted hover:text-bright">✕</button>
        </div>
      )}
      <header className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-bright">Webhooks</h1>
          <p className="text-muted mt-1">Receive real-time events when pipeline actions occur.</p>
        </div>
        <button
          onClick={() => setAdding(true)}
          className="flex items-center space-x-2 bg-accent hover:bg-accent/90 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors uppercase"
        >
          <Plus className="w-3 h-3" />
          <span>Add Webhook</span>
        </button>
      </header>

      {/* Add form */}
      {adding && (
        <section className="panel overflow-hidden">
          <div className="bg-border/20 px-6 py-4 border-b border-border">
            <h3 className="text-xs font-bold text-muted uppercase tracking-widest">New Webhook</h3>
          </div>
          <form onSubmit={handleAdd} className="p-6 space-y-5">
            <div>
              <label className="block text-xs font-bold text-muted uppercase tracking-wider mb-1">Endpoint URL</label>
              <input
                type="url"
                value={form.url}
                onChange={e => setForm(p => ({ ...p, url: e.target.value }))}
                placeholder="https://your-server.com/webhook"
                className="w-full bg-surface border border-border rounded-lg px-4 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-muted uppercase tracking-wider mb-2">Events to receive</label>
              <div className="flex flex-wrap gap-2">
                {EVENT_OPTIONS.map(evt => (
                  <button
                    key={evt}
                    type="button"
                    onClick={() => toggleEvent(evt)}
                    className={`text-[10px] font-bold px-3 py-1 rounded-full uppercase transition-colors border ${
                      form.events.includes(evt)
                        ? 'bg-accent/20 text-accent border-accent/40'
                        : 'bg-surface text-muted border-border hover:border-accent/40'
                    }`}
                  >
                    {evt}
                  </button>
                ))}
              </div>
            </div>
            {addError && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-danger text-xs">
                {addError}
              </div>
            )}
            <div className="flex items-center space-x-3">
              <button
                type="submit"
                disabled={saving}
                className="flex items-center space-x-2 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-bold px-5 py-2 rounded-lg transition-colors uppercase"
              >
                {saving && <Loader2 className="w-3 h-3 animate-spin" />}
                <span>{saving ? 'Saving…' : 'Save Webhook'}</span>
              </button>
              <button type="button" onClick={() => setAdding(false)} className="text-xs text-muted hover:text-bright transition-colors">
                Cancel
              </button>
            </div>
          </form>
        </section>
      )}

      {/* List */}
      <section className="panel overflow-hidden">
        <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
          <Webhook className="w-4 h-4 mr-2 text-accent" />
          <h3 className="text-xs font-bold text-muted uppercase tracking-widest">
            Configured Webhooks ({webhooks.length})
          </h3>
        </div>
        {loading ? (
          <div className="p-12 flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-accent" />
          </div>
        ) : webhooks.length === 0 ? (
          <div className="p-12 text-center">
            <Webhook className="w-10 h-10 text-muted/20 mx-auto mb-3" />
            <p className="text-muted text-sm">No webhooks configured. Add one to receive events.</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {webhooks.map(wh => (
              <div key={wh.id}>
                <div className="px-6 py-4 flex items-center justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center space-x-2">
                      {wh.is_active
                        ? <CheckCircle2 className="w-3.5 h-3.5 text-success" />
                        : <XCircle className="w-3.5 h-3.5 text-muted" />}
                      <span className="text-sm font-medium text-bright break-all">{wh.url}</span>
                    </div>
                    <div className="flex flex-wrap gap-1 pl-5">
                      {(wh.events ?? []).map(e => (
                        <span key={e} className="text-[9px] font-bold text-muted uppercase bg-border/30 px-2 py-0.5 rounded-full">{e}</span>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 ml-4 shrink-0">
                    <button
                      onClick={() => handleTest(wh.id)}
                      disabled={testing[wh.id]}
                      className="text-xs font-bold text-blue-400/70 hover:text-blue-400 border border-blue-500/30 px-2.5 py-1 rounded-lg hover:bg-blue-500/10 transition-colors disabled:opacity-50"
                      title="Send test ping"
                    >
                      {testing[wh.id] ? '…' : 'Test'}
                    </button>
                    <button
                      onClick={() => { setEditingId(wh.id); setEditForm({ url: wh.url, events: wh.events ?? [] }); setEditError(null); }}
                      className="text-xs font-bold text-muted hover:text-bright border border-border px-2.5 py-1 rounded-lg hover:border-accent/40 transition-colors"
                      title="Edit webhook"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => setConfirmDelete(wh.id)}
                      disabled={deleting[wh.id]}
                      className="text-danger/50 hover:text-danger transition-colors disabled:opacity-30"
                      title="Delete webhook"
                      aria-label={`Delete webhook ${wh.url}`}
                    >
                      {deleting[wh.id] ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                {testResults[wh.id] && (
                  <div className={`mx-6 mb-2 px-3 py-2 rounded-lg text-xs flex items-center gap-2 ${testResults[wh.id].ok ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-400' : 'bg-red-500/10 border border-red-500/30 text-danger'}`}>
                    {testResults[wh.id].ok ? '✓' : '✗'} {testResults[wh.id].message}
                    {testResults[wh.id].status_code && <span className="font-mono">({testResults[wh.id].status_code})</span>}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {editingId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setEditingId(null)}>
          <div className="bg-panel border border-border rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl" onClick={e => e.stopPropagation()}>
            <h3 className="text-base font-bold text-bright mb-4">Edit Webhook</h3>
            <form onSubmit={handleEdit} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-muted uppercase tracking-wider mb-1">Endpoint URL</label>
                <input
                  type="url"
                  value={editForm.url}
                  onChange={e => setEditForm(p => ({ ...p, url: e.target.value }))}
                  className="w-full bg-surface border border-border rounded-lg px-4 py-2 text-sm text-bright focus:outline-none focus:border-accent"
                  required
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-muted uppercase tracking-wider mb-2">Events</label>
                <div className="flex flex-wrap gap-2">
                  {EVENT_OPTIONS.map(evt => (
                    <button key={evt} type="button" onClick={() => toggleEditEvent(evt)}
                      className={`text-[10px] font-bold px-3 py-1 rounded-full uppercase transition-colors border ${editForm.events.includes(evt) ? 'bg-accent/20 text-accent border-accent/40' : 'bg-surface text-muted border-border hover:border-accent/40'}`}>
                      {evt}
                    </button>
                  ))}
                </div>
              </div>
              {editError && <p className="text-xs text-danger">{editError}</p>}
              <div className="flex gap-3">
                <button type="button" onClick={() => setEditingId(null)} className="flex-1 px-4 py-2 text-sm text-muted border border-border rounded-lg hover:text-bright transition-colors">Cancel</button>
                <button type="submit" disabled={editSaving} className="flex-1 px-4 py-2 text-sm font-bold bg-accent hover:bg-accent/90 text-white rounded-lg transition-colors disabled:opacity-50">
                  {editSaving ? 'Saving…' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete Webhook"
        message={confirmDelete ? `Are you sure you want to delete the webhook for "${webhooks.find(w => w.id === confirmDelete)?.url}"?` : ''}
        onConfirm={() => confirmDelete && handleDelete(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
        danger
      />
    </div>
  );
};

export default WebhookSettings;
