import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { Webhook, Plus, Trash2, CheckCircle2, XCircle, Loader2 } from 'lucide-react';

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

  const fetchWebhooks = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await api.getWebhooks();
      setWebhooks(res.data ?? []);
    } catch (err) {
      setLoadError(err.response?.data?.detail || 'Failed to load webhooks.');
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
      setAddError('Failed to add webhook: ' + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    if (confirmDelete !== id) { setConfirmDelete(id); return; }
    setConfirmDelete(null);
    setDeleteError(null);
    setDeleting(prev => ({ ...prev, [id]: true }));
    try {
      await api.deleteWebhook(id);
      setWebhooks(prev => prev.filter(w => w.id !== id));
    } catch (err) {
      setDeleteError(err.response?.data?.detail || 'Failed to delete webhook.');
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
              <div key={wh.id} className="px-6 py-4 flex items-center justify-between">
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
                {confirmDelete === wh.id ? (
                  <span className="ml-4 flex items-center gap-2 text-[10px]">
                    <span className="text-danger font-bold">Delete?</span>
                    <button onClick={() => handleDelete(wh.id)} className="text-danger font-bold underline">Yes</button>
                    <button onClick={() => setConfirmDelete(null)} className="text-muted hover:text-bright">No</button>
                  </span>
                ) : (
                  <button
                    onClick={() => handleDelete(wh.id)}
                    disabled={deleting[wh.id]}
                    className="ml-4 text-danger/50 hover:text-danger transition-colors disabled:opacity-30"
                    title="Delete webhook"
                  >
                    {deleting[wh.id] ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};

export default WebhookSettings;
