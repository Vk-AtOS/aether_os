import * as vscode from 'vscode';
import { RunsProvider, RunItem } from './runsProvider';
import { AetherClient } from './client';
import { StatusPanel } from './statusPanel';

let autoRefreshTimer: ReturnType<typeof setInterval> | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const client = new AetherClient();
  const runsProvider = new RunsProvider(client);

  const runsView = vscode.window.createTreeView('aetheros.runsView', {
    treeDataProvider: runsProvider,
    showCollapseAll: false,
  });

  // Status bar item
  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 10);
  statusBar.command = 'aetheros.listRuns';
  statusBar.show();

  const updateStatusBar = async () => {
    try {
      const runs = await client.listRuns(5);
      const active = runs.filter((r: any) => r.status === 'running').length;
      if (active > 0) {
        statusBar.text     = `$(loading~spin) AetherOS: ${active} running`;
        statusBar.tooltip  = 'AetherOS Factory — click to view runs';
        statusBar.color    = new vscode.ThemeColor('statusBarItem.warningForeground');
      } else {
        statusBar.text     = '$(rocket) AetherOS';
        statusBar.tooltip  = 'AetherOS Factory — click to view runs';
        statusBar.color    = undefined;
      }
    } catch {
      statusBar.text    = '$(rocket) AetherOS';
      statusBar.color   = undefined;
    }
  };

  const startAutoRefresh = () => {
    if (autoRefreshTimer) clearInterval(autoRefreshTimer);
    const cfg = vscode.workspace.getConfiguration('aetheros');
    const secs = Math.max(5, cfg.get<number>('autoRefreshSeconds', 15));
    autoRefreshTimer = setInterval(() => {
      runsProvider.refresh();
      updateStatusBar();
    }, secs * 1000);
  };

  startAutoRefresh();
  updateStatusBar();

  // ── Commands ──────────────────────────────────────────────────────────────

  context.subscriptions.push(
    runsView,
    statusBar,

    vscode.commands.registerCommand('aetheros.configure', async () => {
      const url = await vscode.window.showInputBox({
        prompt: 'AetherOS Gateway URL',
        value: vscode.workspace.getConfiguration('aetheros').get('gatewayUrl', 'http://localhost:8000'),
        placeHolder: 'http://localhost:8000',
      });
      if (!url) return;
      await vscode.workspace.getConfiguration('aetheros').update('gatewayUrl', url, true);

      const email = await vscode.window.showInputBox({ prompt: 'Email', placeHolder: 'you@example.com' });
      if (!email) return;
      const password = await vscode.window.showInputBox({ prompt: 'Password', password: true });
      if (!password) return;

      try {
        const token = await client.login(url, email, password);
        await vscode.workspace.getConfiguration('aetheros').update('token', token, true);
        vscode.window.showInformationMessage(`AetherOS: Logged in as ${email}`);
        runsProvider.refresh();
        updateStatusBar();
      } catch (e: any) {
        vscode.window.showErrorMessage(`AetherOS login failed: ${e.message}`);
      }
    }),

    vscode.commands.registerCommand('aetheros.newRun', async () => {
      const req = await vscode.window.showInputBox({
        prompt: 'Describe what you want to build',
        placeHolder: 'e.g. A REST API for a todo app with auth and PostgreSQL',
      });
      if (!req) return;

      const domain = await vscode.window.showQuickPick(
        ['general', 'web', 'api', 'data', 'mobile', 'cli', 'saas'],
        { placeHolder: 'Select project domain' }
      ) || 'general';

      const name = await vscode.window.showInputBox({
        prompt: 'Project name (optional)',
        placeHolder: 'my-awesome-app',
      });

      try {
        const run = await client.startRun(req, domain, name || undefined);
        const runId = run.run_id || run.id;
        vscode.window.showInformationMessage(
          `AetherOS: Run started — ${runId}`,
          'View Logs'
        ).then(choice => {
          if (choice === 'View Logs') {
            vscode.commands.executeCommand('aetheros.streamLogs', { runId });
          }
        });
        runsProvider.refresh();
      } catch (e: any) {
        vscode.window.showErrorMessage(`AetherOS: Failed to start run — ${e.message}`);
      }
    }),

    vscode.commands.registerCommand('aetheros.refreshRuns', () => {
      runsProvider.refresh();
      updateStatusBar();
    }),

    vscode.commands.registerCommand('aetheros.showStatus', async (item?: RunItem) => {
      const runId = item?.runId || await vscode.window.showInputBox({ prompt: 'Run ID' });
      if (!runId) return;
      try {
        const run = await client.getRun(runId);
        StatusPanel.show(context, run);
      } catch (e: any) {
        vscode.window.showErrorMessage(`AetherOS: ${e.message}`);
      }
    }),

    vscode.commands.registerCommand('aetheros.streamLogs', async (item?: RunItem | { runId: string }) => {
      const runId = (item as any)?.runId || await vscode.window.showInputBox({ prompt: 'Run ID' });
      if (!runId) return;
      const ch = vscode.window.createOutputChannel(`AetherOS — ${runId}`, { log: false });
      ch.show(true);
      ch.appendLine(`[AetherOS] Streaming logs for run: ${runId}`);
      ch.appendLine('─'.repeat(60));
      client.streamLogs(runId, (event) => {
        const ts = new Date().toLocaleTimeString();
        const phase = event.phase ? `[${event.phase}] ` : '';
        ch.appendLine(`${ts} ${phase}${event.message || event.log || JSON.stringify(event)}`);
        if (event.type === 'complete') {
          ch.appendLine('─'.repeat(60));
          ch.appendLine('[AetherOS] Run complete.');
          runsProvider.refresh();
        }
      }).catch((e: Error) => ch.appendLine(`[ERROR] ${e.message}`));
    }),

    vscode.commands.registerCommand('aetheros.cancelRun', async (item?: RunItem) => {
      const runId = item?.runId || await vscode.window.showInputBox({ prompt: 'Run ID to cancel' });
      if (!runId) return;
      const confirm = await vscode.window.showWarningMessage(
        `Cancel run ${runId}?`, { modal: true }, 'Yes, Cancel'
      );
      if (confirm !== 'Yes, Cancel') return;
      try {
        await client.cancelRun(runId);
        vscode.window.showInformationMessage(`AetherOS: Cancelled ${runId}`);
        runsProvider.refresh();
      } catch (e: any) {
        vscode.window.showErrorMessage(`AetherOS: ${e.message}`);
      }
    }),

    vscode.commands.registerCommand('aetheros.openDashboard', () => {
      const cfg = vscode.workspace.getConfiguration('aetheros');
      const base = cfg.get<string>('gatewayUrl', 'http://localhost:8000');
      const url = base.replace(':8000', ':3000').replace(':8080', ':3000');
      vscode.env.openExternal(vscode.Uri.parse(url));
    }),

    vscode.commands.registerCommand('aetheros.openProjectFolder', async (item?: RunItem) => {
      const runId = item?.runId || await vscode.window.showInputBox({ prompt: 'Run ID to open' });
      if (!runId) return;
      vscode.window.showInformationMessage('AetherOS: Opening project in VS Code…');
      try {
        const result = await client.openInVSCode(runId);
        if (!result.opened) {
          vscode.window.showWarningMessage(`AetherOS: ${result.error || 'Could not open in VS Code'}`);
          return;
        }
        if (result.path) {
          vscode.commands.executeCommand(
            'vscode.openFolder',
            vscode.Uri.parse('vscode://file/' + result.path)
          );
        }
      } catch (e: any) {
        vscode.window.showErrorMessage(`AetherOS: ${e.message}`);
      }
    }),

    vscode.workspace.onDidChangeConfiguration(e => {
      if (e.affectsConfiguration('aetheros.autoRefreshSeconds')) startAutoRefresh();
    }),
  );
}

export function deactivate(): void {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
}
