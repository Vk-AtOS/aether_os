// Shared constants and pure helpers for ProjectView and its sub-components.

// The pipeline runs these 12 stages (orchestrator/phase_sequence.py). The older
// p01…p14 names below are kept only so runs recorded before the stage pipeline
// still get readable labels.
export const PHASES = [
  's01_intake', 's02_architecture', 's03_backend', 's04_frontend', 's05_quality', 's06_testing',
  's07_healing', 's08_observability', 's09_devops', 's10_enterprise', 's11_handoff', 's12_specialist',
];

const STAGE_NAMES = {
  s01_intake: 'Intake', s02_architecture: 'Architecture', s03_backend: 'Backend',
  s04_frontend: 'Frontend', s05_quality: 'Quality gate', s06_testing: 'Testing',
  s07_healing: 'Self-healing', s08_observability: 'Observability', s09_devops: 'Deploy',
  s10_enterprise: 'Enterprise', s11_handoff: 'Handoff', s12_specialist: 'Specialist targets',
};

// Stages an org cannot switch off, and why (orchestrator/stage_gate.py MANDATORY_STAGES).
// s08, s10 and s12 are optional. The server ignores a disable on a mandatory stage.
export const MANDATORY_STAGES = {
  s01_intake: 'every later stage builds from its requirements',
  s02_architecture: 'all code generation reads its domain model',
  s03_backend: 'the frontend, quality, testing and deploy stages need the backend',
  s04_frontend: "later stages read its output; ask for frontend 'none' to build without a UI",
  s05_quality: 'security and quality review is a blocking check and feeds healing',
  s06_testing: 'healing needs its test summary',
  s07_healing: 'it applies the quality-score gate that decides whether the run may ship',
  s09_devops: 'a run is done only when the deployed app answers at its live URL',
  s11_handoff: 'it produces the quality report and the delivery',
};

// Folders (under the run's project root) each stage writes its sub-phase output to.
export const STAGE_DIRS = {
  s01_intake: ['p00_research', 'p00b_data_archaeology', 'p00c_architecture_planner', 'p01_intake_requirements', 'p01b_integration_discovery'],
  s02_architecture: ['p02_architecture', 'p02b_domain_ir', 'p02c_permission_modeling', 'p03_scaffolding'],
  s03_backend: ['p04_backend', 'p04b_business_logic', 'p04c_integration_codegen'],
  s04_frontend: ['p05_frontend'],
  s05_quality: ['p06_review_security', 'p06b_formal_verification'],
  s06_testing: ['p07_testing', 'p07a_unit_testing'],
  s07_healing: ['p07b_self_healing'],
  s08_observability: ['p09_observability', 'p11a_monitoring', 'p11b_error_tracking', 'p11c_analytics', 'p11d_alerting'],
  s09_devops: ['p08_cicd_deployment', 'p11_deployment', 'p11e_enterprise_deployment'],
  s10_enterprise: ['p12a_feature_flags', 'p12b_ab_testing', 'p13_app_memory', 'p16_iam', 'p17_control_plane', 'p18_billing_metering', 'p21_sre_agent'],
  s11_handoff: ['p10_docs_delivery', 'p14_client_portal', 'p15_handoff'],
  s12_specialist: ['p05b_mobile', 'p05c_desktop', 'p05d_cli', 'p05e_serverless', 'p19_service_catalog', 'p20_multiregion'],
};

const SKIP_REASONS = {
  disabled_in_settings: 'Switched off in Settings',
  no_frontend_selected: 'No frontend was requested',
};

const STOPPED = ['failed', 'cancelled', 'interrupted'];
const FINISHED = ['passed', 'completed', 'skipped', 'failed', 'timeout'];

