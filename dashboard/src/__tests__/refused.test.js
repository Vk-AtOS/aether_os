import { describe, it, expect } from 'vitest';
import { refused } from '../components/velaris/velarisApi';

describe('refused (an agent result that is a refusal)', () => {
  it('is a refusal when it is not ok and says why, or has a refusal kind', () => {
    expect(refused({ status: 'denied', reason: 'not on the panel' })).toBe(true);
    expect(refused({ status: 'conflict' })).toBe(true);
    expect(refused({ status: 'weird', errors: ['bad'] })).toBe(true);
  });
  it('is not a refusal for ok, or for a data field called status (evidence_view: the session is "open")', () => {
    expect(refused({ status: 'ok' })).toBe(false);
    expect(refused({ status: 'open', session_id: 's1', consents: {} })).toBe(false);
    expect(refused({})).toBe(false);
    expect(refused(null)).toBe(false);
  });
});
