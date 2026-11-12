import React, { useState, useEffect } from 'react';
import { X, Rocket, Loader2, Zap, Settings, CreditCard, HeartPulse, Cloud, ShoppingCart, Truck, BookOpen, Shield } from 'lucide-react';
import { api } from '../api';
import { useNavigate } from 'react-router-dom';
import ErrorText from './ErrorText';
import { apiErrorState } from '../apiError';

const DOMAIN_DATA = {
  general: {
    label: 'General / SaaS',
    icon: <Zap className="w-4 h-4" />,
    stack: 'FastAPI, SQLite, React',
    compliance: [],
    description: 'Standard web application'
  },
  industrial: {
    label: 'Industrial / IoT',
    icon: <Settings className="w-4 h-4" />,
    stack: 'TimescaleDB, MQTT, OPC-UA',
    compliance: ['IEC 62443', 'NIST'],
    description: 'SCADA & IoT systems'
  },
  fintech: {
    label: 'Fintech',
    icon: <CreditCard className="w-4 h-4" />,
    stack: 'PostgreSQL (Serializable), Redis',
    compliance: ['PCI-DSS', 'SOX'],
    description: 'Double-entry accounting'
  },
  healthcare: {
    label: 'Healthcare',
    icon: <HeartPulse className="w-4 h-4" />,
    stack: 'HL7/FHIR, PostgreSQL',
    compliance: ['HIPAA', 'GDPR'],
    description: 'Patient data management'
  },
  saas_multitenant: {
    label: 'SaaS Multi-tenant',
    icon: <Cloud className="w-4 h-4" />,
    stack: 'PostgreSQL RLS, Stripe',
    compliance: ['SOC2', 'GDPR'],
    description: 'Multi-tenant SaaS'
  },
  ecommerce: {
    label: 'E-Commerce',
    icon: <ShoppingCart className="w-4 h-4" />,
    stack: 'PostgreSQL, Meilisearch',
    compliance: ['PCI-DSS'],
    description: 'Orders & Inventory'
  },
  logistics: {
    label: 'Logistics',
    icon: <Truck className="w-4 h-4" />,
    stack: 'PostGIS, Google Maps',
    compliance: ['TAPA'],
    description: 'Route optimization'
  },
  education: {
    label: 'Education / LMS',
    icon: <BookOpen className="w-4 h-4" />,
    stack: 'PostgreSQL, AWS S3',
    compliance: ['FERPA', 'COPPA'],
    description: 'LMS & Assessments'
  }
};

const NewProjectModal = ({ open, onClose }) => {
  const [name, setName] = useState('');
  const [requirements, setRequirements] = useState('');
  const [domain, setDomain] = useState('general');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const currentDomain = DOMAIN_DATA[domain] || DOMAIN_DATA.general;

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
        project_name: name.trim() || 'Untitled Project',
        domain,
        client_id: name.trim()
          ? name.trim().toLowerCase().replace(/\s+/g, '-')
          : 'client-001',
      });
      const runId = res.data?.run_id;
      onClose();
      // Navigate directly to the live run view
      if (runId) {
        navigate(`/project/${runId}`);
      } else {
        navigate('/projects');
      }
    } catch (err) {
      setError(apiErrorState(err, 'Failed to start run.'));
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
              <h2 className="text-base font-bold text-bright">New Project</h2>
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
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {Object.entries(DOMAIN_DATA).map(([key, d]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setDomain(key)}
                  className={`flex items-start p-3 text-left border rounded-lg transition-all ${
                    domain === key 
                      ? 'border-accent bg-accent/5 ring-1 ring-accent' 
                      : 'border-border bg-surface hover:border-slate-700'
                  }`}
                >
                  <div className={`mt-0.5 mr-3 ${domain === key ? 'text-accent' : 'text-muted'}`}>
                    {d.icon}
                  </div>
                  <div>
                    <div className={`text-sm font-semibold ${domain === key ? 'text-bright' : 'text-slate-300'}`}>
                      {d.label}
                    </div>
                    <div className="text-[10px] text-muted leading-tight mt-0.5">
                      {d.description}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Domain Insights */}
          <div className="bg-surface/50 border border-border rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Settings className="w-3.5 h-3.5 text-accent" />
                <span className="text-xs font-bold text-muted uppercase tracking-wider">Recommended Stack</span>
              </div>
              <span className="text-xs text-bright font-mono">{currentDomain.stack}</span>
            </div>
            
            {currentDomain.compliance.length > 0 && (
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <Shield className="w-3.5 h-3.5 text-success" />
                  <span className="text-xs font-bold text-muted uppercase tracking-wider">Compliance</span>
                </div>
                <div className="flex gap-1">
                  {currentDomain.compliance.map(c => (
                    <span key={c} className="text-[10px] bg-success/10 text-success border border-success/20 px-1.5 py-0.5 rounded">
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="bg-danger/10 border border-danger/30 rounded-lg px-4 py-3 text-sm text-danger">
              <ErrorText error={error} />
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
