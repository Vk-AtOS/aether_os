import React from 'react';
import { PHASES, PHASE_NAMES } from './project/projectConstants';

const PhaseBar = ({ phases }) => {
  // phases may be a dict { phase_name: { status, updated_at } } or empty/null
  const phaseDict = (phases && typeof phases === 'object' && !Array.isArray(phases))
    ? phases
    : {};

  const blocks = PHASES.map((id) => {
    const status = phaseDict[id]?.status ?? 'pending';
    let color = 'bg-border/30';
    if (status === 'passed' || status === 'completed') color = 'bg-success';
    else if (status === 'failed')                       color = 'bg-danger';
    else if (status === 'running')                      color = 'bg-accent animate-pulse';
    else if (status === 'escalated')                    color = 'bg-warning';

    return (
      <div
        key={id}
        className={`h-1.5 flex-1 rounded-full ${color}`}
        title={PHASE_NAMES[id]}
      />
    );
  });

  return (
    <div className="flex gap-0.5 w-full items-center">
      {blocks}
    </div>
  );
};

export default PhaseBar;
