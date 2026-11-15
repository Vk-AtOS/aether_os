import { describe, expect, it } from 'vitest';
import { costText, keyShown, providerError, testMessage, toggleLevel } from '../components/settings/providerHelpers';

describe('provider panel helpers', () => {
  it('a free pool can never be given restricted', () => {
    expect(toggleLevel(['public'], 'restricted', true)).toEqual(['public']);
    expect(toggleLevel(['public'], 'restricted', false)).toEqual(['public', 'restricted']);
    expect(toggleLevel(['public', 'internal'], 'internal', true)).toEqual(['public']);
  });

  it('shows only the last four characters of a key', () => {
    expect(keyShown({ has_key: true, key_last4: '7890' })).toBe('••••7890');
    expect(keyShown({ has_key: false })).toBe('no key');
  });

  it('the test result is a fixed sentence, never provider text', () => {
    expect(testMessage({ ok: false, error: 'key_rejected' })).toMatch(/rejected the key/);
    expect(testMessage({ ok: false, error: 'something secret sk-123' })).toBe('The test failed.');
    expect(testMessage({ ok: true, models: 3, latency_s: 0.2 })).toMatch(/Working/);
  });

  it('reads both error shapes', () => {
    expect(providerError({ response: { data: { error: { message: 'no' } } } }, 'x')).toBe('no');
    expect(providerError({ response: { data: { detail: 'denied' } } }, 'x')).toBe('denied');
    expect(providerError({}, 'fallback')).toBe('fallback');
  });

  it('unknown cost is not zero', () => {
    expect(costText({ cost_usd: 0, unpriced_calls: 2 })).toBe('unknown');
    expect(costText({ cost_usd: 0.0123, unpriced_calls: 0 })).toBe('$0.0123');
  });
});
