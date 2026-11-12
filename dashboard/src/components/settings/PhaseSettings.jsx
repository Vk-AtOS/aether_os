import React, { useEffect } from 'react';
import { Settings as SettingsIcon, FolderTree, Search, FileCode, ChevronDown, Lock } from 'lucide-react';
import { MANDATORY_STAGES } from '../project/projectConstants';
import { apiError } from '../../apiError';

import hljs from 'highlight.js/lib/core';
import json from 'highlight.js/lib/languages/json';
import javascript from 'highlight.js/lib/languages/javascript';
import python from 'highlight.js/lib/languages/python';
import yaml from 'highlight.js/lib/languages/yaml';
import bash from 'highlight.js/lib/languages/bash';
import sql from 'highlight.js/lib/languages/sql';
hljs.registerLanguage('json', json);
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('python', python);
hljs.registerLanguage('yaml', yaml);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('sql', sql);

// ── Stage Controls ─────────────────────────────────────────────────────────────
// Mandatory stages are shown on and locked, with the reason; the optional ones
// (s08, s10, s12) can be switched off. The pipeline records a switched-off stage as
// skipped ("disabled_in_settings"). The stored priority is sent back unchanged: the
// pipeline does not read it.
const StageToggle = ({ stage, name, config, onSave }) => {
  const lockedWhy = MANDATORY_STAGES[stage];
  const enabled = lockedWhy ? true : config.enabled !== false;
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  const toggle = async () => {
    setSaving(true); setError('');
    try {
      await onSave({ enabled: !enabled, priority: config.priority || 'normal' });
    } catch (e) {
      setError(apiError(e) || 'Could not save. Try again.');
    } finally {
      setSaving(false);
    }
  };

  const label = lockedWhy ? `Always on: ${lockedWhy}` : enabled ? 'On: click to switch off' : 'Off: click to switch on';
  return (
    <div className="flex items-center justify-between gap-4 p-4">
      <div className="min-w-0">
        <div className="flex items-center space-x-3">
          <span className="text-xs font-mono text-accent font-bold">{stage}</span>
          <span className="text-sm font-medium text-bright">{name}</span>
          {lockedWhy && <Lock className="w-3 h-3 text-muted" aria-hidden="true" />}
        </div>
        <p className="text-[11px] text-muted mt-0.5">{lockedWhy ? `Required: ${lockedWhy}.` : 'Optional.'}</p>
        {error && <p role="alert" className="text-[11px] text-danger mt-0.5">{error}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label={`${name}: ${label}`}
        title={label}
        disabled={Boolean(lockedWhy) || saving}
        onClick={toggle}
        className={`relative w-10 h-5 rounded-full shrink-0 transition-colors ${enabled ? 'bg-accent' : 'bg-border'} ${lockedWhy ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${enabled ? 'translate-x-5' : ''}`} />
      </button>
    </div>
  );
};

export const PhaseControlsPanel = ({ PHASES, PHASE_NAMES, phaseConfigs, onSavePhaseConfig }) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
      <SettingsIcon className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Stage Controls</h3>
    </div>
    <div className="divide-y divide-border">
      {PHASES.map((p) => (
        <StageToggle key={p} stage={p} name={PHASE_NAMES[p]} config={phaseConfigs[p] || {}}
          onSave={(cfg) => onSavePhaseConfig(p, cfg)} />
      ))}
    </div>
  </section>
);

// ── File Browser Panel ─────────────────────────────────────────────────────────
export const FileBrowserPanel = ({
  runs, selectedRun, onRunSelect,
  runFiles, loadingFiles, selectedFile, fileContent,
  onFileClick,
}) => {
  useEffect(() => {
    if (fileContent) {
      document.querySelectorAll('pre code').forEach((block) => {
        hljs.highlightElement(block);
      });
    }
  }, [fileContent]);

  return (
    <section className="panel overflow-hidden">
      <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center">
          <FolderTree className="w-4 h-4 mr-2 text-accent" />
          <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Project File Browser</h3>
        </div>
        <div className="flex items-center space-x-3">
          <select
            value={selectedRun}
            onChange={(e) => onRunSelect(e.target.value)}
            className="bg-surface border border-border rounded px-3 py-1 text-[10px] font-bold text-muted uppercase focus:outline-none focus:border-accent"
          >
            <option value="">Select Run</option>
            {runs.map(r => (
              <option key={r.run_id || r.id} value={r.run_id || r.id}>{r.project_name} ({r.run_id || r.id})</option>
            ))}
          </select>
        </div>
      </div>
      <div className="grid grid-cols-10 h-[500px]">
        <div className="col-span-3 border-r border-border overflow-y-auto custom-scrollbar p-4 space-y-4">
          {!selectedRun ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-4">
              <Search className="w-8 h-8 text-muted/20 mb-2" />
              <p className="text-[10px] text-muted uppercase font-bold">Select a factory run to browse files</p>
            </div>
          ) : loadingFiles ? (
            <div className="h-full flex items-center justify-center text-muted text-[10px] uppercase font-bold">Loading...</div>
          ) : Object.keys(runFiles).length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-4">
              <p className="text-[10px] text-muted uppercase font-bold">No files found for this run</p>
            </div>
          ) : (
            Object.entries(runFiles).map(([phase, files]) => (
              <div key={phase} className="space-y-1">
                <div className="text-[10px] font-bold text-muted uppercase tracking-tighter flex items-center">
                  <ChevronDown className="w-3 h-3 mr-1" /> {phase}
                </div>
                <div className="pl-4 space-y-1">
                  {files.map(filePath => {
                    const fileName = filePath.split('/').pop();
                    return (
                      <button
                        key={filePath}
                        onClick={() => onFileClick(filePath)}
                        className={`w-full text-left px-2 py-1 rounded text-[11px] flex items-center transition-colors ${selectedFile === filePath ? 'bg-accent/20 text-accent font-bold' : 'text-bright/70 hover:bg-border/30'}`}
                      >
                        <FileCode className="w-3 h-3 mr-2 opacity-50" /> {fileName}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>
        <div className="col-span-7 bg-[#0a0c10] overflow-hidden flex flex-col">
          <div className="bg-border/10 px-4 py-2 border-b border-border flex justify-between items-center shrink-0">
            <span className="text-[10px] font-mono text-muted uppercase tracking-widest">{selectedFile || 'No file selected'}</span>
            <span className="text-[9px] font-mono text-success">READ ONLY</span>
          </div>
          <div className="flex-1 overflow-auto p-4 custom-scrollbar">
            {fileContent ? (() => {
              const ext = selectedFile?.split('.').pop()?.toLowerCase() || '';
              const langMap = { js: 'javascript', ts: 'typescript', jsx: 'javascript', tsx: 'typescript', py: 'python', json: 'json', yml: 'yaml', yaml: 'yaml', md: 'markdown', sh: 'bash', css: 'css', html: 'html', sql: 'sql' };
              const lang = `language-${langMap[ext] || 'plaintext'}`;
              return <pre className="m-0"><code className={`${lang} font-mono text-sm leading-relaxed`}>{fileContent}</code></pre>;
            })() : (
              <div className="h-full flex items-center justify-center text-muted/20">
                <FileCode className="w-16 h-16" />
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
};
