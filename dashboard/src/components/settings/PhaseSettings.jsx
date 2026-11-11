import React, { useEffect } from 'react';
import { Settings as SettingsIcon, FolderTree, Search, FileCode, ChevronDown, ChevronUp } from 'lucide-react';

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

// ── Phase Config Panel ─────────────────────────────────────────────────────────
// Inline sub-component kept here since it only serves PhaseControls
const PhaseConfigPanel = ({ config, onSave }) => {
  const [enabled, setEnabled] = React.useState(config.enabled !== false);
  const [priority, setPriority] = React.useState(
    config.priority ? config.priority.charAt(0).toUpperCase() + config.priority.slice(1) : 'Normal'
  );
  const [saved, setSaved] = React.useState(false);

  const handleSave = async () => {
    await onSave({ enabled, priority: priority.toLowerCase() });
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  return (
    <div className="p-6 bg-border/5 space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <label className="text-[10px] font-bold text-muted uppercase">Execution Status</label>
          <select
            value={enabled ? 'Enabled' : 'Disabled'}
            onChange={(e) => setEnabled(e.target.value === 'Enabled')}
            className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
          >
            <option>Enabled</option>
            <option>Disabled</option>
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-bold text-muted uppercase">Priority Level</label>
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className="w-full bg-surface border border-border rounded px-3 py-1.5 text-xs text-bright focus:outline-none focus:border-accent"
          >
            <option>Normal</option>
            <option>High</option>
            <option>Low</option>
          </select>
        </div>
      </div>
      <div className="flex items-center space-x-3 pt-2">
        <button
          onClick={handleSave}
          className="text-[10px] font-bold bg-accent/20 text-accent border border-accent/30 px-3 py-1 rounded uppercase tracking-wider hover:bg-accent/30 transition-colors"
        >
          {saved ? '✓ Saved' : 'Save Config'}
        </button>
      </div>
    </div>
  );
};

// ── Phase Controls Panel ───────────────────────────────────────────────────────
export const PhaseControlsPanel = ({ PHASES, PHASE_NAMES, phaseConfigs, expandedPhase, setExpandedPhase, onSavePhaseConfig }) => (
  <section className="panel overflow-hidden">
    <div className="bg-border/20 px-6 py-4 border-b border-border flex items-center">
      <SettingsIcon className="w-4 h-4 mr-2 text-accent" />
      <h3 className="text-xs font-bold text-muted uppercase tracking-widest">Stage Controls</h3>
    </div>
    <div className="divide-y divide-border">
      {PHASES.map((p) => (
        <div key={p} className="flex flex-col">
          <button
            onClick={() => setExpandedPhase(expandedPhase === p ? null : p)}
            className="flex items-center justify-between p-4 hover:bg-border/10 transition-colors"
          >
            <div className="flex items-center space-x-4">
              <span className="text-xs font-mono text-accent font-bold">{p}</span>
              <span className="text-sm font-medium text-bright">{PHASE_NAMES[p]}</span>
            </div>
            {expandedPhase === p ? <ChevronUp className="w-4 h-4 text-muted" /> : <ChevronDown className="w-4 h-4 text-muted" />}
          </button>
          {expandedPhase === p && (
            <PhaseConfigPanel
              config={phaseConfigs[p] || {}}
              onSave={(cfg) => onSavePhaseConfig(p, cfg)}
            />
          )}
        </div>
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
