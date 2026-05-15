import * as vscode from 'vscode';
import { AetherClient } from './client';

const STATUS_ICONS: Record<string, string> = {
  running:     '$(loading~spin)',
  completed:   '$(check)',
  failed:      '$(error)',
  interrupted: '$(warning)',
  pending:     '$(circle-outline)',
  passed:      '$(check)',
};

const PHASE_ORDER = [
  'p01_intake_requirements', 'p02_architecture', 'p03_scaffolding',
  'p04_backend', 'p05_frontend', 'p06_review_security', 'p07_testing',
  'p07b_self_healing', 'p08_cicd_deployment', 'p09_observability',
  'p10_docs_delivery', 'p11_deployment',
];

function phaseProgress(phases: Record<string, any>): string {
  if (!phases) return '0/12';
  const done = PHASE_ORDER.filter(p => ['passed','completed','timeout'].includes(phases[p]?.status || '')).length;
  return `${done}/${PHASE_ORDER.length}`;
}

export class RunItem extends vscode.TreeItem {
  constructor(
    public readonly runId: string,
    public readonly run:   any,
  ) {
    const label = run.project_name || runId.slice(0, 16);
    super(label, vscode.TreeItemCollapsibleState.None);
    const st = (run.status || 'unknown').toLowerCase();
    const icon = STATUS_ICONS[st] || '$(circle-outline)';
    this.iconPath = new vscode.ThemeIcon(icon.replace(/\$\(|\)/g, ''));
    this.description = `${st} · ${phaseProgress(run.phases || {})}`;
    this.tooltip     = `${run.project_name || runId}\nStatus: ${run.status}\nID: ${runId}`;
    this.contextValue = 'run';
    this.command = {
      command:   'aetheros.showStatus',
      title:     'Show Status',
      arguments: [this],
    };
  }
}

export class RunsProvider implements vscode.TreeDataProvider<RunItem> {
  private _onDidChange = new vscode.EventEmitter<RunItem | undefined | null>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  constructor(private client: AetherClient) {}

  refresh(): void { this._onDidChange.fire(undefined); }

  getTreeItem(el: RunItem): vscode.TreeItem { return el; }

  async getChildren(): Promise<RunItem[]> {
    try {
      const runs = await this.client.listRuns(30);
      return runs.map((r: any) => new RunItem(r.run_id || r.id, r));
    } catch {
      return [];
    }
  }
}
