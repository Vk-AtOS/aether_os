import { describe, expect, it } from 'vitest';
import { readinessStatus } from '../readiness';

describe('readinessStatus', () => {
  it('shows nothing when everything is up', () => {
    expect(readinessStatus({ ready: true, degraded: [] })).toBeNull();
  });
  it('names degraded components without calling the system down', () => {
    expect(readinessStatus({ ready: true, degraded: ['velaris'] })).toEqual({ label: 'Degraded: velaris', level: 'warning' });
  });
  it('is critical when not ready', () => {
    expect(readinessStatus({ ready: false, degraded: ['postgres'] }).level).toBe('critical');
  });
  it('ignores malformed answers', () => {
    expect(readinessStatus(null)).toBeNull();
    expect(readinessStatus({ status: 'ok' })).toBeNull();
  });
});
