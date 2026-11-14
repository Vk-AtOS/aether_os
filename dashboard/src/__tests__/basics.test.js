import { beforeEach, describe, expect, it, vi } from 'vitest';

const store = {};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};

const { api } = await import('../api');
const { decode } = await import('../hooks/useRole');
const { appPath } = await import('../appUrl');
const { nextDelay } = await import('../hooks/useRunStream');

const jwt = (payload) => `h.${btoa(JSON.stringify(payload)).replace(/=/g, '')}.s`;

describe('api client', () => {
  beforeEach(() => { Object.keys(store).forEach((k) => delete store[k]); });

  it('stores and clears the tokens', () => {
    api.setToken('a', 'r');
    expect(api.getToken()).toBe('a');
    expect(store.aether_refresh_token).toBe('r');
    api.clearToken();
    expect(api.getToken()).toBeNull();
  });

  it('logout revokes the session server-side and still clears locally when that fails', async () => {
    api.setToken('a', 'r');
    const post = vi.spyOn(api.client, 'post').mockRejectedValue(new Error('offline'));
    await api.logout();
    expect(post).toHaveBeenCalledWith('/auth/logout');
    expect(api.getToken()).toBeNull();
    post.mockRestore();
  });

  it('deleteOrg uses the backend route /org', async () => {
    const del = vi.spyOn(api.client, 'delete').mockResolvedValue({});
    await api.deleteOrg();
    expect(del).toHaveBeenCalledWith('/org');
  });

  it('adds the bearer token to requests', async () => {
    api.setToken('tok');
    const cfg = await api.client.interceptors.request.handlers[0].fulfilled({ headers: {} });
    expect(cfg.headers.Authorization).toBe('Bearer tok');
  });
});

describe('role gating', () => {
  it('reads the role from the token and rejects garbage', () => {
    expect(decode(jwt({ role: 'admin' })).role).toBe('admin');
    expect(decode('not-a-jwt')).toBeNull();
  });
});

describe('urls and reconnect', () => {
  it('in-app URLs carry the /dashboard base', () => {
    vi.stubEnv('BASE_URL', '/dashboard/');   // the test run does not inherit vite.config.js base
    expect(appPath('/admin/billing?upgrade=success')).toBe('/dashboard/admin/billing?upgrade=success');
  });
  it('reconnect backoff doubles and is capped', () => {
    expect([0, 1, 2].map(nextDelay)).toEqual([1000, 2000, 4000]);
    expect(nextDelay(20)).toBe(30000);
  });
});
