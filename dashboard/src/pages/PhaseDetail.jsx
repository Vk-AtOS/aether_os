import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import PhaseBadge from '../components/PhaseBadge';
import {
  ArrowLeft,
  FileText,
  ShieldCheck,
  Brain,
  Files,
  ChevronRight,
  Download,
  Copy,
  File,
  Folder,
  FolderOpen,
  ChevronDown,
  Loader2,
} from 'lucide-react';

// ── Helpers ──────────────────────────────────────────────────────────────────

const langFromExt = (filename) => {
  if (!filename) return 'text';
  const ext = filename.split('.').pop().toLowerCase();
  return { py: 'python', js: 'javascript', jsx: 'javascript', ts: 'typescript',
           tsx: 'typescript', json: 'json', yaml: 'yaml', yml: 'yaml',
           md: 'markdown', html: 'html', css: 'css', sh: 'bash',
           toml: 'toml', txt: 'text' }[ext] || 'text';
};

const formatDuration = (ms) => {
  if (!ms || ms <= 0) return null;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
};

const JsonBlock = ({ data, collapsed = false }) => {
  const [open, setOpen] = useState(!collapsed);
  const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  return (
    <div className="relative group">
      <div className="absolute right-4 top-4 flex space-x-2 opacity-0 group-hover:opacity-100 transition-opacity z-10">
        <button
          onClick={() => { navigator.clipboard.writeText(text); }}
          className="p-1.5 bg-panel border border-border rounded text-muted hover:text-bright transition-colors"
          title="Copy"
        >
          <Copy className="w-3.5 h-3.5" />
        </button>
      </div>
      <pre className="p-6 bg-[#0a0c10] rounded-xl border border-border overflow-x-auto custom-scrollbar font-mono text-sm leading-relaxed text-bright/90 max-h-[600px] overflow-y-auto">
        <code>{text}</code>
      </pre>
    </div>
  );
};

// Flat file list from tree, filtering by phase prefix
const flattenTree = (items, prefix) => {
  const result = [];
  const walk = (nodes) => {
    for (const node of nodes) {
      if (node.type === 'file' && node.path.startsWith(prefix)) {
        result.push(node);
      }
      if (node.children) walk(node.children);
    }
  };
  walk(items);
  return result;
};

// ── Main Component ────────────────────────────────────────────────────────────

