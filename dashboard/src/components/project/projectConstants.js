// Shared constants and pure helpers for ProjectView and its sub-components.

export const PHASES = [
  'p01_intake_requirements',
  'p02_architecture',
  'p02b_domain_ir',
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
  'p11a_monitoring',
  'p11b_error_tracking',
  'p11c_analytics',
  'p11d_alerting',
  'p12a_feature_flags',
  'p12b_ab_testing',
  'p13_app_memory',
  'p14_client_portal',
];

export const PHASE_NAMES = {
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
