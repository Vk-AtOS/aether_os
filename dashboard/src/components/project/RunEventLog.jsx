/**
 * RunEventLog — SSE live feed terminal tab + Agent Events log section.
 * Exported as two named components:
 *   - LiveFeedTab: the "LIVE" tab terminal content
 *   - AgentEventsLog: the agent events section at the bottom of the page
 */
import React, { useRef } from 'react';
import { Terminal } from 'lucide-react';

// ANSI terminal renderer

const ANSI_MAP = {
  '\x1b[32m': 'text-emerald-400',
  '\x1b[31m': 'text-red-400',
  '\x1b[33m': 'text-yellow-400',
  '\x1b[36m': 'text-indigo-400',
  '\x1b[90m': 'text-slate-500',
  '\x1b[0m':  '',
};

export const TerminalLine = ({ text }) => {
  const parts = [];
  let currentClass = 'text-emerald-300';
  const re = /(\x1b\[[0-9;]*m)/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      parts.push({ text: text.slice(last, m.index), cls: currentClass });
    }
    currentClass = ANSI_MAP[m[0]] || '';
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), cls: currentClass });
  if (parts.length === 0) parts.push({ text, cls: currentClass });

  return (
    <div className="leading-relaxed whitespace-pre-wrap break-all">
      {parts.map((p, i) => (
        <span key={i} className={p.cls || 'text-emerald-300/70'}>{p.text}</span>
      ))}
    </div>
  );
};

// LiveFeedTab

export const LiveFeedTab = ({ feedLines, feedDone, isRunning, feedContainerRef, feedEndRef }) => (
  <div className="flex flex-col" style={{ height: '420px', background: '#0a0a0f' }}>
    <div className="flex items-center justify-between px-4 py-2 border-b border-white/5 shrink-0">
      <div className="flex items-center space-x-2">
        {isRunning
          ? <><span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" /><span className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest">LIVE</span></>
          : <><span className="w-2 h-2 rounded-full bg-slate-600" /><span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">{feedDone ? 'COMPLETE' : 'IDLE'}</span></>
        }
        <span className="text-[10px] text-slate-600 ml-2">
          {isRunning ? 'AetherOS is building your project...' : feedDone ? 'Build finished.' : 'Waiting for pipeline...'}
        </span>
      </div>
      <span className="text-[10px] font-mono text-slate-700">{feedLines.length} lines</span>
    </div>
    <div ref={feedContainerRef} className="flex-1 overflow-y-auto p-4 font-mono text-[11px] space-y-0.5 custom-scrollbar">
      {feedLines.length === 0 && (
        <div className="text-slate-600 italic">
          {isRunning ? 'Connecting to pipeline stream...' : 'No events yet. Start a run to see live output.'}
        </div>
      )}
      {feedLines.map((line, i) => (
        <TerminalLine key={i} text={line} />
      ))}
      {isRunning && (
        <div className="flex items-center">
          <span className="text-emerald-400 animate-pulse">X</span>
        </div>
      )}
      {feedDone && (
        <div className="mt-3 text-emerald-400 font-bold">Build complete</div>
      )}
      <div ref={feedEndRef} />
    </div>
  </div>
);

// AgentEventsLog

export const AgentEventsLog = ({ events }) => {
  const logContainerRef = useRef(null);
  const logEndRef = useRef(null);

  React.useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <section>
      <div className="panel overflow-hidden flex flex-col h-[280px]">
        <div className="bg-border/20 px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
          <div className="flex items-center text-xs font-bold text-muted uppercase tracking-wider">
            <Terminal className="w-4 h-4 mr-2 text-accent" /> Agent Events
          </div>
          <span className="text-[10px] font-mono text-muted">{events.length} entries</span>
        </div>
        <div ref={logContainerRef} className="flex-1 overflow-y-auto p-4 font-mono text-[11px] space-y-1 custom-scrollbar bg-[#0a0c10]">
          {events.length > 0 ? (
            events.map((ev, i) => (
              <div key={i} className="flex space-x-3 leading-relaxed">
                <span className="text-muted shrink-0 w-20 text-[10px]">
                  {ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : '---'}
                </span>
                <span className="text-accent shrink-0 w-24 uppercase font-bold text-[10px] truncate">{ev.agent}</span>
                <span className="text-bright/90 truncate">
                  {ev.action}
                  {ev.detail ? ' --- ' + (typeof ev.detail === 'string' ? ev.detail.slice(0, 100) : JSON.stringify(ev.detail).slice(0, 100)) : ''}
                </span>
              </div>
            ))
          ) : (
            <div className="h-full flex items-center justify-center text-muted italic">
              No events recorded for this run.
            </div>
          )}
          <div ref={logEndRef} />
        </div>
      </div>
    </section>
  );
};
