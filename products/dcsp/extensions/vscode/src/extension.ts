import * as vscode from 'vscode';

const OUTPUT_CHANNEL_NAME = 'DCSP';
let outputChannel: vscode.OutputChannel;
let statusBarItem: vscode.StatusBarItem;

function getConfig() {
    const config = vscode.workspace
        .getConfiguration('dcsp');
    return {
        serverUrl: config.get<string>(
            'serverUrl',
            'http://localhost:8000'),
        apiKey: config.get<string>(
            'apiKey', ''),
        autoRepair: config.get<boolean>(
            'autoRepair', false)
    };
}

async function checkConnection(): Promise<boolean> {
    const config = getConfig();
    try {
        const response = await fetch(`${config.serverUrl}/health`, {
            signal: AbortSignal.timeout(2000)
        });
        if (response.ok) {
            statusBarItem.text = `$(check) DCSP`;
            statusBarItem.tooltip = `Connected to ${config.serverUrl}`;
            statusBarItem.backgroundColor = undefined;
            return true;
        }
    } catch (err) {
        // Fall through to disconnected state
    }
    statusBarItem.text = `$(warning) DCSP`;
    statusBarItem.tooltip = `Disconnected from ${config.serverUrl}`;
    statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
    return false;
}

async function repairFile(
    uri?: vscode.Uri
): Promise<void> {
    const editor = vscode.window
        .activeTextEditor;
    if (!editor && !uri) {
        vscode.window.showWarningMessage(
            'DCSP: No active file to repair');
        return;
    }

    const fileUri = uri ||
        editor!.document.uri;
    const filePath = fileUri.fsPath;
    const config = getConfig();

    outputChannel.show();
    outputChannel.appendLine(
        `[DCSP] Triggering repair for: ` +
        `${filePath}`);

    try {
        const payload = {
            repo_name: vscode.workspace
                .name || 'vscode-workspace',
            branch: 'main',
            log_content: `File: ${filePath}`,
            ci_system: 'vscode'
        };

        const response = await fetch(
            `${config.serverUrl}` +
            `/webhook/ci-auto`, {
            method: 'POST',
            headers: {
                'Content-Type':
                    'application/json',
                ...(config.apiKey
                    ? {'X-API-Key':
                        config.apiKey}
                    : {})
            },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            const data = await
                response.json() as any;
            vscode.window.showInformationMessage(
                `DCSP: Repair triggered! ` +
                `Confidence: ` +
                `${data.confidence || 'N/A'}`
            );
            outputChannel.appendLine(
                `[DCSP] Success: ` +
                JSON.stringify(data));
        } else {
            vscode.window.showErrorMessage(
                `DCSP: Server returned ` +
                `${response.status}`);
            outputChannel.appendLine(
                `[DCSP] Error: ` +
                `${response.status}`);
        }
    } catch (err) {
        vscode.window.showErrorMessage(
            `DCSP: Connection failed - ` +
            `is the server running?`);
        outputChannel.appendLine(
            `[DCSP] Connection error: ${err}`
        );
    }
}

async function showDashboard(): Promise<void> {
    const config = getConfig();
    const url = vscode.Uri.parse(
        `${config.serverUrl}/dashboard`);
    await vscode.env.openExternal(url);
    outputChannel.appendLine(
        `[DCSP] Opening dashboard: ${url}`);
}

async function configure(): Promise<void> {
    const config = getConfig();
    const url = await vscode.window
        .showInputBox({
            prompt: 'Enter DCSP server URL',
            value: config.serverUrl,
            placeHolder:
                'http://localhost:8000'
        });
    if (url) {
        await vscode.workspace
            .getConfiguration('dcsp')
            .update('serverUrl', url,
                vscode.ConfigurationTarget
                    .Global);
        vscode.window.showInformationMessage(
            `DCSP: Server URL set to ${url}`);
        outputChannel.appendLine(
            `[DCSP] Config updated: ${url}`);
        checkConnection();
    }
}

export function activate(
    context: vscode.ExtensionContext
): void {
    outputChannel = vscode.window
        .createOutputChannel(
            OUTPUT_CHANNEL_NAME);

    outputChannel.appendLine(
        '[DCSP] Extension activated');

    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.command = 'dcsp.checkConnection';
    statusBarItem.text = `$(sync~spin) DCSP`;
    statusBarItem.show();

    context.subscriptions.push(statusBarItem);

    context.subscriptions.push(
        vscode.commands.registerCommand(
            'dcsp.repairFile',
            repairFile),
        vscode.commands.registerCommand(
            'dcsp.showDashboard',
            showDashboard),
        vscode.commands.registerCommand(
            'dcsp.configure',
            configure),
        vscode.commands.registerCommand(
            'dcsp.checkConnection',
            async () => {
                const ok = await checkConnection();
                if (ok) {
                    vscode.window.showInformationMessage('DCSP: Server connection OK');
                } else {
                    vscode.window.showErrorMessage('DCSP: Server unreachable');
                }
            })
    );

    // Initial check
    checkConnection();

    // Auto-repair on save if enabled
    context.subscriptions.push(
        vscode.workspace
            .onDidSaveTextDocument(
                async (doc) => {
                    const cfg = getConfig();
                    if (cfg.autoRepair) {
                        await repairFile(
                            doc.uri);
                    }
                }
            )
    );
}

export function deactivate(): void {
    outputChannel?.appendLine(
        '[DCSP] Extension deactivated');
}
