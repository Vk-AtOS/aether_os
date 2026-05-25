import React from 'react';

// Canonical 10-phase order matching orchestrator/factory_pipeline.py PHASE_SEQUENCE
const PHASE_ORDER = [
  'p01_intake_requirements',
  'p02_architecture',
  'p03_scaffolding',
  'p04_backend',
  'p05_frontend',
  'p06_review_security',
  'p07_testing',
  'p07b_self_healing',
  'p08_cicd_deployment',
  'p09_observability',
  'p10_docs_delivery',
  'p11_deployment',
];

const PhaseBar = ({ phases }) => {
  // phases may be a dict { phase_name: { status, updated_at } } or empty/null
  const phaseDict = (phases && typeof phases === 'object' && !Array.isArray(phases))
    ? phases
    : {};

  const blocks = PHASE_ORDER.map((id) => {
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
        title={id}
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
