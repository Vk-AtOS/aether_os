import React from 'react';

const PhaseBar = ({ phases = [] }) => {
  // Total 26 phases in AetherOS Factory
  const total = 26;
  const blocks = Array.from({ length: total }, (_, i) => {
    const phaseKey = `p${i.toString().padStart(2, '0')}`;
    const phaseData = phases.find(p => p.id === phaseKey);
    
    let color = 'bg-border/30';
    if (phaseData) {
      if (phaseData.status === 'passed') color = 'bg-success';
      if (phaseData.status === 'failed') color = 'bg-danger';
      if (phaseData.status === 'running') color = 'bg-accent animate-pulse';
      if (phaseData.status === 'escalated') color = 'bg-warning';
    }

    return (
      <div 
        key={i} 
        className={`h-1.5 flex-1 rounded-full ${color}`}
        title={phaseKey}
      ></div>
    );
  });

  return (
    <div className="flex gap-0.5 w-full items-center">
      {blocks}
    </div>
  );
};

export default PhaseBar;
