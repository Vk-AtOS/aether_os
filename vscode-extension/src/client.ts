import * as vscode from 'vscode';

interface LogEvent {
  phase?:   string;
  message?: string;
  log?:     string;
  type?:    string;
  [key: string]: unknown;
}

export class AetherClient {
  private get gatewayUrl(): string {
    return vscode.workspace.getConfiguration('aetheros').get<string>('gatewayUrl', 'http://localhost:8000').replace(/\/$/, '');
  }

  private get token(): string {
    return vscode.workspace.getConfiguration('aetheros').get<string>('token', '');
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    return { 'Authorization': `Bearer ${this.token}`, 'Content-Type': 'application/json', ...extra };
  }

  private async fetch<T>(path: string, init?: RequestInit): Promise<T> {
    const url = `${this.gatewayUrl}${path}`;
    const res = await fetch(url, { headers: this.headers(), ...init });
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new Error(`${res.status} ${res.statusText}: ${body}`);
    }
    return res.json() as Promise<T>;
  }

  async login(url: string, email: string, password: string): Promise<string> {
    const res = await fetch(`${url.replace(/\/$/, '')}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new Error(`Login failed: ${body}`);
    }
    const data = await res.json() as { access_token: string };
    return data.access_token;
  }

  async listRuns(limit = 20): Promise<any[]> {
    const data = await this.fetch<any>(`/factory/runs?limit=${limit}`);
    return data?.items ?? data?.runs ?? (Array.isArray(data) ? data : []);
  }

  async getRun(runId: string): Promise<any> {
    return this.fetch<any>(`/factory/runs/${runId}`);
  }

  async startRun(requirement: string, domain = 'general', name?: string): Promise<any> {
    return this.fetch<any>('/factory/start', {
      method: 'POST',
      body: JSON.stringify({ raw_input: requirement, domain, ...(name ? { project_name: name } : {}) }),
    });
  }

  async cancelRun(runId: string): Promise<void> {
    await this.fetch<any>(`/factory/runs/${runId}/cancel`, { method: 'POST' });
  }

  async getHealth(): Promise<any> {
    return this.fetch<any>('/health');
  }

  async streamLogs(runId: string, onEvent: (ev: LogEvent) => void): Promise<void> {
    const url = `${this.gatewayUrl}/factory/runs/${runId}/stream`;
    const res = await fetch(url, {
      headers: { ...this.headers(), 'Accept': 'text/event-stream' },
    });
    if (!res.ok || !res.body) throw new Error(`Stream failed: ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const payload = line.slice(5).trim();
        if (payload === '[DONE]') return;
        try { onEvent(JSON.parse(payload)); } catch { /* skip malformed */ }
      }
    }
  }
}
