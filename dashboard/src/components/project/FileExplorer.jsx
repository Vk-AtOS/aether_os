/**
 * FileExplorer — generated file browser + Monaco editor tab.
 * Corresponds to the "Artifacts" tab in ProjectView.
 */
import React, { useState } from 'react';
import Editor from '@monaco-editor/react';
import { Folder, FolderOpen, File, Loader2, ChevronDown } from 'lucide-react';
import { formatBytes, getMonacoLanguage, countFiles } from './projectConstants';
import { api } from '../../api';

// ── FileTree ──────────────────────────────────────────────────────────────────

const FileTree = ({ items, level = 0, onFileClick, selectedPath }) => {
  const [openDirs, setOpenDirs] = useState({});
  const toggle = (path) => setOpenDirs((prev) => ({ ...prev, [path]: !prev[path] }));

  return (
    <div className={level > 0 ? 'ml-3 border-l border-border/30 pl-2' : ''}>
      {items.map((item) =>
        item.type === 'directory' ? (
          <div key={item.path}>
            <button
              onClick={() => toggle(item.path)}
              className="w-full flex items-center space-x-1.5 py-1 px-2 rounded hover:bg-border/20 text-left text-xs"
            >
              {openDirs[item.path]
                ? <FolderOpen className="w-3.5 h-3.5 text-accent shrink-0" />
                : <Folder    className="w-3.5 h-3.5 text-accent shrink-0" />}
              <span className="text-bright font-medium truncate">{item.name}</span>
              <ChevronDown className={`w-3 h-3 text-muted ml-auto transition-transform shrink-0 ${openDirs[item.path] ? '' : '-rotate-90'}`} />
            </button>
            {openDirs[item.path] && item.children && (
              <FileTree items={item.children} level={level + 1} onFileClick={onFileClick} selectedPath={selectedPath} />
            )}
          </div>
        ) : (
          <button
            key={item.path}
            onClick={() => onFileClick(item)}
            className={`w-full flex items-center space-x-1.5 py-1 px-2 rounded text-left text-xs transition-colors ${
              selectedPath === item.path
                ? 'bg-accent/20 text-accent'
                : 'hover:bg-border/20 text-muted hover:text-bright'
            }`}
          >
            <File className="w-3 h-3 shrink-0" />
            <span className="truncate">{item.name}</span>
            <span className="ml-auto text-[9px] text-muted shrink-0">{formatBytes(item.size_bytes)}</span>
          </button>
        )
      )}
    </div>
  );
};

// ── FileExplorer ──────────────────────────────────────────────────────────────

const FileExplorer = ({ runId, fileTree, isViewer, onToast }) => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent]   = useState(null);
  const [fileLoading, setFileLoading]   = useState(false);
  const [editContent, setEditContent]   = useState(null);
  const [editSaving, setEditSaving]     = useState(false);

  const handleFileClick = async (file) => {
    setSelectedFile(file);
    setFileLoading(true);
    setFileContent(null);
    try {
      const res = await api.getFileContent(runId, file.path);
      setFileContent(res.data);
    } catch {
      setFileContent({ error: 'Failed to load file content.' });
    } finally {
      setFileLoading(false);
    }
  };

  return (
    <div className="flex h-[420px]">
      {/* File tree sidebar */}
      <div className="w-64 border-r border-border overflow-y-auto p-2 custom-scrollbar shrink-0">
        {fileTree === null ? (
          <div className="flex items-center justify-center h-full text-muted text-xs">
            <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> Loading...
          </div>
        ) : fileTree.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted text-xs italic">No artifacts yet.</div>
        ) : (
          <>
            <div className="px-2 pb-1 text-[10px] text-muted">{countFiles(fileTree)} files</div>
            <FileTree items={fileTree} onFileClick={handleFileClick} selectedPath={selectedFile?.path} />
          </>
        )}
      </div>

      {/* Editor pane */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {!selectedFile ? (
          <div className="flex items-center justify-center h-full text-muted text-sm italic">Select a file to preview.</div>
        ) : fileLoading ? (
          <div className="flex items-center justify-center h-full"><Loader2 className="w-6 h-6 text-accent animate-spin" /></div>
        ) : fileContent?.error ? (
          <div className="p-4 text-danger text-sm">{fileContent.error}</div>
        ) : (
          <>
            <div className="bg-border/20 px-4 py-2 border-b border-border flex items-center justify-between shrink-0">
              <span className="text-xs font-mono text-muted truncate">{selectedFile.path}</span>
              <div className="flex items-center space-x-3 shrink-0 ml-4">
                {fileContent?.truncated && <span className="text-[10px] text-warning">Truncated (50K)</span>}
                <span className="text-[10px] text-muted">{formatBytes(fileContent?.size_bytes)}</span>
                {!isViewer && editContent === null ? (
                  <button
                    onClick={() => setEditContent(fileContent?.content || '')}
                    className="text-[10px] px-2 py-0.5 bg-indigo-700 hover:bg-indigo-600 text-white rounded transition-colors"
                  >Edit</button>
                ) : editContent !== null ? (
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => setEditContent(null)}
                      className="text-[10px] px-2 py-0.5 bg-slate-700 hover:bg-slate-600 text-white rounded transition-colors"
                    >Cancel</button>
                    <button
                      disabled={editSaving}
                      onClick={async () => {
                        setEditSaving(true);
                        try {
                          await api.patchFileContent(runId, selectedFile.path, editContent);
                          setFileContent(prev => ({ ...prev, content: editContent }));
                          setEditContent(null);
                          onToast('File saved.');
                        } catch {
                          onToast('Save failed.');
                        } finally {
                          setEditSaving(false);
                        }
                      }}
                      className="text-[10px] px-2 py-0.5 bg-emerald-700 hover:bg-emerald-600 text-white rounded transition-colors disabled:opacity-50"
                    >{editSaving ? 'Saving…' : 'Save'}</button>
                  </div>
                ) : null}
              </div>
            </div>
            <div className="flex-1 overflow-hidden" style={{ minHeight: 0 }}>
              <Editor
                height="100%"
                defaultLanguage={getMonacoLanguage(selectedFile?.name)}
                value={editContent !== null ? editContent : (fileContent?.content || '')}
                onChange={editContent !== null ? (v) => setEditContent(v || '') : undefined}
                options={{
                  readOnly: editContent === null,
                  minimap: { enabled: false },
                  fontSize: 11,
                  lineNumbers: 'on',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  theme: 'vs-dark',
                  padding: { top: 8 },
                }}
                theme="vs-dark"
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default FileExplorer;