/** From GET /factory/runs/{id}/events: why each stage was skipped, and the stage that stopped a failed run. */
export const summariseRunEvents = (events) => {
  const skipped = {};
  let failedStage = null;
  let failedReason = '';
  for (const e of events || []) {
    const p = e.payload || e;
    const type = e.event_type || p.type;
    if (type === 'phase_complete' && p.status === 'skipped' && p.phase) skipped[p.phase] = p.reason || '';
    if (type === 'pipeline_complete' && p.status === 'failed') {
      if (p.failed_stage) failedStage = p.failed_stage;
      if (p.error) failedReason = p.error;
    }
  }
  return { skipped, failedStage, failedReason };
};

/**
 * Display state of each of the 12 stages: {status, reason}. status is a stage-row status
 * (passed, completed, failed, timeout, skipped, running, pending) or 'not_run' for a stage
 * a stopped run never reached. A failed run's stopping stage is 'failed' with Run.message.
 */
export const stageStates = (run, summary = {}) => {
  const rows = run?.phases || {};
  const stopped = STOPPED.includes(run?.status);
  let stop = null;
  if (run?.status === 'failed') {
    stop = (PHASES.includes(summary.failedStage) && summary.failedStage)
      || [...PHASES].reverse().find((p) => ['failed', 'timeout'].includes(rows[p]?.status))
      || (PHASES.includes(run.current_phase) ? run.current_phase : null);
  }
  const stopIdx = PHASES.indexOf(stop);
  const curIdx = PHASES.indexOf(run?.current_phase);
  const noRows = !Object.keys(rows).length;
  const out = {};
  PHASES.forEach((p, i) => {
    let status = rows[p]?.status;
    let reason = '';
    if (p === stop) {
      status = 'failed';
      reason = run.message || summary.failedReason || '';
    } else if (status === 'skipped') {
      const why = summary.skipped?.[p];
      reason = SKIP_REASONS[why] || (why ? why.replace(/_/g, ' ') : '');
    } else if (stopped && !FINISHED.includes(status || '')) {
      // A stopped run left this stage unfinished or never reached it.
      status = 'not_run';
    } else if (!status) {
      if (['completed', 'passed'].includes(run?.status) && noRows) status = 'passed';
      else if (run?.current_phase === p) status = 'running';
      else if (curIdx > 0 && i < curIdx) status = 'passed';
      else status = 'pending';
    }
    if (stopIdx >= 0 && i > stopIdx && status === 'pending') status = 'not_run';
    out[p] = { status, reason };
  });
  return out;
};

export const STAGE_STATUS_LABEL = {
  passed: 'Passed', completed: 'Completed', failed: 'Failed', timeout: 'Timed out',
  skipped: 'Skipped', running: 'Running', pending: 'Waiting', not_run: 'Not run',
};

export const PHASE_NAMES = {
  ...STAGE_NAMES,
  p01_intake_requirements: 'Intake',
  p02_architecture:        'Architecture',
  p02b_domain_ir:          'Domain IR',
  p03_scaffolding:         'Scaffolding',
  p04_backend:             'Backend',
  p05_frontend:            'Frontend',
  p06_review_security:     'Review',
  p07_testing:             'Testing',
  p07b_self_healing:       'Self-Healing',
  p08_cicd_deployment:     'CI/CD',
  p09_observability:       'Observability',
  p10_docs_delivery:       'Delivery',
  p11_deployment:          'Deployment',
  p11a_monitoring:         'Monitoring',
  p11b_error_tracking:     'Error Tracking',
  p11c_analytics:          'Analytics',
  p11d_alerting:           'Alerting',
  p12a_feature_flags:      'Feature Flags',
  p12b_ab_testing:         'A/B Testing',
  p13_app_memory:          'App Memory',
  p14_client_portal:       'Client Portal',
};

