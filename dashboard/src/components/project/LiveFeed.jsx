import React from 'react';

// Mirrors TerminalLine from ProjectView — must stay in sync
const LINE_STYLES = {
  phase_start:   'text-cyan-400 font-bold',
  phase_end:     'text-emerald-400 font-bold',
  phase_fail:    'text-red-400 font-bold',
  error:         'text-red-400',
  warning:       'text-yellow-400',
  info:          'text-slate-400',
  llm_chunk:     'text-slate-300',
  tool_call:     'text-purple-400',
  tool_result:   'text-purple-300',
  status_update: 'text-indigo-300',
  stream_start:  'text-emerald-300',
  stream_end:    'text-emerald-400',
};

const TerminalLine = ({ text }) => {
  let type = 'info';
  let content = text;
  if (typeof text === 'object' && text !== null) {
    type = text.type || 'info';
    content = text.content || text.message || JSON.stringify(text);
  }
  return (
    <div className={`leading-relaxed whitespace-pre-wrap break-all ${LINE_STYLES[type] || 'text-slate-400'}`}>
      {content}
    </div>
  );
};

const LiveFeed = ({ feedLines, feedDone, feedEndRef, feedContainerRef, isRunning }) => (
  <div className="flex flex-col" style={{ height: '420px', background: '#0a0a0f' }}>
    {/* Header bar */}
    <div className="flex items-center justify-between px-4 py-2 border-b border-white/5 shrink-0">
      <div className="flex items-center space-x-2">
        {isRunning
          ? <><span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" /><span className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest">LIVE</span></>
          : <><span className="w-2 h-2 rounded-full bg-slate-600" /><span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">{feedDone ? 'COMPLETE' : 'IDLE'}</span></>
        }
        <span className="text-[10px] text-slate-600 ml-2">
          {isRunning ? 'AetherOS is building your project…' : feedDone ? 'Build finished.' : 'Waiting for pipeline…'}
        </span>
      </div>
      <span className="text-[10px] font-mono text-slate-700">{feedLines.length} lines</span>
    </div>

    {/* Terminal body */}
    <div ref={feedContainerRef} className="flex-1 overflow-y-auto p-4 font-mono text-[11px] space-y-0.5 custom-scrollbar">
      {feedLines.length === 0 && (
        <div className="text-slate-600 italic">
          {isRunning ? 'Connecting to pipeline stream…' : 'No events yet. Start a run to see live output.'}
        </div>
      )}
      {feedLines.map((line, i) => (
        <TerminalLine key={i} text={line} />
      ))}
      {/* Blinking cursor */}
      {isRunning && (
        <div className="flex items-center">
          <span className="text-emerald-400 animate-pulse">█</span>
        </div>
      )}
      {feedDone && (
        <div className="mt-3 text-emerald-400 font-bold">✓ Build complete</div>
      )}
      <div ref={feedEndRef} />
    </div>
  </div>
);

export default LiveFeed;
