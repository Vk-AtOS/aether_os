import React, { useState, useEffect } from 'react';
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
  Copy
} from 'lucide-react';

const PhaseDetail = () => {
  const { id, name } = useParams();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('output');
  const [phaseData, setPhaseData] = useState(null);

  useEffect(() => {
    const fetchDetail = async () => {
      try {
        const res = await api.getRun(id);
        const run = res.data;
        // Extract phase-specific data from the run
        const phases = Array.isArray(run.phases) ? run.phases : Object.values(run.phases || {});
        const phase = phases.find(p => p.id === name || p.name === name) || {};
        setPhaseData({
          name: phase.name || name,
          status: phase.status || run.status,
          confidence: phase.confidence || 0,
          duration: phase.duration || '—',
          files: phase.files || {},
          gate_result: phase.gate_result || { passed: phase.status === 'passed', confidence: phase.confidence || 0, issues: [], attempts: 1 },
          memories: phase.memories || [],
        });
      } catch (err) {
        console.error('Failed to load phase detail', err);
        setPhaseData({
          name: name,
          status: 'unknown',
          confidence: 0,
          duration: '—',
          files: {},
          gate_result: { passed: false, confidence: 0, issues: ['Could not load phase data'], attempts: 0 },
          memories: [],
        });
      }
    };
    fetchDetail();
  }, [id, name]);

  if (!phaseData) return <div className="p-8 text-center text-muted">Loading phase details...</div>;

  const tabs = [
    { id: 'output', name: 'Output', icon: FileText },
    { id: 'gate', name: 'Gate Result', icon: ShieldCheck },
    { id: 'memory', name: 'Memory Used', icon: Brain },
    { id: 'artifacts', name: 'Raw Artifacts', icon: Files },
  ];

  const renderFileContent = (content, filename) => {
    const isJson = filename.endsWith('.json');
    const isPython = filename.endsWith('.py');
    return (
      <div className="relative group">
        <div className="absolute right-4 top-4 flex space-x-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button className="p-2 bg-panel border border-border rounded-lg text-muted hover:text-bright transition-colors" title="Copy Content">
            <Copy className="w-4 h-4" />
          </button>
          <button className="p-2 bg-panel border border-border rounded-lg text-muted hover:text-bright transition-colors" title="Download File">
            <Download className="w-4 h-4" />
          </button>
        </div>
        <pre className="p-6 bg-[#0a0c10] rounded-xl border border-border overflow-x-auto custom-scrollbar font-mono text-sm leading-relaxed text-bright/90">
          <code>{content}</code>
        </pre>
      </div>
    );
  };

  return (
    <div className="space-y-6">
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
              <h1 className="text-xl font-bold">{phaseData.name}</h1>
              <span className="text-xs font-mono text-muted">{name}</span>
              <PhaseBadge status={phaseData.status} />
            </div>
            <div className="text-[10px] text-muted font-mono mt-1 uppercase">
              Duration: {phaseData.duration} • Confidence: {Math.round(phaseData.confidence*100)}%
            </div>
          </div>
        </div>
      </header>

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

      <div className="mt-6">
        {activeTab === 'output' && (
          <div className="space-y-8">
            {Object.entries(phaseData.files || {}).map(([name, content]) => (
              <div key={name}>
                <div className="flex items-center text-xs font-bold text-muted uppercase tracking-[0.2em] mb-3 ml-1">
                   <ChevronRight className="w-3 h-3 mr-1 text-accent" /> {name}
                </div>
                {renderFileContent(content, name)}
              </div>
            ))}
          </div>
        )}

        {activeTab === 'gate' && (
          <div className="panel p-8 max-w-2xl">
            <div className="flex items-center space-x-4 mb-8">
               <div className={`w-12 h-12 rounded-full flex items-center justify-center ${phaseData.gate_result.passed ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}>
                  <ShieldCheck className="w-6 h-6" />
               </div>
               <div>
                  <h3 className="text-lg font-bold">Gate {phaseData.gate_result.passed ? 'Passed' : 'Failed'}</h3>
                  <p className="text-sm text-muted">Quality verification check completed with {Math.round(phaseData.gate_result.confidence*100)}% confidence.</p>
               </div>
            </div>

            <div className="grid grid-cols-2 gap-8">
               <div>
                  <h4 className="text-xs font-bold text-muted uppercase tracking-wider mb-4">Verification Stats</h4>
                  <div className="space-y-4">
                     <div className="flex justify-between text-sm">
                        <span className="text-muted">Attempts Required</span>
                        <span className="font-mono">{phaseData.gate_result.attempts}</span>
                     </div>
                     <div className="flex justify-between text-sm">
                        <span className="text-muted">Confidence Threshold</span>
                        <span className="font-mono text-success">0.85 (PASSED)</span>
                     </div>
                  </div>
               </div>
               <div>
                  <h4 className="text-xs font-bold text-muted uppercase tracking-wider mb-4">Issues Found</h4>
                  {phaseData.gate_result.issues.length > 0 ? (
                    <ul className="space-y-2">
                       {phaseData.gate_result.issues.map((issue, i) => (
                         <li key={i} className="text-sm text-danger flex items-start">
                            <span className="mr-2">•</span> {issue}
                         </li>
                       ))}
                    </ul>
                  ) : (
                    <div className="text-sm text-success flex items-center">
                       <ShieldCheck className="w-4 h-4 mr-2" /> No critical issues detected.
                    </div>
                  )}
               </div>
            </div>
          </div>
        )}

        {activeTab === 'memory' && (
          <div className="space-y-4">
            {phaseData.memories?.map((mem, i) => (
              <div key={i} className="panel p-6 flex items-start space-x-6">
                 <div className="shrink-0 flex flex-col items-center">
                    <div className="text-[10px] font-bold text-muted uppercase tracking-tighter mb-1">Score</div>
                    <div className="text-lg font-bold text-accent font-mono">{(mem.score * 100).toFixed(0)}%</div>
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
            ))}
            {(!phaseData.memories || phaseData.memories.length === 0) && (
              <div className="panel p-8 text-center text-muted">No memories were retrieved for this phase.</div>
            )}
          </div>
        )}

        {activeTab === 'artifacts' && (
          <div className="panel overflow-hidden">
             <div className="bg-border/20 px-4 py-3 border-b border-border text-xs font-bold text-muted uppercase tracking-wider">
                Output Directory: /outputs/{id}/{name}
             </div>
             <div className="p-2">
                {Object.keys(phaseData.files || {}).map((filename) => (
                   <div key={filename} className="flex items-center justify-between p-3 rounded-lg hover:bg-border/20 transition-colors group cursor-pointer">
                      <div className="flex items-center space-x-3">
                         <Files className="w-4 h-4 text-muted group-hover:text-accent transition-colors" />
                         <span className="text-sm text-bright/90 font-mono">{filename}</span>
                      </div>
                      <div className="text-[10px] text-muted font-mono opacity-0 group-hover:opacity-100 transition-opacity">
                         VIEW RAW CONTENT
                      </div>
                   </div>
                ))}
             </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default PhaseDetail;
