import React, { useState, useEffect } from 'react';
import { X, Rocket, Loader2 } from 'lucide-react';
import { api } from '../api';
import { useNavigate } from 'react-router-dom';

const DOMAINS = [
  { value: 'general',   label: 'General / SaaS' },
  { value: 'fintech',   label: 'Fintech' },
  { value: 'healthtech', label: 'HealthTech' },
  { value: 'ecommerce', label: 'E-Commerce' },
  { value: 'edtech',    label: 'EdTech' },
  { value: 'logistics', label: 'Logistics' },
  { value: 'analytics', label: 'Analytics' },
  { value: 'devtools',  label: 'Developer Tools' },
];

const NewProjectModal = ({ open, onClose }) => {
  const [name, setName] = useState('');
  const [requirements, setRequirements] = useState('');
  const [domain, setDomain] = useState('general');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  // Reset on open
  useEffect(() => {
    if (open) {
      setName('');
      setRequirements('');
      setDomain('general');
      setError(null);
      setLoading(false);
    }
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!requirements.trim()) {
      setError('Requirements are required.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.startPipeline({
        raw_input: requirements.trim(),
        project_name: name.trim() || undefined,
        domain,
        client_id: 'client-001',
      });
      const runId = res.data?.run_id;
      onClose();
      if (runId) navigate(`/project/${runId}`);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to start run.');
      setLoading(false);
    }
  };

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* Modal */}
      <div className="relative w-full max-w-lg mx-4 bg-panel border border-border rounded-xl shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center">
              <Rocket className="w-4 h-4 text-accent" />
            </div>
            <div>
              <h2 className="text-base font-bold text-bright">New Factory Run</h2>
              <p className="text-xs text-muted mt-0.5">AetherOS will generate a complete codebase</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-muted hover:text-bright transition-colors p-1"
            disabled={loading}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-5">
          {/* Project Name */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">
              Project Name <span className="text-slate-600 font-normal normal-case">(optional)</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Todo REST API"
              disabled={loading}
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm text-bright placeholder:text-muted/50 focus:outline-none focus:border-accent transition-colors disabled:opacity-50"
            />
          </div>

          {/* Requirements */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">
              Requirements <span className="text-danger">*</span>
            </label>
            <textarea
              value={requirements}
              onChange={(e) => setRequirements(e.target.value)}
              placeholder="Describe what you want to build…&#10;&#10;Example: Build a Python REST API for a todo list app with CRUD endpoints, user authentication, and PostgreSQL persistence."
              rows={5}
              disabled={loading}
              required
              className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-sm text-bright placeholder:text-muted/50 focus:outline-none focus:border-accent transition-colors resize-none disabled:opacity-50"
            />
          </div>

          {/* Domain */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted uppercase tracking-wider">
              Domain
            </label>
            <select
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              disabled={loading}
              className="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm text-bright focus:outline-none focus:border-accent transition-colors disabled:opacity-50"
            >
              {DOMAINS.map((d) => (
                <option key={d.value} value={d.value}>{d.label}</option>
              ))}
            </select>
          </div>

          {/* Error */}
          {error && (
            <div className="bg-danger/10 border border-danger/30 rounded-lg px-4 py-3 text-sm text-danger">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end space-x-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="px-5 py-2.5 text-sm font-medium text-muted hover:text-bright border border-border rounded-lg transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || !requirements.trim()}
              className="flex items-center space-x-2 px-6 py-2.5 bg-accent hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-bold rounded-lg transition-colors"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Starting…</span>
                </>
              ) : (
                <>
                  <Rocket className="w-4 h-4" />
                  <span>Start Factory Run</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default NewProjectModal;