const PhaseDetail = () => {
  const { id, name } = useParams();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('output');
  const [run, setRun] = useState(null);
  const [phaseData, setPhaseData] = useState(null);

  // Artifacts tab state
  const [fileTree, setFileTree] = useState(null);
  const [phaseFiles, setPhaseFiles] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState(null);
  const [fileLoading, setFileLoading] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        const [runRes, filesRes] = await Promise.all([
          api.getRun(id),
          api.getRunFiles(id),
        ]);
        const r = runRes.data;
        setRun(r);
        const phaseEntry = r.phases?.[name] ?? null;
        setPhaseData(phaseEntry);

        const tree = filesRes.data?.tree || [];
        setFileTree(tree);
        // Filter files to those under this phase's directory
        setPhaseFiles(flattenTree(tree, name + '/'));
      } catch (err) {
        console.error('PhaseDetail load failed', err);
        setPhaseData({});
      }
    };
    load();
  }, [id, name]);

  const handleFileClick = useCallback(async (file) => {
    setSelectedFile(file);
    setFileLoading(true);
    setFileContent(null);
    try {
      const res = await api.getFileContent(id, file.path);
      setFileContent(res.data);
    } catch {
      setFileContent({ error: 'Failed to load file content.' });
    } finally {
      setFileLoading(false);
    }
  }, [id]);

  // ── Loading guard ─────────────────────────────────────────────────────────
  if (!phaseData && phaseData !== null) {
    return <div className="p-8 text-center text-muted">Loading phase details…</div>;
  }
  if (phaseData === null) {
    return <div className="p-8 text-center text-muted">Loading phase details…</div>;
  }

  // ── Derived values ────────────────────────────────────────────────────────

  const status = phaseData.status || 'unknown';

  // Duration: phase.updated_at is Unix seconds; run.started_at is JS ms
  const updatedAtMs = phaseData.updated_at ? phaseData.updated_at * 1000 : null;
  const startedAtMs = run?.started_at || null;
  const durationMs = updatedAtMs && startedAtMs ? updatedAtMs - startedAtMs : null;
  const durationStr = formatDuration(durationMs) || '—';

  // Confidence: pull from gate_result or output field
  const gateResult = phaseData.gate_result || null;
  const confidence = gateResult?.confidence ?? gateResult?.score ?? phaseData.confidence ?? null;
  const confidenceStr = (confidence != null && confidence > 0)
    ? `${Math.round(confidence * 100)}%`
    : null;

  const tabs = [
    { id: 'output',    name: 'Output',       icon: FileText },
    { id: 'gate',      name: 'Gate Result',  icon: ShieldCheck },
    { id: 'memory',    name: 'Memory Used',  icon: Brain },
    { id: 'artifacts', name: 'Raw Artifacts',icon: Files },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <button
            onClick={() => navigate(`/project/${id}`)}
            className="p-2 panel hover:bg-border/50 transition-colors text-muted"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center space-x-3">
              <h1 className="text-xl font-bold">{name.replace(/_/g, ' ').replace(/^p\d+ /i, '').replace(/\b\w/g, c => c.toUpperCase())}</h1>
              <span className="text-xs font-mono text-muted">{name}</span>
              <PhaseBadge status={status} />
            </div>
            <div className="text-[10px] text-muted font-mono mt-1 uppercase flex space-x-4">
              <span>Duration: {durationStr}</span>
              {confidenceStr && <span>Confidence: {confidenceStr}</span>}
            </div>
          </div>
        </div>
      </header>

      {/* Tab bar */}
      <div className="flex border-b border-border space-x-8">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center space-x-2 py-4 border-b-2 transition-all ${
              activeTab === tab.id
                ? 'border-accent text-accent'
                : 'border-transparent text-muted hover:text-muted/80'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            <span className="text-sm font-bold uppercase tracking-wider">{tab.name}</span>
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="mt-6">

        {/* ── OUTPUT ────────────────────────────────────────────────────────── */}
        {activeTab === 'output' && (
          <div>
            {phaseData.output ? (
              <div className="space-y-4">
                {phaseData.output_file && (
                  <div className="flex items-center text-xs font-bold text-muted uppercase tracking-[0.2em] mb-3 ml-1">
                    <ChevronRight className="w-3 h-3 mr-1 text-accent" />
                    {phaseData.output_file}
                  </div>
                )}
                <JsonBlock data={phaseData.output} />
              </div>
            ) : (
              <div className="panel p-8 text-center text-muted italic">
                No output recorded for this phase.
              </div>
            )}
          </div>
        )}

        {/* ── GATE RESULT ───────────────────────────────────────────────────── */}
        {activeTab === 'gate' && (
          <div className="panel p-8 max-w-2xl">
            {gateResult ? (
              <>
                <div className="flex items-center space-x-4 mb-8">
                  <div className={`w-12 h-12 rounded-full flex items-center justify-center ${
                    gateResult.passed !== false ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'
                  }`}>
                    <ShieldCheck className="w-6 h-6" />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold">
                      Gate {gateResult.passed !== false ? 'Passed' : 'Failed'}
                    </h3>
                    {confidenceStr && (
                      <p className="text-sm text-muted">
                        Completed with {confidenceStr} confidence.
                      </p>
                    )}
                  </div>
                </div>
                <div className="mb-6">
                  <h4 className="text-xs font-bold text-muted uppercase tracking-wider mb-3">
                    Raw Gate Data
                  </h4>
                  <JsonBlock data={gateResult} />
                </div>
              </>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center space-x-4 mb-6">
                  <div className={`w-12 h-12 rounded-full flex items-center justify-center ${
                    status === 'passed' ? 'bg-success/10 text-success' : 'bg-muted/10 text-muted'
                  }`}>
                    <ShieldCheck className="w-6 h-6" />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold">
                      Phase {status === 'passed' ? 'Passed' : status === 'failed' ? 'Failed' : 'Completed'}
                    </h3>
                    <p className="text-sm text-muted">No structured gate result was recorded.</p>
                  </div>
                </div>
                <div className="text-sm text-muted italic">Gate result not available for this phase.</div>
              </div>
            )}
          </div>
        )}

        {/* ── MEMORY USED ───────────────────────────────────────────────────── */}
        {activeTab === 'memory' && (
          <div className="space-y-4">
            {(phaseData.memories && phaseData.memories.length > 0) ? (
              phaseData.memories.map((mem, i) => (
                <div key={i} className="panel p-6 flex items-start space-x-6">
                  <div className="shrink-0 flex flex-col items-center">
                    <div className="text-[10px] font-bold text-muted uppercase tracking-tighter mb-1">Score</div>
                    <div className="text-lg font-bold text-accent font-mono">
                      {((mem.score ?? 0) * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center space-x-2 mb-2">
                      <span className="bg-border/50 text-[10px] font-bold px-1.5 py-0.5 rounded border border-border text-muted uppercase tracking-wider">
                        {mem.global ? 'GLOBAL KNOWLEDGE' : `SOURCE: ${mem.phase}`}
                      </span>
                    </div>
                    <p className="text-sm text-bright/80 italic leading-relaxed">"{mem.snippet}"</p>
                  </div>
                </div>
              ))
            ) : (phaseData.context || phaseData.memory) ? (
              <div>
                <div className="text-xs font-bold text-muted uppercase tracking-wider mb-3">
                  Context / Memory Data
                </div>
                <JsonBlock data={phaseData.context || phaseData.memory} />
              </div>
            ) : (
              <div className="panel p-8 text-center text-muted italic">
                No memory data for this phase.
              </div>
            )}
          </div>
        )}

        {/* ── RAW ARTIFACTS ─────────────────────────────────────────────────── */}
        {activeTab === 'artifacts' && (
          <div className="panel overflow-hidden">
            <div className="bg-border/20 px-4 py-3 border-b border-border text-xs font-bold text-muted uppercase tracking-wider">
              Output Directory: {name}/ &nbsp;·&nbsp; {phaseFiles.length} file{phaseFiles.length !== 1 ? 's' : ''}
            </div>
            {phaseFiles.length === 0 ? (
              <div className="p-8 text-center text-muted italic">
                {fileTree === null ? 'Loading artifacts…' : 'No artifacts found for this phase.'}
              </div>
            ) : (
              <div className="flex h-[440px]">
                {/* File list */}
                <div className="w-72 border-r border-border overflow-y-auto custom-scrollbar p-2 shrink-0">
                  {phaseFiles.map((file) => (
                    <button
                      key={file.path}
                      onClick={() => handleFileClick(file)}
                      className={`w-full flex items-center space-x-2 p-2.5 rounded-lg text-left text-xs transition-colors group ${
                        selectedFile?.path === file.path
                          ? 'bg-accent/15 text-accent'
                          : 'hover:bg-border/20 text-muted hover:text-bright'
                      }`}
                    >
                      <File className="w-3.5 h-3.5 shrink-0" />
                      <span className="flex-1 font-mono truncate">
                        {file.path.replace(name + '/', '')}
                      </span>
                      <span className="text-[9px] text-muted shrink-0 ml-1">
                        {langFromExt(file.name).toUpperCase()}
                      </span>
                    </button>
                  ))}
                </div>

                {/* Content viewer */}
                <div className="flex-1 overflow-hidden flex flex-col">
                  {!selectedFile ? (
                    <div className="flex items-center justify-center h-full text-muted text-sm italic">
                      Select a file to view its contents.
                    </div>
                  ) : fileLoading ? (
                    <div className="flex items-center justify-center h-full">
                      <Loader2 className="w-6 h-6 text-accent animate-spin" />
                    </div>
                  ) : fileContent?.error ? (
                    <div className="p-4 text-danger text-sm">{fileContent.error}</div>
                  ) : (
                    <>
                      <div className="bg-border/20 px-4 py-2 border-b border-border flex items-center justify-between shrink-0">
                        <span className="text-xs font-mono text-muted truncate">{selectedFile.path}</span>
                        <div className="flex items-center space-x-3 shrink-0 ml-4">
                          <span className="text-[10px] text-accent uppercase font-bold">
                            {langFromExt(selectedFile.name)}
                          </span>
                          <button
                            onClick={() => navigator.clipboard.writeText(fileContent?.content || '')}
                            className="p-1 text-muted hover:text-bright transition-colors"
                            title="Copy content"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                      <div className="flex-1 overflow-auto bg-[#0a0c10]">
                        <pre className="p-4 font-mono text-[11px] text-bright/90 leading-relaxed whitespace-pre-wrap break-words">
                          {fileContent?.content || '(empty file)'}
                        </pre>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
};

export default PhaseDetail;