export const PHASE_LABELS = {
  ...STAGE_NAMES,
  p01_intake_requirements: 'Intake & Requirements',
  p02_architecture:        'Architecture Design',
  p02b_domain_ir:          'Domain IR Extraction',
  p03_scaffolding:         'Project Scaffolding',
  p04_backend:             'Backend Codegen',
  p05_frontend:            'Frontend Codegen',
  p06_review_security:     'Code Review & Security',
  p07_testing:             'Testing Suite',
  p07b_self_healing:       'Self-Healing',
  p08_cicd_deployment:     'CI/CD & Deployment',
  p09_observability:       'Observability',
  p10_docs_delivery:       'Docs & Delivery',
  p11_deployment:          'Deployment',
  p11a_monitoring:         'Monitoring & Metrics',
  p11b_error_tracking:     'Error Tracking',
  p11c_analytics:          'Analytics',
  p11d_alerting:           'Alerting & Runbooks',
  p12a_feature_flags:      'Feature Flags',
  p12b_ab_testing:         'A/B Testing',
  p13_app_memory:          'App Memory Layer',
  p14_client_portal:       'Client Portal',
};

export const PRIORITY_CONFIG = {
  high:   { label: 'High',   color: 'text-red-400',   dot: 'bg-red-400'   },
  normal: { label: 'Normal', color: 'text-slate-400', dot: 'bg-slate-400' },
  low:    { label: 'Low',    color: 'text-blue-400',  dot: 'bg-blue-400'  },
};

export const PRIORITY_CYCLE = ['high', 'normal', 'low'];

export const formatBytes = (bytes) => {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}K`;
  return `${(bytes / 1024 / 1024).toFixed(1)}M`;
};

export const countFiles = (items) => {
  let n = 0;
  for (const item of items) {
    if (item.type === 'file') n++;
    else if (item.children) n += countFiles(item.children);
  }
  return n;
};

export const formatTime = (seconds) => {
  if (!seconds || seconds < 0) return '0m 00s';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s.toString().padStart(2, '0')}s`;
};

export const findIndexHtml = (items) => {
  for (const item of items) {
    if (item.type === 'file' && item.name === 'index.html') return item;
    if (item.children) {
      const found = findIndexHtml(item.children);
      if (found) return found;
    }
  }
  return null;
};

export const getMonacoLanguage = (filename) => {
  if (!filename) return 'plaintext';
  const ext = filename.split('.').pop()?.toLowerCase();
  const map = {
    py: 'python', js: 'javascript', jsx: 'javascript', ts: 'typescript',
    tsx: 'typescript', json: 'json', md: 'markdown', yml: 'yaml',
    yaml: 'yaml', html: 'html', css: 'css', sh: 'shell', txt: 'plaintext',
    toml: 'toml', env: 'plaintext', sql: 'sql', dockerfile: 'dockerfile',
  };
  return map[ext] || 'plaintext';
};

/** Format a pipeline SSE event into a terminal line string. */
export const formatEvent = (event) => {
  switch (event.type) {
    case 'phase_start':
      return `\x1b[36m▶ [${event.phase}] ${PHASE_LABELS[event.phase] || event.phase}…\x1b[0m`;
    case 'phase_complete': {
      const dur   = event.duration ? ` in ${event.duration}s` : '';
      const icon  = event.status === 'passed'  ? '✓'
                  : event.status === 'timeout' ? '⏱'
                  : event.status === 'failed'  ? '✗'
                  : '✓';
      const color = event.status === 'passed'  ? '\x1b[32m'
                  : event.status === 'failed'  ? '\x1b[31m'
                  : '\x1b[33m';
      return `${color}${icon} [${event.phase}] ${event.status}${dur}\x1b[0m`;
    }
    case 'file_written': {
      const kb = event.size ? ` (${formatBytes(event.size)})` : '';
      return `\x1b[90m  → wrote ${event.path}${kb}\x1b[0m`;
    }
    case 'llm_chunk':
      return event.text || '';
    case 'pipeline_complete':
      return event.status === 'cancelled'
        ? '\x1b[33m✕ Pipeline cancelled\x1b[0m'
        : '\x1b[32m✓ Build complete\x1b[0m';
    case 'heartbeat':
    case 'no_stream':
      return null;
    default:
      return null;
  }
};

/** The stage a sub-phase output folder (e.g. 'p04_backend') belongs to, or the id itself if it is a stage. */
export const stageOfDir = (dir) =>
  PHASES.includes(dir) ? dir : PHASES.find((s) => STAGE_DIRS[s].includes(dir)) || null;
