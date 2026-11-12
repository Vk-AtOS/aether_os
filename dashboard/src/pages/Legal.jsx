import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2, FileText, Shield, FileCheck } from 'lucide-react';

const DOCS = [
  { key: 'tos',     label: 'Terms of Service', path: '/api/legal/tos',     icon: FileText  },
  { key: 'privacy', label: 'Privacy Policy',   path: '/api/legal/privacy', icon: Shield    },
  { key: 'dpa',     label: 'DPA (GDPR)',        path: '/api/legal/dpa',     icon: FileCheck },
];

const Legal = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [active, setActive] = useState(searchParams.get('doc') || 'tos');
  const [content, setContent] = useState('');
  const [meta, setMeta] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const doc = DOCS.find(d => d.key === active);
    if (!doc) return;
    fetch(doc.path)
      .then(r => r.json())
      .then(data => {
        setError('');
        setContent(data.text || '');
        setMeta({ version: data.version, effective_date: data.effective_date });
      })
      .catch(() => setError('Failed to load document. Please try again.'))
      .finally(() => setLoading(false));
  }, [active]);

  const switchDoc = (key) => {
    if (key !== active) setLoading(true);
    setActive(key);
    setSearchParams({ doc: key });
  };

  const activeDoc = DOCS.find(d => d.key === active);

  return (
    <div className="min-h-screen bg-bg flex flex-col">
      <div className="border-b border-border bg-panel px-6 py-4 flex items-center gap-3">
        <Shield className="w-5 h-5 text-accent" />
        <h1 className="text-lg font-bold text-bright">Legal Documents</h1>
      </div>

      <div className="flex flex-1 overflow-hidden max-w-5xl mx-auto w-full mt-8 mb-8 gap-6 px-4">
        {/* Tab list */}
        <nav className="w-48 shrink-0 space-y-1">
          {DOCS.map(doc => {
            const Icon = doc.icon;
            const isActive = active === doc.key;
            return (
              <button
                key={doc.key}
                onClick={() => switchDoc(doc.key)}
                className={`w-full flex items-center gap-2.5 px-4 py-2.5 rounded-lg text-sm font-medium text-left transition-colors ${
                  isActive ? 'bg-accent text-white' : 'text-muted hover:text-bright hover:bg-surface'
                }`}
              >
                <Icon className="w-4 h-4 shrink-0" />
                {doc.label}
              </button>
            );
          })}
        </nav>

        {/* Document viewer */}
        <div className="flex-1 bg-panel border border-border rounded-xl overflow-hidden flex flex-col">
          <div className="px-6 py-4 border-b border-border flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-bright">{activeDoc?.label}</h2>
              {meta.version && (
                <p className="text-xs text-muted mt-0.5">
                  Version {meta.version} · Effective {meta.effective_date}
                </p>
              )}
            </div>
            <a
              href={`/api/legal/${active}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-accent hover:text-accent/80 font-medium transition-colors"
            >
              Raw JSON ↗
            </a>
          </div>

          <div className="flex-1 overflow-y-auto p-6">
            {loading ? (
              <div className="flex items-center justify-center h-40 text-muted">
                <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading…
              </div>
            ) : error ? (
              <div className="text-danger text-sm p-4 bg-danger/10 rounded-lg border border-danger/20">{error}</div>
            ) : (
              <pre className="text-sm text-bright/90 whitespace-pre-wrap font-sans leading-relaxed">{content}</pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Legal;
