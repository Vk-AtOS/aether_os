import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const root = join(import.meta.dirname, '..');
const walk = (dir) => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  if (statSync(p).isDirectory()) return f === '__tests__' ? [] : walk(p);
  return /\.(jsx?|tsx?)$/.test(f) && f !== 'api.js' ? [p] : [];
});

describe('api.js', () => {
  it('has no wrapper that nothing calls, and SystemHealth has no dead fallback route', () => {
    const api = readFileSync(join(root, 'api.js'), 'utf8');
    const used = walk(root).map((f) => readFileSync(f, 'utf8')).join('\n');
    // Top-level wrappers only (two-space indent), skipping the raw client and the base URL.
    const names = [...api.matchAll(/^ {2}([A-Za-z]+): /gm)].map((m) => m[1]).filter((n) => !['client', 'baseURL', 'operator'].includes(n));
    const dead = names.filter((n) => !new RegExp(`\\b${n}\\b`).test(used));
    expect(dead).toEqual([]);
    expect(readFileSync(join(root, 'pages/SystemHealth.tsx'), 'utf8')).not.toContain('/health/metrics');
  });
});
