import * as vscode from 'vscode';

const PHASE_ORDER = [
  'p01_intake_requirements', 'p02_architecture', 'p03_scaffolding',
  'p04_backend', 'p05_frontend', 'p06_review_security', 'p07_testing',
  'p07b_self_healing', 'p08_cicd_deployment', 'p09_observability',
  'p10_docs_delivery', 'p11_deployment',
];

const PHASE_LABEL: Record<string, string> = {
  p01_intake_requirements: 'Intake & Requirements',
  p02_architecture:        'Architecture',
  p03_scaffolding:         'Scaffolding',
  p04_backend:             'Backend',
  p05_frontend:            'Frontend',
  p06_review_security:     'Review & Security',
  p07_testing:             'Testing',
  p07b_self_healing:       'Self-Healing',
  p08_cicd_deployment:     'CI/CD & Deployment',
  p09_observability:       'Observability',
  p10_docs_delivery:       'Docs & Delivery',
  p11_deployment:          'Deployment',
};

const STATUS_EMOJI: Record<string, string> = {
  completed: '✅', passed: '✅', failed: '❌', running: '🔄',
  interrupted: '⚠️', pending: '⏳', timeout: '⏱️',
};

export class StatusPanel {
  private static panels = new Map<string, vscode.WebviewPanel>();

  static show(context: vscode.ExtensionContext, run: any): void {
    const runId = run.run_id || run.id;
    const existing = this.panels.get(runId);
    if (existing) {
      existing.reveal();
      existing.webview.html = this.buildHtml(run);
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      'aetherRunStatus',
      `AetherOS: ${run.project_name || runId}`,
      vscode.ViewColumn.Beside,
      { enableScripts: false },
    );
    panel.webview.html = this.buildHtml(run);
    panel.onDidDispose(() => this.panels.delete(runId));
    this.panels.set(runId, panel);
  }

  private static buildHtml(run: any): string {
    const phases = run.phases || {};
    const cost = run.cost ?? run.total_cost ?? 0;
    const st = (run.status || 'unknown').toLowerCase();
    const stEmoji = STATUS_EMOJI[st] || '❓';

    const phaseRows = PHASE_ORDER.map(p => {
      const info = phases[p] || {};
      const pst  = (info.status || '—').toLowerCase();
      const emoji = STATUS_EMOJI[pst] || '⏳';
      const dur  = info.duration_s;
      const durStr = typeof dur === 'number' ? `${dur.toFixed(1)}s` : '—';
      return `<tr>
        <td>${emoji}</td>
        <td>${PHASE_LABEL[p] || p}</td>
        <td class="st ${pst}">${pst}</td>
        <td>${durStr}</td>
      </tr>`;
    }).join('');

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); background: var(--vscode-editor-background); padding: 20px; }
  h1 { font-size: 1.2em; margin-bottom: 4px; }
  .meta { color: var(--vscode-descriptionForeground); font-size: 0.85em; margin-bottom: 20px; }
  table { border-collapse: collapse; width: 100%; }
  th { text-align: left; color: var(--vscode-descriptionForeground); font-size: 0.75em; text-transform: uppercase; padding: 4px 8px; border-bottom: 1px solid var(--vscode-editorGroup-border); }
  td { padding: 6px 8px; font-size: 0.9em; border-bottom: 1px solid var(--vscode-editorGroup-border); }
  .st.completed, .st.passed { color: #4ec9b0; }
  .st.failed  { color: #f44747; }
  .st.running { color: #569cd6; }
  .st.interrupted { color: #dcdcaa; }
  .card { background: var(--vscode-editor-inactiveSelectionBackground); border-radius: 6px; padding: 12px 16px; margin-bottom: 16px; }
  .pill { display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 0.8em; background: var(--vscode-badge-background); }
</style>
</head>
<body>
  <h1>${run.project_name || run.run_id || 'Factory Run'}</h1>
  <div class="meta">${run.run_id || ''} · ${run.domain || 'general'}</div>
  <div class="card">
    <strong>${stEmoji} ${st.toUpperCase()}</strong>
    &nbsp;&nbsp;
    <span class="pill">Cost: $${cost.toFixed(4)}</span>
    &nbsp;
    <span class="pill">Phase: ${run.current_phase || '—'}</span>
  </div>
  <table>
    <thead><tr><th></th><th>Phase</th><th>Status</th><th>Duration</th></tr></thead>
    <tbody>${phaseRows}</tbody>
  </table>
</body>
</html>`;
  }
}
